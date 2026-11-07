"""The owner's alerts: a Telegram message to the owner when the disk fills up, pages answer 500 or trader scoring keeps
failing; told once, again every 6 hours while it lasts, and "fixed" when it's gone (no network: Telegram is a stand-in)."""

from __future__ import annotations

import json
from collections import namedtuple
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from signals import app as engine
from signals import owner_alerts
from signals.owner_alerts import REMIND_S, Errors, ServerErrors, Watch, disk_problem, errors_problem, scoring_problem

NOW = 1_793_700_000.0


class Outbox:
    def __init__(self, ok: bool = True) -> None:
        self.sent: list[str] = []
        self.ok = ok

    def __call__(self, text: str) -> bool:
        if self.ok:
            self.sent.append(text)
        return self.ok


def test_a_problem_is_told_once_then_every_6_hours_then_fixed() -> None:
    out = Outbox()
    w = Watch(out)
    w.update("disk", "The disk is 92% full.", NOW)
    w.update("disk", "The disk is 93% full.", NOW + 60)
    w.update("disk", "The disk is 95% full.", NOW + REMIND_S - 60)
    assert out.sent == ["Signals needs a look: The disk is 92% full."]
    w.update("disk", "The disk is 99% full.", NOW + REMIND_S)
    assert out.sent[-1] == "Signals, still broken (6 hours so far): The disk is 99% full."
    w.update("disk", None, NOW + REMIND_S + 3600)
    assert out.sent[-1] == "Signals, fixed: The disk has room again. It lasted 7 hours."
    assert len(out.sent) == 3 and "disk" not in w.problems


def test_a_message_that_didnt_go_is_tried_the_next_minute() -> None:
    out = Outbox(ok=False)
    w = Watch(out)
    w.update("errors", "2 requests failed.", NOW)
    assert w.problems["errors"].told_at is None
    out.ok = True
    w.update("errors", "3 requests failed.", NOW + 60)
    assert out.sent == ["Signals needs a look: 3 requests failed."]


def test_no_fixed_message_for_a_problem_never_told() -> None:
    out = Outbox(ok=False)
    w = Watch(out)
    w.update("scoring", "Trader scoring has failed.", NOW)
    out.ok = True
    w.update("scoring", None, NOW + 60)
    assert out.sent == []


def test_each_problem_is_its_own() -> None:
    out = Outbox()
    w = Watch(out)
    w.update("disk", "Disk.", NOW)
    w.update("errors", "Errors.", NOW)
    w.update("errors", None, NOW + 600)
    assert out.sent == ["Signals needs a look: Disk.", "Signals needs a look: Errors.",
                        "Signals, fixed: No server errors for 10 minutes. It lasted 10 min."]  # fmt: skip
    assert list(w.problems) == ["disk"]


Usage = namedtuple("Usage", "total used free")


class Vfs:
    def __init__(self, files: int, free: int) -> None:
        self.f_files, self.f_ffree = files, free


def test_disk_problem_on_space_or_file_slots(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    gb = 1_000_000_000
    monkeypatch.setattr(owner_alerts.shutil, "disk_usage", lambda p: Usage(5 * gb, int(4.6 * gb), int(0.4 * gb)))
    monkeypatch.setattr(owner_alerts.os, "statvfs", lambda p: Vfs(1000, 900))
    assert disk_problem(tmp_path) == ("The disk is 92% full (4.6 of 5.0 GB). When it's full, the Traders page stops "
                                      "working. Make the volume bigger on Railway, or clear space.")  # fmt: skip
    monkeypatch.setattr(owner_alerts.shutil, "disk_usage", lambda p: Usage(5 * gb, 2 * gb, 3 * gb))
    assert disk_problem(tmp_path) is None
    monkeypatch.setattr(owner_alerts.os, "statvfs", lambda p: Vfs(1000, 100))
    assert disk_problem(tmp_path).startswith("The disk has used 90% of its file slots.")  # type: ignore[union-attr]


def test_errors_are_counted_over_10_minutes_and_named_by_page() -> None:
    e = Errors()
    e.add("/api/leaderboard", "OperationalError: disk I/O error", NOW - 700)  # too old
    e.add("/api/leaderboard", "OperationalError: disk I/O error", NOW - 300)
    e.add("/api/leaderboard", "OperationalError: disk I/O error", NOW - 200)
    e.add("/api/traders", "OperationalError: database or disk is full", NOW - 100)
    rows = e.recent(NOW)
    assert len(rows) == 3
    assert errors_problem(rows) == ("3 requests failed with a server error in the last 10 minutes (/api/leaderboard ×2, "
                                    "/api/traders). Visitors see \"Couldn't load this\". Latest: OperationalError: "
                                    "database or disk is full")  # fmt: skip
    assert errors_problem([]) is None


def test_scoring_is_told_after_30_minutes_of_failing() -> None:
    err = "OperationalError: database or disk is full"
    assert scoring_problem(err, NOW - 1700, NOW) is None
    assert scoring_problem(None, NOW - 7200, NOW) is None
    assert scoring_problem(err, NOW - 1800, NOW) == (
        "Trader scoring has failed every round for 30 min: OperationalError: database or disk is full. The leaderboard "
        "isn't getting new or updated records.")  # fmt: skip


def test_server_errors_records_500s_and_raised_errors_only() -> None:
    into = Errors()
    app = FastAPI()

    @app.get("/ok")
    def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/broken")
    def broken() -> None:
        raise RuntimeError("disk I/O error")

    @app.get("/refused")
    def refused() -> None:
        raise HTTPException(500, "no")

    @app.get("/missing")
    def missing() -> None:
        raise HTTPException(404, "nope")

    app.add_middleware(ServerErrors, into=into)
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/ok").status_code == 200
    assert c.get("/missing").status_code == 404
    assert c.get("/broken?q=secret").status_code == 500
    assert c.get("/refused").status_code == 500
    rows = into.recent()
    assert [(p, why) for _, p, why in rows] == [("/broken", "RuntimeError: disk I/O error"), ("/refused", "answered 500")]


def test_the_engine_counts_its_own_500s() -> None:
    assert any(m.cls is ServerErrors for m in engine.app.user_middleware)


class Telegram:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, **p: Any) -> dict[str, Any]:
        self.calls.append({"method": method} | p)
        return {}


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> Telegram:
    t = Telegram()
    monkeypatch.setattr(engine, "tg", t)
    monkeypatch.setattr(engine, "TG_TOKEN", "token")
    monkeypatch.setattr(engine, "OWNER_CHAT", "")
    monkeypatch.setattr(engine, "OWNER_USER", "user_owner")
    monkeypatch.setattr(engine, "EVALUATE_ON", True)
    monkeypatch.setattr(engine, "_owner_watch", Watch(engine._owner_send))
    monkeypatch.setattr(owner_alerts, "errors", Errors())
    monkeypatch.setattr(owner_alerts, "disk_problem", lambda folder: None)
    monkeypatch.setitem(engine._evaluate_state, "error", None)
    monkeypatch.setitem(engine._evaluate_state, "error_since", None)
    (engine.STORE_DIR / "follows.json").write_text(json.dumps({"users": {"user_owner": {"follows": [], "chat": 4242}}}))
    return t


