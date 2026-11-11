"""The weekly "what's new in Signals" email, Layer's weekly update (uselayer/layer lib/weekly.ts) for Signals users
(owner, 11 Nov 2026: "we should have one for signals as well"). Signals' only email to every user.

  The day before the send day, from DRAFT_HOUR Pacific: the engine reads the week's merged pull requests in
    uselayer/signals (public: GitHub's API, GITHUB_TOKEN optional), has Claude write the issue (OpenRouter,
    SIGNALS_WEEKLY_MODEL) and keeps it in STORE_DIR/weekly.db.
  Then: David gets the preview, with video ideas on top (his eyes only) and an "Approve and send" link. A week with
    nothing a user would notice gets a short note instead, and nothing goes out. A draft that fails is tried again
    each hour that day, and David hears about it once.
  On approve (/api/weekly/approve, signed; the GET only shows a button, so a mail scanner opening the link can't
    approve it): one email per reader, scheduled with Resend for SEND_HOUR on the send day in the reader's time zone
    (saved from their browser when the page reads /api/me; Eastern when unknown). A link opened after the send day
    sends nothing. Each email has a one-click unsubscribe (/api/weekly/unsubscribe).

Readers: every Clerk account with an email (a Telegram-only sign-in has none), minus the owner's and anyone who
unsubscribed. Nothing reaches a reader without David's approval; nothing here logs an email address or a key.

  CLERK_SECRET_KEY          reads the accounts (Backend API); off without it
  RESEND_API_KEY            sends; off without it
  OPENROUTER_API_KEY        writes the draft; off without it
  SIGNALS_WEEKLY=0          turns it all off
  SIGNALS_WEEKLY_SEND_DAY   the send day (default thursday); the draft comes the afternoon before
  SIGNALS_WEEKLY_FROM       sender (default SIGNALS_WELCOME_FROM, else "David from Signals <david@uselayer.sh>")
  SIGNALS_WEEKLY_PREVIEW_TO who gets the preview (default pemakenemi56@gmail.com)
  SIGNALS_WEEKLY_NOTES      David's notes for the writer about the week (e.g. something no pull request says)
  SIGNALS_WEEKLY_MODEL      the writer (default anthropic/claude-sonnet-5, as Layer's)
  SIGNALS_WEEKLY_SECRET     signs the approve and unsubscribe links (default: derived from CLERK_SECRET_KEY)
  SIGNALS_OWNER_EMAILS, SIGNALS_OWNER_USER, SIGNALS_WELCOME_REPLY: as in signals/welcome.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from signals import welcome

REPO = "uselayer/signals"
SITE = "https://usesignals.app"
PT = ZoneInfo("America/Los_Angeles")
DEFAULT_TZ = "America/New_York"
SEND_HOUR = 9
DRAFT_HOUR = 13  # Pacific, on the day before the send day
RETRY_S = 3600  # a failed draft is tried again this long after
RESEND_MAX_AHEAD_S = 29 * 86400  # Resend schedules at most 30 days ahead; a day of margin
SOONEST_S = 120  # a reader whose 9 AM has passed (approved late) gets it this long after approval
OWNER_DEFAULT = welcome.OWNER_DEFAULT
FROM_DEFAULT = "David from Signals <david@uselayer.sh>"
MODEL_DEFAULT = "anthropic/claude-sonnet-5"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]  # date.weekday() order

# The pages an item may point at, all open to everyone (the Feed asks a signed-out visitor to sign in).
PAGES = {
    "/": "Feed: trades from the traders you follow (signed in)",
    "/#/recommended": "Feed, Top traders: $1,000+ trades from the leaderboard's top traders",
    "/#/big": "Feed, Big trades: the biggest trades right now",
    "/#/watchlist": "Watchlist: the open trades of everyone you follow",
    "/#/traders": "Traders: the leaderboard of Polymarket traders' track records",
    "/breakdowns/": "Breakdowns: ask AI to break down how a trader or market trades",
}

# Words an email to traders never has (AGENTS.md: "trade", never "bet"; never "sandbox" or "paper"; nothing about
# copying, which only the owner has). A draft that has one is flagged in David's preview, never sent unflagged.
NEVER = re.compile(r"\b(bets?|betting|bettors?|sandbox|paper|cop(?:y|ies|ied|ying)|copy-?trad\w*|guarantee\w*|"
                   r"risk-free|sure thing)\b", re.I)  # fmt: skip

_SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, status TEXT NOT NULL, draft TEXT, skip_reason TEXT,
  prs TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL, previewed_at REAL, approved_at REAL, failed_at REAL,
  fail_reason TEXT, fail_told_at REAL);
CREATE TABLE IF NOT EXISTS sends (issue_id TEXT NOT NULL, uid TEXT NOT NULL, scheduled_for TEXT NOT NULL,
  result TEXT, PRIMARY KEY (issue_id, uid));
CREATE TABLE IF NOT EXISTS readers (uid TEXT PRIMARY KEY, tz TEXT, unsubscribed_at REAL);
"""

