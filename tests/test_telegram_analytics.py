"""Telegram in PostHog, from the engine: connected (from the bot's confirmation), alerts sent and failed, taps,
"Fewer alerts" and the choice made, "Stop alerts", /stop, votes, a chat lost. The account id only, never a chat id;
nothing without a key. And /api/metrics' "fewer" section. No network."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
import test_counting as counting
from fastapi.testclient import TestClient
from test_counting import SAM, buy, metrics, user

from signals import app as engine


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    """The counting tests' engine: a store of its own, a pretend bot, signed in with test keys."""
    return counting.api.__wrapped__(monkeypatch, tmp_path)  # type: ignore[attr-defined,no-any-return]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """What the engine queued for PostHog (the sender thread is never started)."""
    monkeypatch.setattr(engine, "POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(engine, "_ph_state", {"thread": object()})
    engine._ph_queue.clear()
    yield engine._ph_queue
    engine._ph_queue.clear()


def events(q: Any) -> list[tuple[str, str]]:
    return [(e["event"], e["distinct_id"]) for e in q]


def test_connecting_from_the_bot_is_an_event_even_with_the_tab_closed(api: TestClient, sent: Any) -> None:
    user(chat=None)
    engine._codes["c0de"] = ("user_1", time.time())
    engine._on_update({"message": {"chat": {"id": 555}, "text": "/start c0de"}})
    assert events(sent) == [("telegram connected", "user_1")]
    p = sent[0]["properties"]
    assert p["follows"] == 1 and p["account"] == "signed in" and p["source"] == "engine"
    assert "555" not in str(list(sent))  # never the chat


def test_alerts_sent_tapped_voted_and_stopped(api: TestClient, sent: Any) -> None:
    user()
    engine._deliver("user_1", "555", buy(SAM, 5), "Politics")
    aid = engine._alert_of("555", 1)
    api.get(f"/go/{aid}/market", params={"to": "https://polymarket.com/event/t"}, follow_redirects=False)
    engine._on_update({"callback_query": {"id": "q", "data": f"v:{aid}:0", "message": {"chat": {"id": 555}}}})
    engine._on_update({"callback_query": {"id": "q", "data": f"unf:{SAM}", "message": {"chat": {"id": 555}, "message_id": 1}}})
    assert [e for e, _ in events(sent)] == ["telegram alert sent", "telegram alert tapped", "telegram alert voted",
                                            "telegram stop tapped"]  # fmt: skip
    assert {u for _, u in events(sent)} == {"user_1"}  # a tap names no one in alerts.db; PostHog hears the account
    s, t, v, st = (e["properties"] for e in sent)
    assert (s["alert_id"], s["kind"], s["wallet"], s["tries"]) == (aid, "buy", SAM, 1)
    assert (t["target"], t["alert_id"]) == ("market", aid)
    assert v["useful"] is False and st["wallet"] == SAM
    assert "555" not in str(list(sent))


def test_a_failed_alert_says_why(api: TestClient, sent: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    user()

    def refuse(method: str, **params: Any) -> Any:
        raise engine.TelegramError("Telegram: Bad Request: message is too long", code=400)

    monkeypatch.setattr(engine, "tg", refuse)
    engine._deliver("user_1", "555", buy(SAM, 5), "Politics")
    assert [e for e, _ in events(sent)] == ["telegram alert failed"]
    assert "too long" in sent[0]["properties"]["why"]


def test_fewer_alerts_opened_and_the_choice_counted(api: TestClient, sent: Any) -> None:
    user()
    engine._on_update({"callback_query": {"id": "q", "data": f"few:{SAM}", "message": {"chat": {"id": 555}, "message_id": 1}}})
    engine._on_update({"callback_query": {"id": "q", "data": f"am:{SAM}:s", "message": {"chat": {"id": 555}, "message_id": 2}}})
    assert [e for e, _ in events(sent)] == ["telegram fewer alerts opened", "alert choice saved"]
    assert sent[0]["properties"]["mode_before"] == "all"
    assert (sent[1]["properties"]["mode"], sent[1]["properties"]["via"]) == ("summary", "telegram")
    m = metrics(api)["fewer"]
    assert m == {"menu_opened": 1, "accounts": 1, "choices_saved": {"summary": 1}}


def test_stop_in_the_chat_is_counted_before_the_chat_is_let_go(api: TestClient, sent: Any) -> None:
    user()
    engine._on_update({"message": {"chat": {"id": 555}, "text": "/stop"}})
    engine._on_update({"message": {"chat": {"id": 555}, "text": "/stop"}})  # already off: nothing more
    assert events(sent) == [("telegram alerts stopped", "user_1")]
    assert metrics(api)["stops"]["alerts_turned_off_with_stop"] == 1


def test_a_telegram_only_follower_is_their_random_id(api: TestClient, sent: Any) -> None:
    engine._follow_codes["f0110w"] = (SAM, time.time())
    engine._on_update({"message": {"chat": {"id": 777}, "text": "/start f0110w"}})
    names = [e for e, _ in events(sent)]
    assert names == ["telegram connected", "trader followed"]
    uid = sent[0]["distinct_id"]
    assert uid.startswith(engine.TG_ONLY) and sent[0]["properties"]["account"] == "telegram only"
    assert sent[1]["properties"]["via"] == "telegram" and "777" not in str(list(sent))


def test_nothing_is_sent_without_a_key(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "POSTHOG_KEY", "")
    engine._ph_queue.clear()
    user(chat=None)
    engine._codes["c0de"] = ("user_1", time.time())
    engine._on_update({"message": {"chat": {"id": 555}, "text": "/start c0de"}})
    assert not engine._ph_queue
