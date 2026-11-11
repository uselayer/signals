"""The owner's own one-tap copy on Kalshi and Polymarket US (signals/own_trading.py). No real order is sent:
own_trading.place is replaced."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import test_alerts as alerts
from fastapi.testclient import TestClient
from test_alerts import SAM, new_buy, user

from signals import app as engine
from signals import own_trading

OWNER = "user_1"
KALSHI = {"found": True, "url": "https://kalshi.com/m", "market_id": "KX-RAIN", "side": "yes", "differences": []}
PMUS = {"found": True, "url": "https://polymarket.us/event/rain", "market_id": "rain:long", "side": "yes", "differences": []}


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    client = alerts.api.__wrapped__(monkeypatch, tmp_path)  # type: ignore[attr-defined]
    monkeypatch.setattr(own_trading, "OWN_UID", OWNER)
    for k, v in (("SIGNALS_OWN_KALSHI_KEY_ID", "kid"), ("SIGNALS_OWN_KALSHI_PRIVATE_KEY", "pem"),
                 ("SIGNALS_OWN_PMUS_KEY_ID", "uid"), ("SIGNALS_OWN_PMUS_SECRET", "sec")):  # fmt: skip
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(engine, "kalshi_of", lambda *a, **k: dict(KALSHI))
    monkeypatch.setattr(engine, "us_of", lambda *a, **k: dict(PMUS))
    monkeypatch.setattr(engine.threading, "Thread", Now)
    return client  # type: ignore[no-any-return]


class Now:
    def __init__(self, target: Any, args: tuple[Any, ...] = (), **kw: Any) -> None:
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


class Placed:
    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.orders: list[dict[str, Any]] = []
        self.answer = answer or {"ok": True, "status": "filled", "order_id": "o1", "shares": 57.0, "spent": 24.51, "avg": 0.43}

    def __call__(self, order: dict[str, Any], store_dir: Any) -> dict[str, Any]:
        self.orders.append(order)
        return dict(self.answer)


def alert(uid: str = OWNER) -> dict[str, Any]:
    assert engine._deliver(uid, "555", new_buy(SAM, datetime.now(UTC), now=0.42), "Politics") == 1
    return engine.tg.sent[-1]


def buttons(msg: dict[str, Any]) -> dict[str, str]:
    return {b["text"]: b.get("callback_data", "") for row in msg["reply_markup"]["inline_keyboard"] for b in row}


def tap(data: str) -> None:
    engine._on_update({"callback_query": {"id": "q", "data": data, "message": {"chat": {"id": "555"}, "message_id": 1}}})


def test_the_owner_gets_a_copy_button_for_each_matched_us_venue_and_no_one_else_does(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    b = buttons(alert())
    assert b["Copy $25 on Polymarket US"].startswith("cv:") and b["Copy $25 on Kalshi"].endswith(":k")
    monkeypatch.setattr(own_trading, "OWN_UID", "user_someone_else")
    assert not any("on Kalshi" in t for t in buttons(alert()))
    monkeypatch.setattr(own_trading, "OWN_UID", OWNER)
    monkeypatch.delenv("SIGNALS_OWN_KALSHI_PRIVATE_KEY")  # no Kalshi key: only Polymarket US
    b = buttons(alert())
    assert "Copy $25 on Polymarket US" in b and "Copy $25 on Kalshi" not in b
    monkeypatch.setattr(engine, "us_of", lambda *a, **k: {"found": False})  # no verified match: no button
    assert not any(t.startswith("Copy $25 on") for t in buttons(alert()))


def test_a_tap_buys_25_dollars_capped_3_cents_above_once(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    placed = Placed()
    monkeypatch.setattr(own_trading, "place", placed)
    data = buttons(alert())["Copy $25 on Kalshi"]
    tap(data)
    o = placed.orders[-1]
    assert (o["venue"], o["market"], o["side"], o["max_price"], o["size"]) == ("kalshi", "KX-RAIN", "yes", 0.45, 55)
    assert engine.tg.sent[-1]["text"] == "Bought $24.51 at 43¢ on Kalshi (57 contracts)."
    tap(data)
    tap(data.replace(":k", ":u"))  # the other venue, same alert: still once
    assert len(placed.orders) == 1 and engine.tg.sent[-1]["text"] == "Already copied."


def test_a_tap_that_may_have_gone_through_says_so_and_never_sends_again(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    placed = Placed({"ok": False, "code": "outcome_unknown"})
    monkeypatch.setattr(own_trading, "place", placed)
    data = buttons(alert())["Copy $25 on Polymarket US"]
    tap(data)
    assert engine.tg.sent[-1]["text"].startswith("Not sure the order went through")
    tap(data)
    assert len(placed.orders) == 1


def test_the_daily_limit_stops_copies(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    monkeypatch.setattr(own_trading, "OWN_DAILY_USD", 50.0)
    placed = Placed()
    monkeypatch.setattr(own_trading, "place", placed)
    for _ in range(3):
        msg = alert()
        tap(buttons(msg)["Copy $25 on Kalshi"])
    assert len(placed.orders) == 2 and "today's copy limit of $50" in engine.tg.sent[-1]["text"]


def test_a_tap_from_another_chat_buys_nothing(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    user("user_2", chat="777")
    placed = Placed()
    monkeypatch.setattr(own_trading, "place", placed)
    data = buttons(alert())["Copy $25 on Kalshi"]
    engine._on_update({"callback_query": {"id": "q", "data": data, "message": {"chat": {"id": "777"}, "message_id": 1}}})
    assert placed.orders == [] and engine.tg.sent[-1]["text"] == "Copying isn't on for your account."


@pytest.mark.parametrize(("answer", "says"), [
    ({"ok": False, "code": "not_filled"}, "Not bought: no one is selling at 45¢ or less on Kalshi right now."),
    ({"ok": False, "code": "insufficient_balance"}, "Not bought: your Kalshi balance is under $25."),
    ({"ok": False, "code": "auth_failed"}, "Not bought: Kalshi didn't accept your API key."),
])  # fmt: skip
def test_what_a_tap_says_when_nothing_was_bought(answer: dict[str, Any], says: str) -> None:
    order = {"name": "Kalshi", "max_price": 0.45, "usd": 25.0}
    assert own_trading.result_text(order, answer).startswith(says)