Send = welcome.Send  # (payload, idempotency key) → True, False (try again) or "dead"


# ---- days and time zones ----


def send_day(env: dict[str, str]) -> int:
    name = env.get("SIGNALS_WEEKLY_SEND_DAY", "thursday").strip().lower()
    return DAYS.index(name) if name in DAYS else DAYS.index("thursday")


def _pt_today(now: float) -> date:
    return datetime.fromtimestamp(now, PT).date()


def next_send_date(now: float, day: int) -> str:
    """The next send date (YYYY-MM-DD) strictly after today in Pacific time: run on Wednesday, it's Thursday."""
    today = _pt_today(now)
    ahead = (day - today.weekday()) % 7 or 7
    return (today + timedelta(days=ahead)).isoformat()


def is_draft_time(now: float, day: int) -> bool:
    """The day before the send day, from DRAFT_HOUR, in Pacific time."""
    t = datetime.fromtimestamp(now, PT)
    return (t.weekday() + 1) % 7 == day and t.hour >= DRAFT_HOUR


def valid_tz(tz: str | None) -> str | None:
    if not tz or len(tz) > 64 or not re.fullmatch(r"[A-Za-z0-9_+\-/]+", tz):
        return None
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return tz


def local_nine(send_date: str, tz: str) -> datetime:
    """SEND_HOUR on that date in that zone, in UTC."""
    y, m, d = map(int, send_date.split("-"))
    return datetime(y, m, d, SEND_HOUR, tzinfo=ZoneInfo(tz)).astimezone(UTC)


def long_date(send_date: str) -> str:
    """Thursday, November 12"""
    d = date.fromisoformat(send_date)
    return f"{d:%A}, {d:%B} {d.day}"


# ---- signed links ----


def _secret(env: dict[str, str]) -> bytes:
    if s := env.get("SIGNALS_WEEKLY_SECRET", ""):
        return s.encode()
    clerk = env.get("CLERK_SECRET_KEY", "")
    if not clerk:
        raise RuntimeError("SIGNALS_WEEKLY_SECRET or CLERK_SECRET_KEY must be set to sign weekly-update links")
    return hmac.new(clerk.encode(), b"signals-weekly-links", hashlib.sha256).digest()


