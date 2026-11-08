"""David's notes to new Signals sign-ups and his sign-up alert (signals/welcome.py)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from signals import app as engine
from signals import welcome

T0 = 1_800_000_000.0  # the first run
SIGNED_UP = T0 + 60
DAY = 86400
SITE = "https://usesignals.app"
ENV = {
    "CLERK_SECRET_KEY": "sk_test_x",
    "RESEND_API_KEY": "re_x",
    "SIGNALS_WELCOME_FROM": "David from Signals <david@uselayer.sh>",
    "SIGNALS_ALERT_FROM": "Signals alerts <alerts@uselayer.sh>",
}


def clerk_user(uid: str, at: float, email: str | None = "sam@example.com", first: str | None = "Sam") -> dict[str, Any]:
    emails = [{"id": f"e_{uid}", "email_address": email}] if email else []
    return {"id": uid, "created_at": int(at * 1000), "first_name": first, "last_name": "Lee" if first else None,
            "primary_email_address_id": f"e_{uid}" if email else None, "email_addresses": emails}  # fmt: skip


class Fake:
    def __init__(self) -> None:
        self.users: list[dict[str, Any]] = []
        self.sent: list[tuple[dict[str, Any], str]] = []
        self.answer: bool | str = True
        self.follows: dict[str, dict[str, Any]] = {}
        self.activity: dict[str, welcome.Activity] = {}
        self.fetches = 0

    def fetch(self, secret: str) -> list[dict[str, Any]]:
        assert secret == "sk_test_x"
        self.fetches += 1
        return list(reversed(self.users))  # Clerk: newest first

    def send(self, payload: dict[str, Any], idem: str) -> bool | str:
        self.sent.append((payload, idem))
        return self.answer

    def run(self, store: Path, now: float, env: dict[str, str] | None = None, owner_user: str = "") -> dict[str, Any]:
        return welcome.check(now, store, users_of=lambda uid: self.follows.get(uid, {}),
                             activity_of=lambda uid: self.activity.get(uid, welcome.Activity(None, False)), site=SITE,
                             owner_user=owner_user, env=ENV if env is None else env, fetch=self.fetch, send=self.send)  # fmt: skip

    def subjects(self) -> list[str]:
        return [p["subject"] for p, _ in self.sent if not p["subject"].startswith("[Signals]")]

    def note(self, subject: str) -> dict[str, Any]:
        (found,) = [p for p, _ in self.sent if p["subject"] == subject]
        return found

    def alerts(self) -> list[dict[str, Any]]:
        return [p for p, _ in self.sent if p["subject"].startswith("[Signals] New sign-up")]

    def signed_up(self, store: Path, **user: Any) -> None:
        self.run(store, T0)
        self.users = [clerk_user("u1", SIGNED_UP, **user)]
        self.run(store, T0 + welcome.POLL_S)

    def following(self, n: int = 3, chat: str | None = None, interests: list[str] | None = None, first_follow: float = SIGNED_UP + 600, reached: bool = False) -> None:
        self.follows["u1"] = {"follows": [f"0x{i}" for i in range(n)], "chat": chat}
        if interests is not None:
            self.follows["u1"]["interests"] = interests
        self.activity["u1"] = welcome.Activity(first_follow, reached)


def test_off_without_clerk(tmp_path: Path) -> None:
    f = Fake()
    assert f.run(tmp_path, T0, env={}) == {"off": "needs CLERK_SECRET_KEY"}
    assert f.fetches == 0


def test_only_sign_ups_after_the_first_run(tmp_path: Path) -> None:
    f = Fake()
    f.users = [clerk_user("old", T0 - 3600)]
    f.run(tmp_path, T0)
    f.run(tmp_path, T0 + 2 * DAY + welcome.POLL_S)
    assert f.sent == []


def test_alert_at_once_says_when_the_note_goes(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("u1", SIGNED_UP)]
    out = f.run(tmp_path, T0 + welcome.POLL_S)
    assert out["new"] == 1 and out["alerted"] == 1 and f.subjects() == []
    (alert,) = f.alerts()
    assert alert["to"] == ["pemakenemi56@gmail.com"] and alert["from"] == ENV["SIGNALS_ALERT_FROM"]
    assert alert["subject"] == "[Signals] New sign-up: Sam Lee"
    assert "Email: sam@example.com" in alert["text"] and "Markets picked: not picked yet" in alert["text"]
    assert "Note: goes out automatically around" in alert["text"] and "otherwise a day after sign-up" in alert["text"]


def test_followed_gets_thanks_an_hour_after_sign_up_once(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.following()
    f.run(tmp_path, SIGNED_UP + welcome.NOTE_AFTER_S - 1)
    assert f.subjects() == []
    f.run(tmp_path, SIGNED_UP + welcome.NOTE_AFTER_S)
    note = f.note(welcome.THANKS_SUBJECT)
    assert note["to"] == ["sam@example.com"] and note["reply_to"] == "david@uselayer.sh" and note["from"] == ENV["SIGNALS_WELCOME_FROM"]
    assert note["text"].startswith("Hi Sam,\n\nThanks for signing up, and for following 3 traders. I'm David, I built Signals.")
    assert f"You can see all the Polymarket traders and their latest trades here: {SITE}\nAlso, make sure to turn on Telegram alerts to get their trades the moment they happen." in note["text"]
    assert note["text"].endswith("It comes straight to me.\n\nDavid")
    f.run(tmp_path, SIGNED_UP + welcome.NOTE_AFTER_S + 120)
    assert f.subjects() == [welcome.THANKS_SUBJECT]


def test_thanks_leaves_out_telegram_when_connected_and_one_trader_reads_right() -> None:
    text = welcome.thanks_text(None, 1, True, SITE)
    assert text.startswith("Hi there,") and "following 1 trader." in text and "Telegram" not in text


def test_nobody_followed_gets_hello_a_day_on(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S - 1)
    assert f.subjects() == []
    f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S)
    text = f.note(welcome.HELLO_SUBJECT)["text"]
    assert "Thanks for signing up yesterday." in text and f"You can start by following a trader: {SITE}" in text
    assert text.endswith("just reply with a time that works :)\n\nDavid")


def test_follows_later_in_the_first_day_gets_thanks_then_not_hello(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.run(tmp_path, SIGNED_UP + 5 * 3600)
    assert f.subjects() == []
    f.following(first_follow=SIGNED_UP + 6 * 3600)
    f.run(tmp_path, SIGNED_UP + 6 * 3600 + 60)
    f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S)
    assert f.subjects() == [welcome.THANKS_SUBJECT]


def _thanked(f: Fake, store: Path) -> None:
    f.signed_up(store)
    f.following(chat=f.follows.get("u1", {}).get("chat"))
    f.run(store, SIGNED_UP + welcome.NOTE_AFTER_S)


def test_congratulations_a_day_after_the_first_follow(tmp_path: Path) -> None:
    f = Fake()
    _thanked(f, tmp_path)
    follow = SIGNED_UP + 600
    f.following(chat="42", interests=["Sports"], first_follow=follow, reached=True)
    f.run(tmp_path, follow + welcome.NUDGE_AFTER_S - 1)
    assert f.subjects() == [welcome.THANKS_SUBJECT]
    out = f.run(tmp_path, follow + welcome.NUDGE_AFTER_S)
    assert out["nudged"] == 1
    assert f.note(welcome.CONGRATS_SUBJECT)["text"] == (
        "Hi Sam,\n\nI see you're following 3 traders. Congratulations on your first follow.\n\n"
        "You said Sports is what you're here for, and I believe their trades are already reaching you on Telegram.\n\n"
        "What's the next thing you need from Signals? If something's missing or wrong, tell me and I'll look at it this week.\n\nDavid"
    )
    f.run(tmp_path, follow + welcome.NUDGE_AFTER_S + 3600)  # never twice
    assert f.subjects().count(welcome.CONGRATS_SUBJECT) == 1


def test_congratulations_wording() -> None:
    not_yet = welcome.congrats_text("Sam", 3, ["Sports", "Crypto"], False)
    assert "You said Sports and Crypto are what you're here for, and their trades will come to you on Telegram the moment they happen." in not_yet
    three = welcome.congrats_text("Sam", 3, ["Sports", "Crypto", "Politics"], True)
    assert "You said Sports, Crypto and Politics are what you're here for, and I believe their" in three
    assert "\n\nI believe their trades are already reaching you on Telegram.\n\n" in welcome.congrats_text("Sam", 3, [], True)
    assert "\n\nTheir trades will come to you on Telegram the moment they happen.\n\n" in welcome.congrats_text("Sam", 3, [], False)


def test_anything_in_the_way_without_telegram(tmp_path: Path) -> None:
    f = Fake()
    _thanked(f, tmp_path)
    follow = SIGNED_UP + 600
    f.run(tmp_path, follow + welcome.NUDGE_AFTER_S)
    text = f.note(welcome.IN_THE_WAY_SUBJECT)["text"]
    assert text.startswith("Hi Sam,\n\nI see you're following 3 traders, nice start. You haven't turned on Telegram alerts yet.")
    assert f"Turn them on here and their trades reach you as they happen: {SITE}" in text
    assert welcome.CONGRATS_SUBJECT not in f.subjects()


def test_first_follow_long_ago_gets_no_nudge(tmp_path: Path) -> None:
    f = Fake()
    _thanked(f, tmp_path)
    f.following(first_follow=SIGNED_UP - 10 * DAY)
    f.run(tmp_path, SIGNED_UP + 2 * DAY)
    assert f.subjects() == [welcome.THANKS_SUBJECT]


def test_follow_not_logged_counts_from_the_first_note(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.follows["u1"] = {"follows": ["0xa"], "chat": None}  # followed on Telegram first: logged under the old identity
    noted = SIGNED_UP + welcome.NOTE_AFTER_S
    f.run(tmp_path, noted)
    f.run(tmp_path, noted + welcome.NUDGE_AFTER_S - 1)
    assert welcome.IN_THE_WAY_SUBJECT not in f.subjects()
    f.run(tmp_path, noted + welcome.NUDGE_AFTER_S)
    assert welcome.IN_THE_WAY_SUBJECT in f.subjects()


def test_unfollowed_everyone_gets_no_nudge(tmp_path: Path) -> None:
    f = Fake()
    _thanked(f, tmp_path)
    f.following(n=0)
    f.run(tmp_path, SIGNED_UP + welcome.NUDGE_AFTER_S + 3600)
    assert f.subjects() == [welcome.THANKS_SUBJECT]


def test_hello_then_a_late_follow_still_gets_a_nudge(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S)
    follow = SIGNED_UP + 2 * DAY
    f.following(first_follow=follow)
    f.run(tmp_path, follow + welcome.NUDGE_AFTER_S)
    assert f.subjects() == [welcome.HELLO_SUBJECT, welcome.IN_THE_WAY_SUBJECT]


def test_no_two_notes_at_once_after_an_outage(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.following()
    f.run(tmp_path, SIGNED_UP + 2 * DAY)  # the first time the job has run since sign-up
    assert f.subjects() == [welcome.THANKS_SUBJECT]
    f.run(tmp_path, SIGNED_UP + 2 * DAY + welcome.NOTE_AFTER_S)
    assert f.subjects() == [welcome.THANKS_SUBJECT, welcome.IN_THE_WAY_SUBJECT]


def test_ask_a_week_on_only_without_markets_or_telegram(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S)
    f.run(tmp_path, SIGNED_UP + welcome.ASK_AFTER_S - 1)
    assert f.subjects() == [welcome.HELLO_SUBJECT]
    out = f.run(tmp_path, SIGNED_UP + welcome.ASK_AFTER_S)
    assert out["asked"] == 1
    text = f.note(welcome.ASK_SUBJECT)["text"]
    assert "signed up to Signals last week" in text and text.endswith("1. Sports\n2. Politics\n3. Crypto\n4. Just looking\n\nDavid")
    f.run(tmp_path, SIGNED_UP + welcome.ASK_AFTER_S + DAY)
    assert f.subjects().count(welcome.ASK_SUBJECT) == 1


def test_no_ask_when_they_picked_markets_or_connected_telegram(tmp_path: Path) -> None:
    for picked in ({"interests": ["Sports"]}, {"interests": []}, {"chat": "42"}):
        store = tmp_path / str(hash(str(picked)))
        f = Fake()
        f.signed_up(store)
        f.run(store, SIGNED_UP + welcome.HELLO_AFTER_S)
        f.follows["u1"] = {"follows": [], **picked}
        f.run(store, SIGNED_UP + welcome.ASK_AFTER_S + 3600)
        assert welcome.ASK_SUBJECT not in f.subjects()


def test_ask_waits_three_days_after_the_last_note(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S)
    nudged = SIGNED_UP + 5 * DAY
    f.following(first_follow=nudged - welcome.NUDGE_AFTER_S)
    f.run(tmp_path, nudged)
    assert f.subjects() == [welcome.HELLO_SUBJECT, welcome.IN_THE_WAY_SUBJECT]
    f.run(tmp_path, SIGNED_UP + welcome.ASK_AFTER_S)  # a week on, but only two days after the nudge
    assert welcome.ASK_SUBJECT not in f.subjects()
    f.run(tmp_path, nudged + welcome.ASK_AFTER_LAST_S)
    assert welcome.ASK_SUBJECT in f.subjects()


def test_no_ask_to_an_old_sign_up(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path)
    f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S)
    f.run(tmp_path, SIGNED_UP + welcome.ASK_WITHIN_S + 60)
    assert welcome.ASK_SUBJECT not in f.subjects()


def test_owner_is_skipped_for_every_note(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("me", SIGNED_UP, email="PemakEnemi56@gmail.com"), clerk_user("me2", T0 + 61, email="x@y.z")]
    f.run(tmp_path, T0 + welcome.POLL_S, owner_user="me2")
    f.run(tmp_path, SIGNED_UP + 8 * DAY)
    assert f.sent == []


def test_telegram_sign_in_without_email(tmp_path: Path) -> None:
    f = Fake()
    f.signed_up(tmp_path, email=None, first="Ada")
    (alert,) = f.alerts()
    assert "Email: none (signed in with Telegram)" in alert["text"] and "can't be sent" in alert["text"]
    out = f.run(tmp_path, SIGNED_UP + 2 * 3600)
    assert out["skipped"] == 1
    f.run(tmp_path, SIGNED_UP + 8 * DAY)
    assert f.subjects() == []


def test_failed_send_is_tried_again_and_refused_is_dropped(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("u1", SIGNED_UP)]
    f.answer = False
    out = f.run(tmp_path, T0 + welcome.POLL_S)
    assert out["failed"] == 1 and out["alerted"] == 0
    f.answer = True
    assert f.run(tmp_path, T0 + welcome.POLL_S + 60)["alerted"] == 1
    f.answer = "dead"
    assert f.run(tmp_path, SIGNED_UP + welcome.HELLO_AFTER_S)["skipped"] == 1
    f.answer = True
    f.run(tmp_path, SIGNED_UP + 8 * DAY)
    assert f.subjects() == [welcome.HELLO_SUBJECT]  # the refused note, never again, and nothing after it


def test_failed_nudge_is_tried_again_and_refused_is_dropped(tmp_path: Path) -> None:
    f = Fake()
    _thanked(f, tmp_path)
    follow = SIGNED_UP + 600
    f.answer = False
    assert f.run(tmp_path, follow + welcome.NUDGE_AFTER_S)["failed"] == 1
    f.answer = "dead"
    assert f.run(tmp_path, follow + welcome.NUDGE_AFTER_S + 3600)["skipped"] == 1
    f.answer = True
    before = len(f.subjects())
    f.run(tmp_path, follow + welcome.NUDGE_AFTER_S + 7200)
    assert len(f.subjects()) == before


def test_note_off_still_alerts_and_says_so(tmp_path: Path) -> None:
    f = Fake()
    env = {k: v for k, v in ENV.items() if k != "SIGNALS_WELCOME_FROM"}
    f.run(tmp_path, T0, env=env)
    f.users = [clerk_user("u1", SIGNED_UP)]
    f.run(tmp_path, T0 + welcome.POLL_S, env=env)
    f.run(tmp_path, SIGNED_UP + 2 * DAY, env=env)
    assert f.subjects() == []
    (alert,) = f.alerts()
    assert "the automatic note is off" in alert["text"]


def test_clerk_asked_every_poll_only(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.run(tmp_path, T0 + 60)
    f.run(tmp_path, T0 + welcome.POLL_S)
    assert f.fetches == 2


def test_too_old_when_the_note_is_turned_on(tmp_path: Path) -> None:
    f = Fake()
    env = {k: v for k, v in ENV.items() if k != "SIGNALS_WELCOME_FROM"}
    f.run(tmp_path, T0, env=env)
    f.users = [clerk_user("u1", SIGNED_UP)]
    f.run(tmp_path, T0 + welcome.POLL_S, env=env)
    out = f.run(tmp_path, T0 + welcome.NOTE_MAX_AGE_S + 3600)  # the note switched on 8 days later
    assert f.subjects() == [] and out["skipped"] == 1


def test_a_welcome_db_from_before_the_follow_ups_keeps_working(tmp_path: Path) -> None:
    con = sqlite3.connect(tmp_path / "welcome.db")
    con.executescript("""
      CREATE TABLE signups (uid TEXT PRIMARY KEY, created_at REAL NOT NULL, email TEXT, first_name TEXT, last_name TEXT,
        alerted_at REAL, noted_at REAL, note TEXT);
      CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
    """)
    con.execute("INSERT INTO meta VALUES ('started_at', ?)", (str(T0 - DAY),))
    con.execute("INSERT INTO signups VALUES ('u1', ?, 'sam@example.com', 'Sam', 'Lee', ?, ?, 'sent')", (SIGNED_UP, SIGNED_UP, SIGNED_UP + 3600))
    con.commit()
    con.close()
    f = Fake()
    f.following()
    f.run(tmp_path, SIGNED_UP + 600 + welcome.NUDGE_AFTER_S)
    assert f.subjects() == [welcome.IN_THE_WAY_SUBJECT]  # someone who got the old note carries on from it


def test_activity_reads_the_first_follow_and_only_trades_from_people_they_follow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(engine, "STORE_DIR", tmp_path)

    def alert(aid: str, kind: str, state: str | None) -> None:
        with engine._db() as con:
            con.execute("INSERT INTO alerts (id, uid, chat, kind, sent_at, day, state) VALUES (?, 'u1', '42', ?, 1.0, 'd', ?)", (aid, kind, state))

    assert engine._welcome_activity("u1") == welcome.Activity(None, False)
    with engine._db() as con:
        con.execute("INSERT INTO events VALUES (200.0, 'follow', 'u1', NULL, NULL, '0xb')")
        con.execute("INSERT INTO events VALUES (100.0, 'follow', 'u1', NULL, NULL, '0xa')")
        con.execute("INSERT INTO events VALUES (50.0, 'follow', 'other', NULL, NULL, '0xa')")
        con.execute("INSERT INTO events VALUES (10.0, 'unfollow', 'u1', NULL, NULL, '0xa')")
    alert("a", "whale", "sent")  # a big trade, from someone they don't follow
    alert("b", "cap", "sent")  # the daily-limit message
    alert("c", "buy", "failed")  # never reached them
    alert("d", "sell", "queued")  # not yet
    assert engine._welcome_activity("u1") == welcome.Activity(100.0, False)
    alert("e", "buy", "sent")
    assert engine._welcome_activity("u1") == welcome.Activity(100.0, True)


def test_every_note_has_the_same_words_as_html() -> None:
    text = welcome.in_the_way_text("Sam & Co", 3, SITE)
    html = welcome.plain_html(text)
    assert html.startswith("<!doctype html>") and "<p>Hi Sam &amp; Co,</p>" in html
    assert f'<a href="{SITE}">{SITE}</a>' in html and "<style" not in html and "<img" not in html
    assert welcome.plain_html("one\ntwo\n\nthree").count("<p>") == 2 and "one<br>\ntwo" in welcome.plain_html("one\ntwo")
