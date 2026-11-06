"""David's note to each new Signals sign-up and his sign-up alert (signals/welcome.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from signals import welcome

T0 = 1_800_000_000.0  # the first run
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
        self.fetches = 0

    def fetch(self, secret: str) -> list[dict[str, Any]]:
        assert secret == "sk_test_x"
        self.fetches += 1
        return list(reversed(self.users))  # Clerk: newest first

    def send(self, payload: dict[str, Any], idem: str) -> bool | str:
        self.sent.append((payload, idem))
        return self.answer

    def run(self, store: Path, now: float, env: dict[str, str] | None = None, owner_user: str = "") -> dict[str, Any]:
        return welcome.check(now, store, users_of=lambda uid: self.follows.get(uid, {}), site=SITE, owner_user=owner_user,
                             env=ENV if env is None else env, fetch=self.fetch, send=self.send)  # fmt: skip

    def notes(self) -> list[dict[str, Any]]:
        return [p for p, _ in self.sent if p["subject"] == welcome.SUBJECT]

    def alerts(self) -> list[dict[str, Any]]:
        return [p for p, _ in self.sent if p["subject"].startswith("[Signals] New sign-up")]


def test_off_without_clerk(tmp_path: Path) -> None:
    f = Fake()
    assert f.run(tmp_path, T0, env={}) == {"off": "needs CLERK_SECRET_KEY"}
    assert f.fetches == 0


def test_only_sign_ups_after_the_first_run(tmp_path: Path) -> None:
    f = Fake()
    f.users = [clerk_user("old", T0 - 3600)]
    f.run(tmp_path, T0)
    f.run(tmp_path, T0 + 2 * 3600 + welcome.POLL_S)
    assert f.sent == []


def test_alert_at_once_note_an_hour_later_each_once(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("u1", T0 + 60)]
    out = f.run(tmp_path, T0 + welcome.POLL_S)
    assert out["new"] == 1 and out["alerted"] == 1 and f.notes() == []
    (alert,) = f.alerts()
    assert alert["to"] == ["pemakenemi56@gmail.com"] and alert["from"] == ENV["SIGNALS_ALERT_FROM"]
    assert alert["subject"] == "[Signals] New sign-up: Sam Lee"
    assert "Email: sam@example.com" in alert["text"] and "Markets picked: not picked yet" in alert["text"]
    assert "Note: goes out automatically around" in alert["text"]

    f.run(tmp_path, T0 + 60 + welcome.NOTE_AFTER_S - 1)  # not yet an hour
    assert f.notes() == []
    f.run(tmp_path, T0 + 60 + welcome.NOTE_AFTER_S)
    (note,) = f.notes()
    assert note["to"] == ["sam@example.com"] and note["reply_to"] == "david@uselayer.sh"
    assert note["text"].startswith("Hi Sam,\n\nI'm David, I built Signals.")
    assert f"Start by following a trader: {SITE}" in note["text"]
    assert note["text"].endswith("just reply with a time that works :)\n\nDavid")

    f.run(tmp_path, T0 + 3 * 3600 + welcome.POLL_S * 2)  # nothing twice
    assert len(f.notes()) == 1 and len(f.alerts()) == 1


def test_note_follows_line() -> None:
    assert "Start by following a trader" in welcome.note_text("Sam", 0, False, SITE)
    one = welcome.note_text("Sam", 1, False, SITE)
    assert "You're following 1 trader. Turn on Telegram alerts" in one
    two = welcome.note_text(None, 2, True, SITE)
    assert two.startswith("Hi there,") and "You're following 2 traders, and their trades come to you on Telegram" in two


def test_note_uses_what_they_did_in_the_hour(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("u1", T0 + 60)]
    f.run(tmp_path, T0 + welcome.POLL_S)
    f.follows["u1"] = {"follows": ["0xa", "0xb"], "chat": None, "interests": ["Sports"]}
    f.run(tmp_path, T0 + 60 + welcome.NOTE_AFTER_S)
    (note,) = f.notes()
    assert "You're following 2 traders. Turn on Telegram alerts" in note["text"]


def test_owner_is_skipped(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("me", T0 + 60, email="PemakEnemi56@gmail.com"), clerk_user("me2", T0 + 61, email="x@y.z")]
    f.run(tmp_path, T0 + welcome.POLL_S, owner_user="me2")
    f.run(tmp_path, T0 + 2 * 3600)
    assert f.sent == []


def test_telegram_sign_in_without_email(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("tg", T0 + 60, email=None, first="Ada")]
    f.run(tmp_path, T0 + welcome.POLL_S)
    (alert,) = f.alerts()
    assert "Email: none (signed in with Telegram)" in alert["text"] and "can't be sent" in alert["text"]
    out = f.run(tmp_path, T0 + 2 * 3600)
    assert f.notes() == [] and out["skipped"] == 1


def test_failed_send_is_tried_again_and_refused_is_dropped(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, T0)
    f.users = [clerk_user("u1", T0 + 60)]
    f.answer = False
    out = f.run(tmp_path, T0 + welcome.POLL_S)
    assert out["failed"] == 1 and out["alerted"] == 0
    f.answer = True
    assert f.run(tmp_path, T0 + welcome.POLL_S + 60)["alerted"] == 1
    f.answer = "dead"
    out = f.run(tmp_path, T0 + 2 * 3600)
    assert out["skipped"] == 1
    f.answer = True
    f.run(tmp_path, T0 + 3 * 3600)
    assert len([p for p, _ in f.sent if p["subject"] == welcome.SUBJECT]) == 1  # the refused note, never again


def test_note_off_still_alerts_and_says_so(tmp_path: Path) -> None:
    f = Fake()
    env = {k: v for k, v in ENV.items() if k != "SIGNALS_WELCOME_FROM"}
    f.run(tmp_path, T0, env=env)
    f.users = [clerk_user("u1", T0 + 60)]
    f.run(tmp_path, T0 + welcome.POLL_S, env=env)
    f.run(tmp_path, T0 + 2 * 3600, env=env)
    assert f.notes() == []
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
    f.users = [clerk_user("u1", T0 + 60)]
    f.run(tmp_path, T0 + welcome.POLL_S, env=env)
    out = f.run(tmp_path, T0 + welcome.NOTE_MAX_AGE_S + 3600)  # the note switched on 8 days later
    assert f.notes() == [] and out["skipped"] == 1