def test_owner_check_sends_to_the_chat_on_the_owners_account(owner: Telegram, monkeypatch: pytest.MonkeyPatch) -> None:
    owner_alerts.errors.add("/api/leaderboard", "OperationalError: disk I/O error", NOW - 30)
    engine.owner_check(NOW)
    assert [(c["method"], c["chat_id"]) for c in owner.calls] == [("sendMessage", "4242")]
    assert owner.calls[0]["text"].startswith("Signals needs a look: 1 request failed with a server error")
    engine.owner_check(NOW + 60)  # still the same problem: not told again
    assert len(owner.calls) == 1


def test_owner_check_tells_scoring_failing_for_30_minutes(owner: Telegram, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(engine._evaluate_state, "error", "OperationalError: database or disk is full")
    monkeypatch.setitem(engine._evaluate_state, "error_since", NOW - 1900)
    engine.owner_check(NOW)
    assert "Trader scoring has failed every round for 32 min" in owner.calls[0]["text"]


def test_owner_check_is_off_without_an_owner(owner: Telegram, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "OWNER_USER", "")
    owner_alerts.errors.add("/api/leaderboard", "boom", NOW - 30)
    engine.owner_check(NOW)
    assert owner.calls == []


def test_a_telegram_failure_is_logged_and_tried_again(owner: Telegram, monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    def down(method: str, **p: Any) -> None:
        raise engine.TelegramError("Telegram couldn't be reached (gaierror)")

    monkeypatch.setattr(engine, "tg", down)
    owner_alerts.errors.add("/api/leaderboard", "boom", NOW - 30)
    engine.owner_check(NOW)
    assert "owner alerts: not sent: Telegram couldn't be reached" in capsys.readouterr().out
    monkeypatch.setattr(engine, "tg", owner)
    engine.owner_check(NOW + 60)
    assert len(owner.calls) == 1


def test_the_test_message_is_the_owners_only(owner: Telegram, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "METRICS_KEY", "owner-secret")
    c = TestClient(engine.app)
    assert c.post("/api/owner-alerts/test").status_code == 404
    r = c.post("/api/owner-alerts/test", headers={"authorization": "Bearer owner-secret"})
    assert r.status_code == 200 and r.json() == {"sent": True, "problems_now": {}}
    assert owner.calls[0]["text"].startswith("Signals: your alerts are on.")
    monkeypatch.setattr(engine, "OWNER_USER", "user_nobody")
    r = c.post("/api/owner-alerts/test", headers={"authorization": "Bearer owner-secret"})
    assert r.json()["sent"] is False and "SIGNALS_OWNER_USER" in r.json()["why"]


def test_owner_check_tells_when_telegram_refused_the_sign_in_button(owner: Telegram, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(engine._tg, "login_refused", "Telegram: Bad Request: BOT_DOMAIN_INVALID")
    monkeypatch.setitem(engine._tg, "bot", "UseSignalsBot")
    engine.owner_check(NOW)
    assert len(owner.calls) == 1
    text = owner.calls[0]["text"]
    assert text.startswith("Signals needs a look: Telegram refused an alert for its sign-in button (Telegram: Bad Request: BOT_DOMAIN_INVALID)")
    assert "/setdomain → @UseSignalsBot → usesignals.app" in text and "SIGNALS_TG_LOGIN=0" in text
    engine.owner_check(NOW + 60)  # the same problem: not told again
    assert len(owner.calls) == 1
    monkeypatch.setitem(engine._tg, "login_refused", None)  # after a restart with the domain linked
    engine.owner_check(NOW + 120)
    assert owner.calls[-1]["text"].startswith("Signals, fixed: Alerts carry the sign-in button again.")