def sign(purpose: str, ident: str, env: dict[str, str]) -> str:
    mac = hmac.new(_secret(env), f"{purpose}:{ident}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def verify(purpose: str, ident: str, sig: str | None, env: dict[str, str]) -> bool:
    if not sig or not ident:
        return False
    try:
        return hmac.compare_digest(sign(purpose, ident, env).encode(), sig.encode())
    except (RuntimeError, UnicodeEncodeError):
        return False


def approve_url(issue_id: str, env: dict[str, str], site: str = SITE) -> str:
    return f"{site}/api/weekly/approve?issue={urllib.parse.quote(issue_id)}&sig={sign('approve', issue_id, env)}"


def unsubscribe_url(uid: str, env: dict[str, str], site: str = SITE) -> str:
    return f"{site}/api/weekly/unsubscribe?u={urllib.parse.quote(uid)}&sig={sign('unsubscribe', uid, env)}"


# ---- the email ----


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def flags(draft: dict[str, Any]) -> list[str]:
    """What David should check before approving: words an email to traders never has."""
    out = []
    parts = [("Subject", draft.get("subject", "")), ("Preheader", draft.get("preheader", "")), ("Closing", draft.get("ask", ""))]
    parts += [(f"TL;DR {i + 1}", t) for i, t in enumerate(draft.get("tldr") or [])]
    parts += [(f"Item {i + 1}", f"{it['lead']} {it['body']}") for i, it in enumerate(draft.get("items") or [])]
    for where, text in parts:
        words = sorted({m.group(0).lower() for m in NEVER.finditer(text)})
        if words:
            out.append(f"{where} says {', '.join(repr(w) for w in words)}")
    return out


def render(draft: dict[str, Any], *, unsubscribe: str, site: str = SITE, preview: dict[str, Any] | None = None) -> dict[str, str]:
    """The email: {"subject", "html", "text"}. ``preview`` ({"approve", "recipients", "send_date"}) adds David's banner."""
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    items = draft["items"]
    ideas = [f'Item {i + 1} ("{it["lead"]}") would land better with a 30-second video: {it["video_hint"]}'
             for i, it in enumerate(items) if it.get("video_hint")]  # fmt: skip
    checks = flags(draft) if preview else []
    banner = ""
    if preview:
        n = preview["recipients"]
        banner = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;'
            'background:#FFF7DB;border:1px solid #E6C229;border-radius:8px;"><tr><td style="padding:16px 18px;'
            'font-size:14px;line-height:1.5;color:#141519;">\n'
            '<p style="margin:0 0 8px;font-weight:600;">Preview for you only. Nothing has been sent.</p>\n'
            + (f'<p style="margin:0 0 4px;font-weight:700;color:#B42318;">Check before approving</p><ul style="margin:0 0 12px;'
               f'padding-left:18px;color:#B42318;">{"".join(f"<li>{esc(t)}</li>" for t in checks)}</ul>\n' if checks else "")
            + f'<p style="margin:0 0 {"8px" if ideas else "14px"};">Approving schedules it for {n} {"reader" if n == 1 else "readers"} '
            f'at 9 AM on {esc(long_date(preview["send_date"]))}, each in their own time zone.</p>\n'
            + (f'<p style="margin:0 0 4px;font-weight:600;">Video ideas</p><ul style="margin:0 0 14px;padding-left:18px;">'
               f'{"".join(f"<li>{esc(t)}</li>" for t in ideas)}</ul>\n' if ideas else "")
            + f'<a href="{esc(preview["approve"])}" style="display:inline-block;padding:10px 16px;background:#141519;'
            'color:#FFFFFF;border-radius:6px;text-decoration:none;font-weight:600;">Approve and send &rarr;</a>\n'
            "</td></tr></table>"
        )  # fmt: skip

    def link(it: dict[str, Any]) -> str:
        if not it.get("page"):
            return ""
        return (f'<p style="margin:6px 0 0;"><a href="{esc(site + it["page"])}" style="color:#141519;font-weight:600;">'
                "Open it on Signals &rarr;</a></p>")  # fmt: skip

    rows = "\n".join(
        f'<li style="margin:0 0 0 1em;padding:0.4em 0 0.8em"><p style="margin:0"><strong>{esc(it["lead"])}</strong> '
        f"{esc(it['body'])}</p>{link(it)}</li>"
        for it in items
    )
    tldr = draft.get("tldr") or []
    top = (
        '<p style="margin:0;padding:0.4em 0 0.2em;font-size:12px;font-weight:700;letter-spacing:.06em;color:#67655F;">TL;DR</p>\n'
        f'<ul style="margin:0;padding:0 0 0.4em 1.1em;">{"".join(f"<li style=\"margin:0 0 0 0.6em;padding:0.15em 0;\">{esc(t)}</li>" for t in tldr)}</ul>'
        if tldr else ""
    )  # fmt: skip
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta name="x-apple-disable-message-reformatting"><title>{esc(draft["subject"])}</title></head>
<body style="margin:0;padding:0;background:#ffffff;">
<div style="display:none;overflow:hidden;line-height:1px;opacity:0;max-height:0;max-width:0">{esc(draft["preheader"])}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 16px;font-family:{font};font-size:16px;line-height:155%;color:#141519;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;"><tr><td style="text-align:left;">
{banner}
{top}
<p style="margin:0;padding:1.1em 0 0.3em;font-size:18px;line-height:1.3;font-weight:700;">What&rsquo;s new this week</p>
<ul style="margin:0;padding:0;padding-left:1.1em;padding-bottom:0.5em">
{rows}
</ul>
<p style="margin:0;padding:0.5em 0">{esc(draft["ask"])} Just reply here.<br><br>David<br><span style="color:#67655F;">Founder, Signals</span></p>
<hr style="width:100%;border:none;border-top:2px solid #eaeaea;margin:16px 0 0;">
<p style="margin:0;padding:0.8em 0;font-size:13px;color:#67655F;">You're getting this because you signed up for Signals at <a href="{esc(site)}" style="color:#67655F;">usesignals.app</a>. <a href="{esc(unsubscribe)}" style="color:#67655F;">Unsubscribe</a> from these weekly updates.</p>
</td></tr></table>
</td></tr></table>
</body></html>"""
    text = []
    if preview:
        text += [f"PREVIEW FOR YOU ONLY. Approve and send: {preview['approve']}", *(f"- CHECK: {t}" for t in checks),
                 *(f"- {t}" for t in ideas), "", "----------", ""]  # fmt: skip
    if tldr:
        text += ["TL;DR", *(f"- {t}" for t in tldr), ""]
    text += ["WHAT'S NEW THIS WEEK", ""]
    for it in items:
        text += [f"- {it['lead']} {it['body']}" + (f" {site}{it['page']}" if it.get("page") else ""), ""]
    text += [f"{draft['ask']} Just reply here.", "", "David", "Founder, Signals", "", f"Unsubscribe: {unsubscribe}"]
    return {"subject": draft["subject"], "html": body, "text": "\n".join(text)}


# ---- the writer ----

SYSTEM = """You write Signals' weekly product update email, in the voice of David, who builds Signals.

Signals (usesignals.app) shows what Polymarket traders do: a leaderboard of traders' real track records (profit, win rate, how they usually trade), a page per trader, a Feed of trades from the traders you follow, a Watchlist of their open trades, Telegram alerts the moment a trader you follow trades (with a rule for which trades), and Breakdowns, where AI breaks down how a trader or a market trades. For each open trade it shows what buying it now would really cost; the reader buys on Polymarket themselves. Readers are people who signed up: traders who want to see what good Polymarket traders are doing.

