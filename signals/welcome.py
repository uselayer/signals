"""New Signals sign-ups: David's plain-text notes to each one, chosen by what they've done, and an email to David
about each one (owner, 8 Nov: the same scenarios as Layer's lib/welcome.ts and lib/followups.ts). Following a trader
is Signals' "made a key"; a trade reaching them on Telegram is its "first call".

  thanks     an hour after sign-up if they follow someone, or as soon as they do within their first day
  hello      a day after sign-up if they still follow nobody (each person gets thanks or hello, never both)
  nudge      a day after their first follow: Congratulations (Telegram connected, worded by whether a trade from
             those they follow has reached them) or Anything in the way (not connected). Only when that first follow
             was in the last NUDGE_WITHIN_S, so turning this on never emails people who followed long ago
  ask        a week after sign-up and ASK_AFTER_LAST_S after their last note, only for people who never picked markets
             and still haven't connected Telegram; reply with a number

Then nothing more. Each goes once; a failed send is tried again, one Resend refuses for good is never retried.

Signals keeps no list of accounts (a user is in follows.json only after their first save), so sign-ups come from
Clerk's Backend API: its newest users, read every POLL_S. Each sign-up is handled once, kept in STORE_DIR/welcome.db.
People who signed up before this first ran are never emailed: only sign-ups from then on count.

Someone who signed in with Telegram has no email in Clerk, so they get no notes; David's alert says so. Each note is
plain text plus the same words as unstyled HTML (plain_html), which is what lets Resend count opens.

  CLERK_SECRET_KEY          reads the sign-ups (Backend API, GET /v1/users); everything here is off without it
  RESEND_API_KEY            send-only Resend key; nothing is sent without it
  SIGNALS_WELCOME_FROM      the notes' sender, e.g. "David from Signals <david@uselayer.sh>"; every note is off without it
  SIGNALS_WELCOME_REPLY     where replies to the notes go (default david@uselayer.sh)
  SIGNALS_ALERT_FROM        the sign-up alert's sender, e.g. "Signals alerts <alerts@uselayer.sh>"; off without it
  SIGNALS_SIGNUP_ALERT_TO   who gets the sign-up alert (default pemakenemi56@gmail.com)
  SIGNALS_OWNER_EMAILS      sign-ups never emailed or alerted about, comma-separated (default pemakenemi56@gmail.com);
                            SIGNALS_OWNER_USER (a Clerk user id) is skipped too
Nothing here logs an email address or a key.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NOTE_AFTER_S = 3600  # thanks waits this long after sign-up, so the first note can say what they've done
HELLO_AFTER_S = 86400  # someone still following nobody gets hello this long after sign-up
NOTE_MAX_AGE_S = 7 * 86400  # a sign-up older than this when the note could first go gets none (e.g. the note was off)
NUDGE_AFTER_S = 86400  # the nudge goes this long after their first follow
NUDGE_WITHIN_S = 3 * 86400  # and not at all once that first follow is older than this
ASK_AFTER_S = 7 * 86400  # the ask goes this long after sign-up
ASK_AFTER_LAST_S = 3 * 86400  # and at least this long after their last note
ASK_WITHIN_S = 14 * 86400  # and not at all to a sign-up older than this
POLL_S = 300  # how often Clerk is asked for new sign-ups
OWNER_DEFAULT = "pemakenemi56@gmail.com"
REPLY_DEFAULT = "david@uselayer.sh"
PT = ZoneInfo("America/Los_Angeles")
THANKS_SUBJECT = "Thanks for signing up to Signals"
HELLO_SUBJECT = "Quick hello from David"
CONGRATS_SUBJECT = "Congratulations on your first follow"
IN_THE_WAY_SUBJECT = "Anything in the way?"
ASK_SUBJECT = "Quick question"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signups (uid TEXT PRIMARY KEY, created_at REAL NOT NULL, email TEXT, first_name TEXT,
  last_name TEXT, alerted_at REAL, noted_at REAL, note TEXT, nudged_at REAL, asked_at REAL);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


@dataclass
class SignUp:
    uid: str
    created_at: float  # seconds
    email: str | None
    first_name: str | None
    last_name: str | None


@dataclass
class Activity:
    first_follow: float | None  # when they first followed a trader; None when it wasn't logged under this account
    trade_reached: bool  # a trade from someone they follow has been delivered to their Telegram


# ---- what the emails say ----


def _hi(first_name: str | None) -> str:
    return f"Hi {first_name}," if first_name else "Hi there,"


def thanks_text(first_name: str | None, follows: int, telegram: bool, site: str) -> str:
    """They followed someone in their first day: thanks and where to go, nothing to answer (the owner's wording, 8 Nov)."""
    links = [f"You can see all the Polymarket traders and their latest trades here: {site}"]
    if not telegram:
        links.append("Also, make sure to turn on Telegram alerts to get their trades the moment they happen.")
    return "\n".join([
        _hi(first_name), "",
        f"Thanks for signing up, and for following {_traders(follows)}. I'm David, I built Signals.", "",
        *links, "",
        "If anything doesn't work, reply here. It comes straight to me.", "",
        "David",
    ])  # fmt: skip


def hello_text(first_name: str | None, site: str) -> str:
    """A day on and following nobody: what Signals is, and two questions."""
    return "\n".join([
        _hi(first_name), "",
        "I'm David, I built Signals. Thanks for signing up yesterday.", "",
        "Signals lets you follow the Polymarket traders who are actually good: their real track record, and every "
        "trade they make as they make it.", "",
        "Two quick questions, if you have a minute:",
        "1. What were you hoping to find on Signals?",
        "2. Is anything stopping you from following a trader?", "",
        f"You can start by following a trader: {site}",
        "Happy to do a 5-minute walkthrough too, just reply with a time that works :)", "",
        "David",
    ])  # fmt: skip


def _picked(markets: list[str]) -> str:
    """Sports is / Sports and Crypto are / Sports, Crypto and Politics are"""
    if len(markets) == 1:
        return f"{markets[0]} is"
    return f"{', '.join(markets[:-1])} and {markets[-1]} are"


def congrats_text(first_name: str | None, follows: int, markets: list[str], reached: bool) -> str:
    """A day after their first follow, Telegram connected. ``markets``: what they picked ([] says nothing about it)."""
    trades = "I believe their trades are already reaching you on Telegram." if reached else "their trades will come to you on Telegram the moment they happen."
    line = f"You said {_picked(markets)} what you're here for, and {trades}" if markets else trades[0].upper() + trades[1:]
    return "\n".join([
        _hi(first_name), "",
        f"I see you're following {_traders(follows)}. Congratulations on your first follow.", "",
        line, "",
        "What's the next thing you need from Signals? If something's missing or wrong, tell me and I'll look at it this week.", "",
        "David",
    ])  # fmt: skip


def in_the_way_text(first_name: str | None, follows: int, site: str) -> str:
    """A day after their first follow, Telegram not connected."""
    return "\n".join([
        _hi(first_name), "",
        f"I see you're following {_traders(follows)}, nice start. You haven't turned on Telegram alerts yet. No rush, "
        "and if something got in the way, I'd like to know.", "",
        f"Turn them on here and their trades reach you as they happen: {site}", "",
        "If anything's unclear, reply here. It comes straight to me.", "",
        "David",
    ])  # fmt: skip


def ask_text(first_name: str | None) -> str:
    """A week on, no markets picked and no Telegram."""
    return "\n".join([
        _hi(first_name), "",
        "I noticed you signed up to Signals last week but haven't set up alerts yet. No problem at all.", "",
        "I'm curious what you were hoping to follow, so I can point you to the right traders. Just reply with a number:", "",
        "1. Sports",
        "2. Politics",
        "3. Crypto",
        "4. Just looking", "",
        "David",
    ])  # fmt: skip


def plain_html(text: str) -> str:
    """The same note as unstyled HTML: paragraphs, line breaks, clickable addresses, nothing else. It rides beside the
    plain text and looks the same in Gmail; its only job is to give Resend's open tracking somewhere to go."""

    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def line(raw: str) -> str:
        parts = re.split(r'(https?://[^\s"]+)', raw)
        return "".join(f'<a href="{esc(x)}">{esc(x)}</a>' if i % 2 else esc(x) for i, x in enumerate(parts))

    paragraphs = "\n".join("<p>" + "<br>\n".join(line(x) for x in p.split("\n")) + "</p>" for p in re.split(r"\n\n+", text))
    return f"<!doctype html>\n<html><body>\n{paragraphs}\n</body></html>"


def _traders(n: int) -> str:
    return f"{n} trader{'' if n == 1 else 's'}"


def pt(ts: float) -> str:
    """Nov 6, 1:05 AM PST"""
    d = datetime.fromtimestamp(ts, PT)
    return f"{d:%b} {d.day}, {d.strftime('%I:%M %p').lstrip('0')} {d.tzname()}"


def alert_text(s: SignUp, user: dict[str, Any], note_status: str) -> tuple[str, str]:
    """The sign-up alert to David: who, what they picked and follow so far, and what happens with the note."""
    name = " ".join(p for p in (s.first_name, s.last_name) if p) or None
    who = name or s.email or s.uid
    interests = user.get("interests")
    picked = ("not picked yet" if interests is None else "all markets" if not interests else ", ".join(interests))
    follows = len(user.get("follows") or [])
    lines = [
        f"Name: {name or 'not given'}",
        f"Email: {s.email or 'none (signed in with Telegram)'}",
        f"Signed up: {pt(s.created_at)}",
        f"Markets picked: {picked}",
        f"Following: {_traders(follows) if follows else 'nobody yet'}",
        f"Telegram connected: {'yes' if user.get('chat') else 'no'}",
        "",
        note_status,
    ]  # fmt: skip
    return f"[Signals] New sign-up: {who}", "\n".join(lines)


# ---- Clerk and Resend ----


def clerk_users(secret: str) -> list[dict[str, Any]]:
    """Clerk's newest users (Backend API), newest first. Raises on a failed read; the caller tries again later."""
    req = urllib.request.Request(
        "https://api.clerk.com/v1/users?order_by=-created_at&limit=100",
        headers={"Authorization": f"Bearer {secret}", "User-Agent": "signals"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return data if isinstance(data, list) else list(data.get("data") or [])


def sign_up_of(u: dict[str, Any]) -> SignUp | None:
    uid, created = u.get("id"), u.get("created_at")
    if not isinstance(uid, str) or not isinstance(created, (int, float)):
        return None
    emails = u.get("email_addresses") or []
    primary = next((e for e in emails if e.get("id") == u.get("primary_email_address_id")), emails[0] if emails else None)
    email = (primary or {}).get("email_address") or None
    return SignUp(uid, created / 1000, email, u.get("first_name") or None, u.get("last_name") or None)


Send = Callable[[dict[str, Any], str], "bool | str"]  # (payload, idempotency key) → True, False (try again) or "dead"


def resend_send(key: str) -> Send:
    def send(payload: dict[str, Any], idem: str) -> bool | str:
        req = urllib.request.Request(
            "https://api.resend.com/emails", method="POST", data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "signals",
                     "Idempotency-Key": idem[:256]},
        )  # fmt: skip
        try:
            with urllib.request.urlopen(req, timeout=15):
                return True
        except urllib.error.HTTPError as e:
            dead = 400 <= e.code < 500 and e.code not in (409, 429)  # 409: that key already went, so it's sent
            print(f"welcome: Resend refused an email ({e.code}{', not retried' if dead else ''})", flush=True)
            return True if e.code == 409 else "dead" if dead else False
        except OSError as e:
            print(f"welcome: Resend not reached: {type(e).__name__}", flush=True)
            return False

    return send


# ---- the job ----


def _db(store: Path) -> sqlite3.Connection:
    store.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(store / "welcome.db", timeout=10)
    con.executescript(_SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(signups)")}
    for col in ("nudged_at", "asked_at"):  # a welcome.db from before the follow-up notes
        if col not in have:
            con.execute(f"ALTER TABLE signups ADD COLUMN {col} REAL")
    return con


def _owner(s: SignUp, owner_user: str, env: dict[str, str]) -> bool:
    owners = {e.strip().lower() for e in env.get("SIGNALS_OWNER_EMAILS", OWNER_DEFAULT).split(",") if e.strip()}
    return s.uid == owner_user or bool(s.email and s.email.lower() in owners)


def check(
    now: float,
    store: Path,
    *,
    users_of: Callable[[str], dict[str, Any]],
    activity_of: Callable[[str], Activity],
    site: str,
    owner_user: str = "",
    env: dict[str, str] | None = None,
    fetch: Callable[[str], list[dict[str, Any]]] = clerk_users,
    send: Send | None = None,
) -> dict[str, Any]:
    """One pass: new sign-ups from Clerk (every POLL_S), David's alert about each, and each note once it's due.
    ``users_of(uid)`` is that account's entry in follows.json ({} when they've saved nothing yet); ``activity_of(uid)``
    is when they first followed and whether a trade has reached them."""
    env = dict(os.environ) if env is None else env
    secret = env.get("CLERK_SECRET_KEY", "")
    if not secret:
        return {"off": "needs CLERK_SECRET_KEY"}
    key = env.get("RESEND_API_KEY", "")
    send = send or (resend_send(key) if key else None)
    note_from, alert_from = env.get("SIGNALS_WELCOME_FROM", ""), env.get("SIGNALS_ALERT_FROM", "")
    out: dict[str, Any] = {"new": 0, "alerted": 0, "noted": 0, "nudged": 0, "asked": 0, "skipped": 0, "failed": 0}
    with _db(store) as con:
        row = con.execute("SELECT v FROM meta WHERE k = 'started_at'").fetchone()
        if row is None:  # the first run: only sign-ups from now on
            con.execute("INSERT INTO meta (k, v) VALUES ('started_at', ?)", (str(now),))
            started = now
        else:
            started = float(row[0])
        polled = con.execute("SELECT v FROM meta WHERE k = 'polled_at'").fetchone()
        if polled is None or now - float(polled[0]) >= POLL_S:
            try:
                fresh = [s for u in fetch(secret) if (s := sign_up_of(u)) and s.created_at >= started]
            except (OSError, ValueError) as e:
                print(f"welcome: no sign-ups from Clerk this time: {type(e).__name__}", flush=True)
                fresh = []
            else:
                con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('polled_at', ?)", (str(now),))
            for s in fresh:
                skip = _owner(s, owner_user, env)
                cur = con.execute(
                    "INSERT OR IGNORE INTO signups (uid, created_at, email, first_name, last_name, alerted_at, noted_at,"
                    " note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (s.uid, s.created_at, s.email, s.first_name, s.last_name,
                     now if skip else None, now if skip else None, "skipped: owner" if skip else None),
                )  # fmt: skip
                out["new"] += cur.rowcount

        if send:
            for uid, created, email, first, last, noted in con.execute(
                "SELECT uid, created_at, email, first_name, last_name, note FROM signups WHERE alerted_at IS NULL"
            ).fetchall():
                if not alert_from:
                    break
                s = SignUp(uid, created, email, first, last)
                subject, text = alert_text(s, users_of(uid), _note_status(s, noted, note_from))
                to = env.get("SIGNALS_SIGNUP_ALERT_TO", OWNER_DEFAULT)
                r = send({"from": alert_from, "to": [to], "subject": subject, "text": text}, f"signals-signup-{uid}")
                if r is False:
                    out["failed"] += 1
                    continue
                con.execute("UPDATE signups SET alerted_at = ? WHERE uid = ?", (now, uid))
                out["alerted"] += 1

            if note_from:
                _send_notes(con, now, out, users_of, activity_of, site, env, send, note_from)
    return out


def _send_notes(
    con: sqlite3.Connection,
    now: float,
    out: dict[str, Any],
    users_of: Callable[[str], dict[str, Any]],
    activity_of: Callable[[str], Activity],
    site: str,
    env: dict[str, str],
    send: Send,
    note_from: str,
) -> None:
    """Every note that's due: the first (thanks or hello), then the nudge, then the ask."""

    def go(to: str, subject: str, text: str, idem: str) -> bool | str:
        return send(_note(note_from, env, to, subject, text), idem)

    for uid, created, email, first in con.execute(
        "SELECT uid, created_at, email, first_name FROM signups WHERE note IS NULL AND created_at <= ?", (now - NOTE_AFTER_S,)
    ).fetchall():
        if now - created > NOTE_MAX_AGE_S:
            con.execute("UPDATE signups SET note = 'skipped: too old' WHERE uid = ?", (uid,))
            out["skipped"] += 1
            continue
        if not email:
            con.execute("UPDATE signups SET note = 'skipped: no email' WHERE uid = ?", (uid,))
            out["skipped"] += 1
            continue
        u = users_of(uid)
        follows = len(u.get("follows") or [])
        if not follows and now - created < HELLO_AFTER_S:
            continue  # they may still follow someone, and then it's thanks
        subject, text = (
            (THANKS_SUBJECT, thanks_text(first, follows, bool(u.get("chat")), site)) if follows else (HELLO_SUBJECT, hello_text(first, site))
        )
        r = go(email, subject, text, f"signals-note-{uid}")
        if r is False:
            out["failed"] += 1
            continue
        con.execute("UPDATE signups SET note = ?, noted_at = ? WHERE uid = ?", ("sent" if r is True else "skipped: refused by Resend", now, uid))
        out["noted" if r is True else "skipped"] += 1

    for uid, email, first, noted in con.execute(
        "SELECT uid, email, first_name, noted_at FROM signups WHERE note = 'sent' AND nudged_at IS NULL AND email IS NOT NULL"
    ).fetchall():
        u = users_of(uid)
        follows = len(u.get("follows") or [])
        if not follows or now - noted < NOTE_AFTER_S:  # never two notes at once, e.g. after an outage
            continue
        a = activity_of(uid)
        since = now - (a.first_follow if a.first_follow is not None else noted)  # not logged: counted from the first note
        if not NUDGE_AFTER_S <= since <= NUDGE_WITHIN_S:
            continue
        if u.get("chat"):
            subject, text = CONGRATS_SUBJECT, congrats_text(first, follows, list(u.get("interests") or []), a.trade_reached)
        else:
            subject, text = IN_THE_WAY_SUBJECT, in_the_way_text(first, follows, site)
        r = go(email, subject, text, f"signals-nudge-{uid}")
        if r is False:
            out["failed"] += 1
            continue
        con.execute("UPDATE signups SET nudged_at = ? WHERE uid = ?", (now, uid))
        out["nudged" if r is True else "skipped"] += 1

    for uid, created, email, first, noted, nudged in con.execute(
        "SELECT uid, created_at, email, first_name, noted_at, nudged_at FROM signups"
        " WHERE note = 'sent' AND asked_at IS NULL AND email IS NOT NULL AND created_at <= ? AND created_at >= ?",
        (now - ASK_AFTER_S, now - ASK_WITHIN_S),
    ).fetchall():
        u = users_of(uid)
        if u.get("interests") is not None or u.get("chat") or now - max(noted, nudged or 0) < ASK_AFTER_LAST_S:
            continue
        r = go(email, ASK_SUBJECT, ask_text(first), f"signals-ask-{uid}")
        if r is False:
            out["failed"] += 1
            continue
        con.execute("UPDATE signups SET asked_at = ? WHERE uid = ?", (now, uid))
        out["asked" if r is True else "skipped"] += 1


def _note(note_from: str, env: dict[str, str], to: str, subject: str, text: str) -> dict[str, Any]:
    return {"from": note_from, "to": [to], "reply_to": env.get("SIGNALS_WELCOME_REPLY", REPLY_DEFAULT), "subject": subject,
            "text": text, "html": plain_html(text)}  # fmt: skip


def _note_status(s: SignUp, note: str | None, note_from: str) -> str:
    if note == "sent":
        return "Note: sent automatically."
    if not note_from:
        return "Note: the automatic note is off (SIGNALS_WELCOME_FROM isn't set)."
    if not s.email:
        return "Note: can't be sent, there's no email (Telegram sign-in)."
    return f"Note: goes out automatically around {pt(s.created_at + NOTE_AFTER_S)} if they've followed a trader by then, otherwise a day after sign-up."


def preview(to: str, key: str, *, site: str = "https://usesignals.app", alert: bool = False, env: dict[str, str] | None = None) -> dict[str, bool]:
    """One of each note to ``to``, exactly as they'd go to a new user Sam who follows 3 traders and picked Sports (the
    Congratulations note twice: its two versions), and the sign-up alert only with ``alert``; nothing recorded. Each run
    sends them all again, so run it once (python -m signals.welcome you@x.com [--alert])."""
    env = dict(os.environ) if env is None else env
    send, stamp = resend_send(key), datetime.now().timestamp()
    note_from = env.get("SIGNALS_WELCOME_FROM", "David from Signals <david@uselayer.sh>")
    notes = {
        "thanks": (THANKS_SUBJECT, thanks_text("Sam", 3, False, site)),
        "hello": (HELLO_SUBJECT, hello_text("Sam", site)),
        "congrats, a trade has reached them": (CONGRATS_SUBJECT, congrats_text("Sam", 3, ["Sports"], True)),
        "congrats, no trade yet": (CONGRATS_SUBJECT, congrats_text("Sam", 3, ["Sports"], False)),
        "anything in the way": (IN_THE_WAY_SUBJECT, in_the_way_text("Sam", 3, site)),
        "ask": (ASK_SUBJECT, ask_text("Sam")),
    }
    out = {name: send(_note(note_from, env, to, subject, text), f"signals-preview-{i}-{stamp}") is True
           for i, (name, (subject, text)) in enumerate(notes.items())}  # fmt: skip
    if alert:
        s = SignUp("user_preview", stamp - 120, "sam@example.com", "Sam", "Lee")
        subject, text = alert_text(s, {"interests": ["Sports", "Crypto"], "follows": [], "chat": None}, _note_status(s, None, note_from))
        payload = {"from": env.get("SIGNALS_ALERT_FROM", "Signals alerts <alerts@uselayer.sh>"), "to": [to],
                   "subject": f"(preview) {subject}", "text": text}  # fmt: skip
        out["sign-up alert"] = send(payload, f"signals-alert-preview-{stamp}") is True
    return out


if __name__ == "__main__":  # python -m signals.welcome you@x.com [--alert]  (RESEND_API_KEY, else the Keychain's resend_api_key)
    import subprocess
    import sys

    key = os.environ.get("RESEND_API_KEY") or subprocess.run(
        ["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", "resend_api_key", "-w"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    print(preview(sys.argv[1], key, alert="--alert" in sys.argv[2:]))
