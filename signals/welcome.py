"""New Signals sign-ups: David's plain-text note to each one, an hour after they sign up, and an email to David
about each one (owner, 6 Nov: the same note and sign-up alert Layer has, with Signals' own questions).

Signals keeps no list of accounts (a user is in follows.json only after their first save), so sign-ups come from
Clerk's Backend API: its newest users, read every POLL_S. Each sign-up is handled once, kept in STORE_DIR/welcome.db.
People who signed up before this first ran are never emailed: only sign-ups from then on count.

The note says whether they've followed a trader yet, which is why it waits an hour. It's plain text from David, and
replies go to him. Someone who signed in with Telegram has no email in Clerk, so they get no note; David's alert says so.

  CLERK_SECRET_KEY          reads the sign-ups (Backend API, GET /v1/users); everything here is off without it
  RESEND_API_KEY            send-only Resend key; nothing is sent without it
  SIGNALS_WELCOME_FROM      the note's sender, e.g. "David from Signals <david@uselayer.sh>"; the note is off without it
  SIGNALS_WELCOME_REPLY     where replies to the note go (default david@uselayer.sh)
  SIGNALS_ALERT_FROM        the sign-up alert's sender, e.g. "Signals alerts <alerts@uselayer.sh>"; off without it
  SIGNALS_SIGNUP_ALERT_TO   who gets the sign-up alert (default pemakenemi56@gmail.com)
  SIGNALS_OWNER_EMAILS      sign-ups never emailed or alerted about, comma-separated (default pemakenemi56@gmail.com);
                            SIGNALS_OWNER_USER (a Clerk user id) is skipped too
Nothing here logs an email address or a key.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NOTE_AFTER_S = 3600  # the note waits this long after sign-up, to see whether they've followed someone
NOTE_MAX_AGE_S = 7 * 86400  # a sign-up older than this when the note could first go gets none (e.g. the note was off)
POLL_S = 300  # how often Clerk is asked for new sign-ups
OWNER_DEFAULT = "pemakenemi56@gmail.com"
REPLY_DEFAULT = "david@uselayer.sh"
PT = ZoneInfo("America/Los_Angeles")
SUBJECT = "Quick hello from David"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signups (uid TEXT PRIMARY KEY, created_at REAL NOT NULL, email TEXT, first_name TEXT,
  last_name TEXT, alerted_at REAL, noted_at REAL, note TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


@dataclass
class SignUp:
    uid: str
    created_at: float  # seconds
    email: str | None
    first_name: str | None
    last_name: str | None


# ---- what the emails say ----


def note_text(first_name: str | None, follows: int, telegram: bool, site: str) -> str:
    """David's note (wording approved by the owner, 6 Nov). The line before the walkthrough changes with whether
    they follow a trader yet and whether their Telegram is connected."""
    hi = f"Hi {first_name}," if first_name else "Hi there,"
    if follows == 0:
        line = f"Start by following a trader: {site}"
    elif telegram:
        line = f"You're following {_traders(follows)}, and their trades come to you on Telegram as they happen: {site}"
    else:
        line = f"You're following {_traders(follows)}. Turn on Telegram alerts to get their trades the moment they happen: {site}"
    return "\n".join([
        hi, "",
        "I'm David, I built Signals. Thanks for signing up today.", "",
        "Signals lets you follow the Polymarket traders who are actually good: their real track record, and every "
        "trade they make as they make it.", "",
        "Two quick questions, if you have a minute:",
        "1. Which traders or markets are you hoping to follow?",
        "2. What would make Signals worth checking every day for you?", "",
        line,
        "Happy to do a 5-minute walkthrough too, just reply with a time that works :)", "",
        "David",
    ])  # fmt: skip


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
    return con


def _owner(s: SignUp, owner_user: str, env: dict[str, str]) -> bool:
    owners = {e.strip().lower() for e in env.get("SIGNALS_OWNER_EMAILS", OWNER_DEFAULT).split(",") if e.strip()}
    return s.uid == owner_user or bool(s.email and s.email.lower() in owners)


def check(
    now: float,
    store: Path,
    *,
    users_of: Callable[[str], dict[str, Any]],
    site: str,
    owner_user: str = "",
    env: dict[str, str] | None = None,
    fetch: Callable[[str], list[dict[str, Any]]] = clerk_users,
    send: Send | None = None,
) -> dict[str, Any]:
    """One pass: new sign-ups from Clerk (every POLL_S), David's alert about each, and each note once it's due.
    ``users_of(uid)`` is that account's entry in follows.json ({} when they've saved nothing yet)."""
    env = dict(os.environ) if env is None else env
    secret = env.get("CLERK_SECRET_KEY", "")
    if not secret:
        return {"off": "needs CLERK_SECRET_KEY"}
    key = env.get("RESEND_API_KEY", "")
    send = send or (resend_send(key) if key else None)
    note_from, alert_from = env.get("SIGNALS_WELCOME_FROM", ""), env.get("SIGNALS_ALERT_FROM", "")
    out: dict[str, Any] = {"new": 0, "alerted": 0, "noted": 0, "skipped": 0, "failed": 0}
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

            due = con.execute(
                "SELECT uid, created_at, email, first_name FROM signups WHERE note IS NULL AND created_at <= ?",
                (now - NOTE_AFTER_S,),
            ).fetchall()
            for uid, created, email, first in due:
                if not note_from:
                    break
                if now - created > NOTE_MAX_AGE_S:
                    con.execute("UPDATE signups SET note = 'skipped: too old' WHERE uid = ?", (uid,))
                    out["skipped"] += 1
                    continue
                if not email:
                    con.execute("UPDATE signups SET note = 'skipped: no email' WHERE uid = ?", (uid,))
                    out["skipped"] += 1
                    continue
                u = users_of(uid)
                text = note_text(first, len(u.get("follows") or []), bool(u.get("chat")), site)
                payload = {"from": note_from, "to": [email], "reply_to": env.get("SIGNALS_WELCOME_REPLY", REPLY_DEFAULT),
                           "subject": SUBJECT, "text": text}  # fmt: skip
                r = send(payload, f"signals-note-{uid}")
                if r is False:
                    out["failed"] += 1
                    continue
                note = "sent" if r is True else "skipped: refused by Resend"
                con.execute("UPDATE signups SET note = ?, noted_at = ? WHERE uid = ?", (note, now, uid))
                out["noted" if r is True else "skipped"] += 1
    return out


def _note_status(s: SignUp, note: str | None, note_from: str) -> str:
    if note == "sent":
        return "Note: sent automatically."
    if not note_from:
        return "Note: the automatic note is off (SIGNALS_WELCOME_FROM isn't set)."
    if not s.email:
        return "Note: can't be sent, there's no email (Telegram sign-in)."
    return f"Note: goes out automatically around {pt(s.created_at + NOTE_AFTER_S)}, an hour after sign-up."


def preview(to: str, key: str, *, follows: int = 0, telegram: bool = False, site: str = "https://usesignals.app",
            env: dict[str, str] | None = None) -> dict[str, bool]:
    """One note and one sign-up alert to ``to``, exactly as they'd go for a new user 'Sam Lee' who picked Sports and
    Crypto; nothing recorded. For checking how they land (python -m signals.welcome you@x.com)."""
    env = dict(os.environ) if env is None else env
    send, stamp = resend_send(key), datetime.now().timestamp()
    note_from = env.get("SIGNALS_WELCOME_FROM", "David from Signals <david@uselayer.sh>")
    note = {"from": note_from, "to": [to], "reply_to": env.get("SIGNALS_WELCOME_REPLY", REPLY_DEFAULT),
            "subject": SUBJECT, "text": note_text("Sam", follows, telegram, site)}  # fmt: skip
    s = SignUp("user_preview", stamp - 120, "sam@example.com", "Sam", "Lee")
    subject, text = alert_text(s, {"interests": ["Sports", "Crypto"], "follows": [], "chat": None}, _note_status(s, None, note_from))
    alert = {"from": env.get("SIGNALS_ALERT_FROM", "Signals alerts <alerts@uselayer.sh>"), "to": [to],
             "subject": f"(preview) {subject}", "text": text}  # fmt: skip
    return {"note": send(note, f"signals-note-preview-{stamp}") is True,
            "alert": send(alert, f"signals-alert-preview-{stamp}") is True}  # fmt: skip


if __name__ == "__main__":  # python -m signals.welcome you@x.com  (RESEND_API_KEY, else the Keychain's resend_api_key)
    import subprocess
    import sys

    key = os.environ.get("RESEND_API_KEY") or subprocess.run(
        ["security", "find-generic-password", "-a", os.environ.get("USER", ""), "-s", "resend_api_key", "-w"],
        capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    print(preview(sys.argv[1], key))