You get the pull requests merged this week in Signals (uselayer/signals). Keep ONLY changes a user would notice: new features, new pages or views, clearer screens, better alerts, fixes to things users would have hit. Drop internal work: refactors, tests, CI, monitoring, analytics and tracking, emails and alerts to the team, admin or owner-only tools, research studies and notes (anything under research/), deploy and hosting changes, and anything not live for every user.

Every item must be something any signed-up user can open and try today. Leave out anything behind a flag, invite-only, owner-only or still being tested. In particular, never mention copying a trade or one-tap copy (only the owner has it), the skill test or "Recommended" traders, Kalshi or Polymarket US features, or the trader directory. When in doubt, leave it out.

David may add notes about the week that aren't pull requests, or instructions for this issue (which item goes first, exact wording). Treat the facts as true and include them when they qualify, and follow his instructions over the rules above.

If nothing qualifies, set worth_sending to false and say why in skip_reason, in one sentence.

Otherwise write the email:
- subject: plain and specific, under 60 characters, naming the biggest change. No emoji, no "newsletter", no hype words.
- preheader: one plain sentence on what the reader gets.
- tldr: one short line per item, in the same order as the items, value first, at most about 12 words each.
- items: 1 to 4, most useful first. lead = one bold sentence that says what the reader can now do. body = 1-2 sentences: why it matters and where to try it. Plain words: no code, no field or file names, no PR numbers, no internal names.
- page: the one page that best shows the item, chosen ONLY from the list given, or null.
- video_hint: if a 30-second screen recording would explain the item much better than words (a flow with several steps, something that moves), say what it should show in one sentence; else null. Only David sees this.
- ask: one closing question inviting a reply, e.g. "Which trader should Signals cover better?"

How to write it:
- Lead with what the reader gets, in plain, short words. Say what they can do now, never homework.
- Short: people skim. No explaining how Signals works inside (how often it reads, delays, UTC times).
- Never talk about access changes ("now open to everyone"). Just say what's live.
- Say "trade" and "trader", never "bet", "bettor" or "gambling". Never "sandbox", "paper" or "copy".
- Facts, not advice: never suggest that following a trader makes money, never tell anyone what to buy, never promise what's coming.
- Never invent features, numbers or dates that aren't in the pull requests or David's notes."""

_ANSWER = {
    "type": "object", "additionalProperties": False,
    "required": ["worth_sending", "skip_reason", "subject", "preheader", "tldr", "items", "ask"],
    "properties": {
        "worth_sending": {"type": "boolean"}, "skip_reason": {"type": "string"}, "subject": {"type": "string"},
        "preheader": {"type": "string"}, "tldr": {"type": "array", "items": {"type": "string"}},
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["lead", "body", "page", "video_hint"],
            "properties": {"lead": {"type": "string"}, "body": {"type": "string"}, "page": {"type": ["string", "null"]},
                           "video_hint": {"type": ["string", "null"]}}}},
        "ask": {"type": "string"},
    },
}  # fmt: skip


def merged_since(since: float, token: str = "", fetch: Callable[[str, dict[str, str]], Any] | None = None) -> list[dict[str, Any]]:
    """Every pull request merged into uselayer/signals since ``since``, newest first: {number, title, body, merged_at, url}."""

    def get(url: str, headers: dict[str, str]) -> Any:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            return json.loads(r.read())

    fetch = fetch or get
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "signals"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    out: list[dict[str, Any]] = []
    for page in range(1, 11):
        rows = fetch(f"https://api.github.com/repos/{REPO}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}", headers)
        for r in rows:
            merged = r.get("merged_at")
            if merged and _iso(merged) >= since:
                out.append({"number": r["number"], "title": r["title"], "body": (r.get("body") or "")[:1500],
                            "merged_at": merged, "url": r["html_url"]})  # fmt: skip
        # sorted by last update: once a page ends before ``since``, nothing later merged in the window
        if len(rows) < 100 or _iso(rows[-1]["updated_at"]) < since:
            break
    return sorted(out, key=lambda p: p["merged_at"], reverse=True)


def _iso(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def allowed_page(page: str | None) -> str | None:
    if not page:
        return None
    clean = re.sub(r"^https?://(www\.)?usesignals\.app", "", page.strip()) or "/"
    return clean if clean in PAGES else None


def to_draft(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """A model answer as (draft, "") or (None, why there's nothing to send). Pages not on the list are dropped; 1–4 items."""
    items = [{"lead": str(it.get("lead") or "").strip(), "body": str(it.get("body") or "").strip(),
              "page": allowed_page(it.get("page")), "video_hint": (str(it.get("video_hint") or "").strip() or None)}
             for it in raw.get("items") or [] if str(it.get("lead") or "").strip() and str(it.get("body") or "").strip()][:4]  # fmt: skip
    if not raw.get("worth_sending") or not items:
        return None, str(raw.get("skip_reason") or "").strip() or "Nothing merged this week would be noticed by users."
    given = raw.get("tldr") or []
    tldr = [(str(given[i]).strip() if i < len(given) else "") or it["lead"] for i, it in enumerate(items)]
    return {"subject": str(raw.get("subject") or "").strip()[:90] or "What's new in Signals",
            "preheader": str(raw.get("preheader") or "").strip(), "tldr": tldr, "items": items,
            "ask": str(raw.get("ask") or "").strip() or "What should Signals do next?"}, ""  # fmt: skip


Writer = Callable[[list[dict[str, Any]], str], "tuple[dict[str, Any] | None, str]"]


def openrouter_writer(key: str, model: str) -> Writer:
    def once(prs: list[dict[str, Any]], notes: str) -> tuple[dict[str, Any] | None, str]:
        listing = "\n\n".join(f"### {p['title']}\nMerged {p['merged_at'][:10]}\n{p['body'].strip() or '(no description)'}" for p in prs)
        pages = "\n".join(f"{path} — {what}" for path, what in PAGES.items())
        user = (f"Pages you may pick from:\n{pages}" + (f"\n\nDavid's notes about this week:\n{notes.strip()}" if notes.strip() else "")
                + f"\n\nPull requests merged this week:\n\n{listing or '(none)'}")  # fmt: skip
        body = {"model": model, "max_tokens": 12000, "reasoning": {"max_tokens": 3000},
                "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                "response_format": {"type": "json_schema", "json_schema": {"name": "weekly", "strict": True, "schema": _ANSWER}}}  # fmt: skip
        req = urllib.request.Request(ENDPOINT, json.dumps(body).encode(), {
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "Signals weekly update"})  # fmt: skip
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"the writer answered {e.code}") from None
        text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(f"the writer returned no JSON ({len(text)} characters)")
        return to_draft(json.loads(text[start : end + 1]))

    def write(prs: list[dict[str, Any]], notes: str) -> tuple[dict[str, Any] | None, str]:
        if not prs and not notes.strip():
            return None, "Nothing merged in Signals this week."
        try:
            return once(prs, notes)
        except (OSError, ValueError, RuntimeError) as e:
            print(f"weekly: the writer failed, trying once more: {type(e).__name__}: {e}", flush=True)
            return once(prs, notes)

    return write


# ---- storage ----


def _db(store: Path) -> sqlite3.Connection:
    store.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(store / "weekly.db", timeout=10)
    con.executescript(_SCHEMA)
    return con


def get_issue(store: Path, issue_id: str) -> dict[str, Any] | None:
    with _db(store) as con:
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["draft"] = json.loads(d["draft"]) if d["draft"] else None
    d["prs"] = json.loads(d["prs"] or "[]")
    return d


def save_issue(store: Path, issue_id: str, draft: dict[str, Any] | None, skip_reason: str, prs: list[dict[str, Any]], now: float) -> bool:
    """Keeps a new draft (or skip) for that send date, replacing one not approved yet; False once it's approved."""
    row = (issue_id, "drafted" if draft else "skipped", json.dumps(draft) if draft else None, skip_reason or None,
           json.dumps([{k: p[k] for k in ("number", "title", "url")} for p in prs]), now)  # fmt: skip
    with _db(store) as con:
        cur = con.execute(
            "INSERT INTO issues (id, status, draft, skip_reason, prs, created_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET status = excluded.status, draft = excluded.draft,"
            " skip_reason = excluded.skip_reason, prs = excluded.prs, created_at = excluded.created_at,"
            " previewed_at = NULL, approved_at = NULL, failed_at = NULL, fail_reason = NULL, fail_told_at = NULL"
            " WHERE issues.status IN ('drafted', 'skipped', 'failed')",
            row,
        )
        return cur.rowcount > 0


def remember_tz(store: Path, uid: str, tz: str | None) -> bool:
    """The reader's time zone, from their browser (the page sends it with /api/me). Whether it changed."""
    tz = valid_tz(tz)
    if not uid or not tz:
        return False
    with _db(store) as con:
        cur = con.execute("INSERT INTO readers (uid, tz) VALUES (?, ?) ON CONFLICT (uid) DO UPDATE SET tz = excluded.tz"
                          " WHERE readers.tz IS NOT excluded.tz", (uid, tz))  # fmt: skip
        return cur.rowcount > 0


def unsubscribe(store: Path, uid: str, now: float) -> None:
    with _db(store) as con:
        con.execute("INSERT INTO readers (uid, unsubscribed_at) VALUES (?, ?) ON CONFLICT (uid) DO UPDATE SET"
                    " unsubscribed_at = COALESCE(readers.unsubscribed_at, excluded.unsubscribed_at)", (uid, now))  # fmt: skip


def approve(store: Path, issue_id: str, now: float) -> bool:
    """drafted → approved, once. False when it isn't waiting for approval."""
    with _db(store) as con:
        return con.execute("UPDATE issues SET status = 'approved', approved_at = ? WHERE id = ? AND status = 'drafted'",
                           (now, issue_id)).rowcount > 0  # fmt: skip


def too_late(issue: dict[str, Any], now: float) -> bool:
    """Past the send day in Pacific time: "this week" would be last week by now."""
    return _pt_today(now).isoformat() > issue["id"]


# ---- readers (Clerk) ----


def clerk_all(secret: str) -> list[dict[str, Any]]:
    """Every Clerk account, oldest first. Raises on a failed read."""
    out: list[dict[str, Any]] = []
    for offset in range(0, 50_000, 100):
        req = urllib.request.Request(f"https://api.clerk.com/v1/users?order_by=created_at&limit=100&offset={offset}",
                                     headers={"Authorization": f"Bearer {secret}", "User-Agent": "signals"})  # fmt: skip
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        page = data if isinstance(data, list) else list(data.get("data") or [])
        out += page
        if len(page) < 100:
            break
    return out


def readers(store: Path, users: list[dict[str, Any]], env: dict[str, str]) -> list[dict[str, Any]]:
    """Everyone with an email, not banned, not unsubscribed, minus the owner: [{"uid", "email", "tz"}]."""
    owners = {e.strip().lower() for e in env.get("SIGNALS_OWNER_EMAILS", OWNER_DEFAULT).split(",") if e.strip()}
    owner_user = env.get("SIGNALS_OWNER_USER", "")
    with _db(store) as con:
        kept = {uid: (tz, off) for uid, tz, off in con.execute("SELECT uid, tz, unsubscribed_at FROM readers")}
    out = []
    for u in users:
        s = welcome.sign_up_of(u)
        if not s or not s.email or u.get("banned") or u.get("locked") or s.uid == owner_user or s.email.lower() in owners:
            continue
        tz, off = kept.get(s.uid, (None, None))
        if off is None:
            out.append({"uid": s.uid, "email": s.email, "tz": tz})
    return out


# ---- sending ----


def _from(env: dict[str, str]) -> str:
    return env.get("SIGNALS_WEEKLY_FROM") or env.get("SIGNALS_WELCOME_FROM") or FROM_DEFAULT


def schedule(store: Path, issue_id: str, people: list[dict[str, Any]], send: Send, now: float, env: dict[str, str],
             site: str = SITE) -> dict[str, int]:  # fmt: skip
    """One email per reader, scheduled for 9 AM on the send date in their zone (one already past goes out in two
    minutes). Each reader is claimed in ``sends`` before sending, so a retry never sends twice."""
    issue = get_issue(store, issue_id)
    out = {"scheduled": 0, "failed": 0, "dropped": 0, "later": 0, "total": len(people)}
    if not issue or not issue["draft"] or issue["status"] not in ("approved", "scheduled"):
        return out
    with _db(store) as con:
        done = {uid for (uid,) in con.execute("SELECT uid FROM sends WHERE issue_id = ?", (issue_id,))}
    soonest = datetime.fromtimestamp(now + SOONEST_S, UTC)
    latest = datetime.fromtimestamp(now + RESEND_MAX_AHEAD_S, UTC)
    for p in people:
        if p["uid"] in done:
            continue
        at = max(local_nine(issue_id, valid_tz(p["tz"]) or DEFAULT_TZ), soonest)
        if at > latest:
            out["later"] += 1
            continue
        when = at.isoformat().replace("+00:00", "Z")
        with _db(store) as con:
            if not con.execute("INSERT OR IGNORE INTO sends (issue_id, uid, scheduled_for) VALUES (?, ?, ?)",
                               (issue_id, p["uid"], when)).rowcount:  # fmt: skip
                continue
        unsub = unsubscribe_url(p["uid"], env, site)
        mail = render(issue["draft"], unsubscribe=unsub, site=site)
        r = send({"from": _from(env), "to": [p["email"]], "reply_to": env.get("SIGNALS_WELCOME_REPLY", welcome.REPLY_DEFAULT),
                  **mail, "scheduled_at": when,
                  "headers": {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}},
                 f"signals-weekly-{issue_id}-{p['uid']}")  # fmt: skip
        with _db(store) as con:
            if r is True:
                out["scheduled"] += 1
            elif r == "dead":
                out["dropped"] += 1
                con.execute("UPDATE sends SET result = 'refused' WHERE issue_id = ? AND uid = ?", (issue_id, p["uid"]))
            else:
                out["failed"] += 1
                con.execute("DELETE FROM sends WHERE issue_id = ? AND uid = ?", (issue_id, p["uid"]))
    if out["failed"] == 0 and out["later"] == 0:
        with _db(store) as con:
            con.execute("UPDATE issues SET status = 'scheduled' WHERE id = ? AND status = 'approved'", (issue_id,))
    return out


def _plain(subject: str, text: str, env: dict[str, str]) -> dict[str, Any]:
    return {"from": _from(env), "to": [env.get("SIGNALS_WEEKLY_PREVIEW_TO", OWNER_DEFAULT)], "subject": subject,
            "text": text, "html": welcome.plain_html(text)}  # fmt: skip


def preview(store: Path, issue: dict[str, Any], recipients: int, send: Send, env: dict[str, str], site: str = SITE) -> bool:
    """David's preview of a drafted issue, or the "nothing this week" note for a skipped one."""
    if issue["status"] == "skipped" or not issue["draft"]:
        prs = [f"- {p['title']} (#{p['number']})" for p in issue["prs"]]
        text = "\n".join([
            "Nothing merged in Signals this week looks like something a user would notice, so there's no update to "
            "send, and nothing went out.", "",
            *([f"Why: {issue['skip_reason']}", ""] if issue.get("skip_reason") else []),
            *(["What did merge:", *prs] if prs else ["Nothing merged this week."]), "",
            "If one of these should go out, ask Claude to re-run the Signals weekly draft with a note.",
        ])  # fmt: skip
        mail = _plain(f"No Signals update this week ({long_date(issue['id'])})", text, env)
    else:
        r = render(issue["draft"], unsubscribe=f"{site}/api/weekly/unsubscribe?u=preview", site=site,
                   preview={"approve": approve_url(issue["id"], env, site), "recipients": recipients, "send_date": issue["id"]})  # fmt: skip
        mail = {"from": _from(env), "to": [env.get("SIGNALS_WEEKLY_PREVIEW_TO", OWNER_DEFAULT)],
                "subject": f"[Preview] {r['subject']}", "html": r["html"], "text": r["text"]}  # fmt: skip
    return send(mail, f"signals-weekly-preview-{issue['id']}-{issue['created_at']}") is True


# ---- the job ----


def check(
    now: float,
    store: Path,
    *,
    env: dict[str, str] | None = None,
    site: str = SITE,
    users: Callable[[str], list[dict[str, Any]]] = clerk_all,
    prs_since: Callable[[float, str], list[dict[str, Any]]] = merged_since,
    writer: Writer | None = None,
    send: Send | None = None,
    force: bool = False,
    notes: str | None = None,
) -> dict[str, Any]:
    """One pass (each minute, ``_weekly_loop``): the draft once it's time, David's preview of it, and every approved
    issue's emails. ``force`` drafts now for the next send date (replacing a draft not approved yet)."""
    env = dict(os.environ) if env is None else env
    if env.get("SIGNALS_WEEKLY", "1") == "0":
        return {"off": "SIGNALS_WEEKLY=0"}
    missing = [k for k in ("CLERK_SECRET_KEY", "RESEND_API_KEY", "OPENROUTER_API_KEY") if not env.get(k)]
    if missing:
        return {"off": f"needs {', '.join(missing)}"}
    secret = env["CLERK_SECRET_KEY"]
    send = send or welcome.resend_send(env["RESEND_API_KEY"])
    writer = writer or openrouter_writer(env["OPENROUTER_API_KEY"], env.get("SIGNALS_WEEKLY_MODEL") or MODEL_DEFAULT)
    day = send_day(env)
    out: dict[str, Any] = {}

    issue_id = next_send_date(now, day)
    have = get_issue(store, issue_id)
    due = force or (is_draft_time(now, day) and (have is None or (have["status"] == "failed" and now - (have["failed_at"] or 0) >= RETRY_S)))
    if due:
        try:
            prs = prs_since(now - 7 * 86400, env.get("GITHUB_TOKEN", ""))
            draft, why = writer(prs, env.get("SIGNALS_WEEKLY_NOTES", "") if notes is None else notes)
        except Exception as e:  # the next hour tries again; David hears once
            reason = f"{type(e).__name__}: {e}"[:300]
            print(f"weekly: no draft for {issue_id}: {reason}", flush=True)
            with _db(store) as con:
                con.execute("INSERT INTO issues (id, status, created_at, failed_at, fail_reason) VALUES (?, 'failed', ?, ?, ?)"
                            " ON CONFLICT (id) DO UPDATE SET failed_at = excluded.failed_at, fail_reason = excluded.fail_reason"
                            " WHERE issues.status = 'failed'", (issue_id, now, now, reason))  # fmt: skip
            out["draft"] = f"failed: {reason}"
        else:
            kept = save_issue(store, issue_id, draft, why, prs, now)
            out["draft"] = ("drafted" if draft else f"skipped: {why}") if kept else "already approved, kept"

    with _db(store) as con:
        fresh = [r[0] for r in con.execute("SELECT id FROM issues WHERE previewed_at IS NULL AND status IN ('drafted', 'skipped') ORDER BY id")]
        failed = con.execute("SELECT id, fail_reason FROM issues WHERE status = 'failed' AND fail_told_at IS NULL").fetchall()
        approved = [r[0] for r in con.execute("SELECT id FROM issues WHERE status = 'approved' ORDER BY id")]
    people: list[dict[str, Any]] | None = None

    def everyone() -> list[dict[str, Any]]:
        nonlocal people
        if people is None:
            people = readers(store, users(secret), env)
        return people

    for iid in fresh:
        issue = get_issue(store, iid)
        try:
            ok = bool(issue) and preview(store, issue, len(everyone()) if issue["draft"] else 0, send, env, site)
        except (OSError, ValueError) as e:
            print(f"weekly: no preview yet: {type(e).__name__}", flush=True)
            ok = False
        if ok:
            with _db(store) as con:
                con.execute("UPDATE issues SET previewed_at = ? WHERE id = ?", (now, iid))
        out[f"preview {iid}"] = "sent" if ok else "failed, tried again next minute"
    for iid, reason in failed:
        text = (f"The draft of Signals' weekly update for {long_date(iid)} failed, so there's nothing to approve yet.\n\n"
                f"Why: {reason}\n\nIt's tried again each hour today. Nothing went out to anyone.")  # fmt: skip
        if send(_plain(f"Signals weekly draft failed ({long_date(iid)})", text, env), f"signals-weekly-failed-{iid}") is True:
            with _db(store) as con:
                con.execute("UPDATE issues SET fail_told_at = ? WHERE id = ?", (now, iid))
    for iid in approved:
        issue = get_issue(store, iid)
        if issue and too_late(issue, now):
            continue
        try:
            out[f"send {iid}"] = schedule(store, iid, everyone(), send, now, env, site)
        except (OSError, ValueError) as e:
            print(f"weekly: no readers from Clerk this time: {type(e).__name__}", flush=True)
    return out


# ---- the owner's pages (/api/weekly/approve, /api/weekly/unsubscribe) ----


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>{esc(title)} · Signals</title>
<style>body{{margin:0;background:#fff;color:#141519;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
main{{max-width:520px;margin:12vh auto;padding:0 16px}}h1{{font-size:22px;line-height:1.3;margin:0 0 12px}}
button{{font:600 15px/1 inherit;padding:11px 18px;border:0;border-radius:6px;background:#141519;color:#fff;cursor:pointer;margin-top:8px}}
a{{color:#141519}}</style></head>
<body><main><h1>{esc(title)}</h1>{body}<p style="margin-top:28px"><a href="{SITE}">usesignals.app</a></p></main></body></html>"""


def button(label: str, action: str) -> str:
    return f'<form method="post" action="{esc(action)}"><button type="submit">{esc(label)}</button></form>'


def _keychain(name: str) -> str:
    import subprocess

    return subprocess.run(["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", name, "-w"],
                          capture_output=True, text=True).stdout.strip()  # fmt: skip


if __name__ == "__main__":
    # Try the writer on this week's pull requests, saving nothing:
    #   python -m signals.weekly [--since YYYY-MM-DD] [--note "…"] [--html out.html] [--preview-to you@x.com]
    # OPENROUTER_API_KEY (else the Keychain's openrouter-api-key); --preview-to also needs RESEND_API_KEY (else resend_api_key).
    import sys

    args = sys.argv[1:]

    def opt(name: str) -> str | None:
        return args[args.index(name) + 1] if name in args else None

    now = time.time()
    since = datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp() if (s := opt("--since")) else now - 7 * 86400
    prs = merged_since(since, os.environ.get("GITHUB_TOKEN", ""))
    print(f"{len(prs)} pull requests merged since {datetime.fromtimestamp(since, UTC):%Y-%m-%d}", flush=True)
    key = os.environ.get("OPENROUTER_API_KEY") or _keychain("openrouter-api-key")
    draft, why = openrouter_writer(key, os.environ.get("SIGNALS_WEEKLY_MODEL") or MODEL_DEFAULT)(prs, opt("--note") or "")
    if not draft:
        print(f"Nothing to send: {why}")
        sys.exit(0)
    env = {"SIGNALS_WEEKLY_SECRET": "dry-run", **os.environ}
    send_date = next_send_date(now, send_day(env))
    r = render(draft, unsubscribe=f"{SITE}/api/weekly/unsubscribe?u=preview",
               preview={"approve": f"{SITE}/api/weekly/approve?issue=dry-run", "recipients": 0, "send_date": send_date})  # fmt: skip
    print(r["text"])
    if out_file := opt("--html"):
        Path(out_file).write_text(r["html"])
        print(f"\nHTML: {out_file}")
    if to := opt("--preview-to"):
        rkey = os.environ.get("RESEND_API_KEY") or _keychain("resend_api_key")
        mail = {"from": _from(env), "to": [to], "subject": f"[Preview, dry run] {r['subject']}", "html": r["html"], "text": r["text"]}
        print("preview sent" if welcome.resend_send(rkey)(mail, f"signals-weekly-dry-{now}") is True else "preview NOT sent")
