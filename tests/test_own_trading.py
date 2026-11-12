"""The owner's own one-tap copy on Kalshi and Polymarket US (signals/own_trading.py): the amount, a limit order
after a miss, /copy and /orders. No real order is sent and no exchange is read: own_trading.place, place_limit,
check and cheapest are replaced."""

from __future__ import annotations

import sqlite3
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
FILLED = {"ok": True, "status": "filled", "order_id": "o1", "shares": 57.0, "spent": 24.51, "avg": 0.43}
MISS = {"ok": False, "code": "not_filled"}


class Now:
    def __init__(self, target: Any, args: tuple[Any, ...] = (), **kw: Any) -> None:
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


class Exchange:
    """What stands in for both exchanges: ``answers`` are what each IOC buy gets, in turn (the last one repeats);
    a limit order rests until ``ends`` says how it ended."""

    def __init__(self) -> None:
        self.answers: list[dict[str, Any]] = [dict(FILLED)]
        self.orders: list[dict[str, Any]] = []
        self.limits: list[dict[str, Any]] = []
        self.cancels: list[str] = []
        self.ask: float | None = 0.48
        self.ends: dict[str, Any] | None = None  # how the resting order ends, once it has
        self.cancel_ok = True

    def place(self, order: dict[str, Any], store_dir: Any) -> dict[str, Any]:
        self.orders.append(order)
        return dict(self.answers.pop(0) if len(self.answers) > 1 else self.answers[0])

    def place_limit(self, order: dict[str, Any], store_dir: Any, now: float | None = None) -> dict[str, Any]:
        self.limits.append(order)
        return {"ok": True, "sdk_id": f"L{len(self.limits)}", "expires_at": engine.time.time() + order["minutes"] * 60,
                "over": False, "status": "open", "order_id": "v1", "shares": 0.0, "spent": 0.0, "avg": order["max_price"]}  # fmt: skip

    def check(self, order: dict[str, Any], store_dir: Any, *, cancel: bool = False) -> dict[str, Any] | None:
        if cancel:
            if not self.cancel_ok:
                return None
            self.cancels.append(order["order_id"])
            return {"over": True, "status": "canceled", "order_id": "v1", "shares": 0.0, "spent": 0.0, "avg": 0.45} | (self.ends or {})
        return {"over": False, "status": "open", "order_id": "v1", "shares": 0.0, "spent": 0.0, "avg": 0.45} | (self.ends or {})

    def cheapest(self, order: dict[str, Any], store_dir: Any) -> float | None:
        return self.ask


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


@pytest.fixture
def ex(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> Exchange:
    x = Exchange()
    for name in ("place", "place_limit", "check", "cheapest"):
        monkeypatch.setattr(own_trading, name, getattr(x, name))
    user(OWNER)
    return x


def alert(uid: str = OWNER) -> dict[str, Any]:
    assert engine._deliver(uid, "555", new_buy(SAM, datetime.now(UTC), now=0.42), "Politics") == 1
    return engine.tg.sent[-1]


def keys(markup: dict[str, Any]) -> dict[str, str]:
    return {b["text"]: b.get("callback_data") or b.get("url", "") for row in markup["inline_keyboard"] for b in row}


def buttons(msg: dict[str, Any]) -> dict[str, str]:
    return keys(msg["reply_markup"])


def tap(data: str, mid: int = 1, chat: str = "555") -> None:
    engine._on_update({"callback_query": {"id": "q", "data": data, "message": {"chat": {"id": chat}, "message_id": mid}}})


def say(text: str) -> None:
    engine._on_update({"message": {"chat": {"id": "555"}, "text": text}})


def last() -> dict[str, Any]:
    """The last message the bot changed in place."""
    return next(e for e in reversed(engine.tg.edits) if "text" in e)


def under_alert(mid: int = 1) -> dict[str, str]:
    """The buttons under the alert as they were last changed."""
    return keys(next(e for e in reversed(engine.tg.edits) if "text" not in e and e["message_id"] == mid)["reply_markup"])


def setting(**changed: Any) -> None:
    with engine._db() as con:
        own_trading.save(con, OWNER, **changed)


def left() -> float:
    with engine._db() as con:
        return own_trading.left_today(con, OWNER)


def test_the_owner_gets_a_copy_button_for_each_matched_us_venue_and_no_one_else_does(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    b = buttons(alert())
    assert b["Copy $25 on Polymarket US"].startswith("cv:") and b["Copy $25 on Kalshi"].endswith(":k")
    assert b["Other amount"].startswith("ca:")
    monkeypatch.setattr(own_trading, "OWN_UID", "user_someone_else")
    assert not any("on Kalshi" in t or t == "Other amount" for t in buttons(alert()))
    monkeypatch.setattr(own_trading, "OWN_UID", OWNER)
    monkeypatch.delenv("SIGNALS_OWN_KALSHI_PRIVATE_KEY")  # no Kalshi key: only Polymarket US
    b = buttons(alert())
    assert "Copy $25 on Polymarket US" in b and "Copy $25 on Kalshi" not in b
    monkeypatch.setattr(engine, "us_of", lambda *a, **k: {"found": False})  # no verified match: no button
    assert not any(t.startswith("Copy $25 on") or t == "Other amount" for t in buttons(alert()))


def test_a_tap_says_buying_at_once_then_what_was_bought_once(ex: Exchange) -> None:
    data = buttons(alert())["Copy $25 on Kalshi"]
    tap(data)
    o = ex.orders[-1]
    assert (o["venue"], o["market"], o["side"], o["max_price"], o["size"]) == ("kalshi", "KX-RAIN", "yes", 0.45, 55)
    assert engine.tg.sent[-1]["text"] == "Buying $25 of <b>Yes</b> on Kalshi at 45¢ or less. One second…"
    assert engine.tg.sent[-1]["reply_to_message_id"] == 1
    said = last()
    assert said["message_id"] == 2  # the same message changes
    assert said["text"] == ("<b>Bought.</b> $24.51 of Yes at 43¢ on Kalshi (57 contracts).\n"
                            "Sam paid 42¢. $225.49 left of today's $250.")  # fmt: skip
    assert keys(said["reply_markup"]) == {"View position on Kalshi ↗": "https://kalshi.com/m"}
    b = under_alert()
    assert b["Copied · $24.51 at 43¢"] == "noop" and "Other amount" not in b and "Useful" in b
    assert not any(t.startswith("Copy $") for t in b)
    tap(data)
    tap(data.replace(":k", ":u"))  # the other venue, same alert: still once
    assert len(ex.orders) == 1 and engine.tg.sent[-1]["text"] == "Already copied."


def test_a_tap_that_may_have_gone_through_says_so_and_never_sends_again(ex: Exchange) -> None:
    ex.answers = [{"ok": False, "code": "outcome_unknown"}]
    data = buttons(alert())["Copy $25 on Polymarket US"]
    tap(data)
    assert last()["text"].startswith("Not sure the order went through")
    tap(data)
    assert len(ex.orders) == 1 and left() == 225.0  # counted in the day, as it may have bought


def test_the_daily_limit_stops_copies(ex: Exchange, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(own_trading, "OWN_DAILY_USD", 50.0)
    for _ in range(3):
        msg = alert()
        tap(buttons(msg)["Copy $25 on Kalshi"])
    assert len(ex.orders) == 2 and "today's copy limit of $50" in engine.tg.sent[-1]["text"]


def test_a_tap_from_another_chat_buys_nothing(ex: Exchange) -> None:
    user("user_2", chat="777")
    b = buttons(alert())
    for data in (b["Copy $25 on Kalshi"], b["Other amount"], "cl:x", "cb:x:48", "cx:x", "os:a"):
        tap(data, chat="777")
        assert engine.tg.sent[-1]["text"] == "Copying isn't on for your account."
    assert ex.orders == [] and ex.limits == []


# ---- when no one is selling at the top price ----


def test_by_default_a_miss_asks_and_a_tap_leaves_the_limit_order(ex: Exchange) -> None:
    ex.answers = [dict(MISS)]
    msg = alert()
    aid = buttons(msg)["Other amount"][3:]
    tap(buttons(msg)["Copy $25 on Kalshi"])
    said = last()
    assert said["text"] == "<b>Not bought.</b> The cheapest seller on Kalshi is at 48¢, above your 45¢ top price. Nothing was spent."
    assert keys(said["reply_markup"]) == {"Leave a limit order at 45¢ for 30 min": f"cl:{aid}", "Buy now at 48¢": f"cb:{aid}:48",
                                          "Skip": f"ck:{aid}", "Always leave a limit order": f"cw:{aid}"}  # fmt: skip
    assert ex.limits == [] and left() == 250.0  # nothing rests without a tap, nothing counted
    tap(f"cl:{aid}", mid=2)
    o = ex.limits[-1]
    assert (o["venue"], o["market"], o["side"], o["max_price"], o["size"], o["minutes"]) == ("kalshi", "KX-RAIN", "yes", 0.45, 55, 30.0)
    said = last()
    assert said["message_id"] == 2
    assert said["text"] == ("<b>Limit order left</b> on Kalshi: <b>55 contracts of Yes at 45¢</b>, waiting for 30 min.\n"
                            "It buys only if a seller comes down to 45¢. You'll hear here either way.")  # fmt: skip
    assert keys(said["reply_markup"]) == {"Cancel order": f"cx:{aid}", "Buy now at 48¢": f"cb:{aid}:48",
                                          "View order on Kalshi ↗": "https://kalshi.com/m"}  # fmt: skip
    assert left() == 225.0  # counted while it rests
    tap(f"cl:{aid}", mid=2)
    assert len(ex.limits) == 1 and engine.tg.sent[-1]["text"] == "Your limit order is already there."
    assert engine.own_pass() == 0  # still open: nothing said
    ex.ends = {"over": True, "status": "filled", "shares": 55.0, "spent": 24.94, "avg": 0.45}
    before = len(engine.tg.sent)
    assert engine.own_pass() == 1 and engine.own_pass() == 0  # said once
    assert len(engine.tg.sent) == before + 1  # a new message, so the phone buzzes
    assert engine.tg.sent[-1]["text"] == ("<b>Limit order filled.</b> Bought $24.94 of Yes at 45¢ on Kalshi (55 contracts).\n"
                                          "Sam paid 42¢. $225.06 left of today's $250.")  # fmt: skip
    assert buttons(engine.tg.sent[-1]) == {"View position on Kalshi ↗": "https://kalshi.com/m"}
    assert under_alert()["Copied · $24.94 at 45¢"] == "noop"


def test_with_the_setting_a_miss_leaves_the_limit_order_itself_and_says_when_it_ends_empty(ex: Exchange) -> None:
    setting(miss="limit", wait=15.0)
    ex.answers = [dict(MISS)]
    tap(buttons(alert())["Copy $25 on Polymarket US"])
    assert len(ex.limits) == 1 and ex.limits[0]["minutes"] == 15.0 and ex.limits[0]["venue"] == "polymarket_us"
    assert last()["text"] == ("<b>Not bought yet.</b> The cheapest seller on Polymarket US is at 48¢, above your 45¢ top price.\n"
                              "Your settings say to leave a limit order, so I did: <b>55 contracts of Yes at 45¢</b>, waiting for 15 min.\n"
                              "It buys only if a seller comes down to 45¢. You'll hear here either way.")  # fmt: skip
    assert "Cancel order" in keys(last()["reply_markup"])
    ex.ends = {"over": True, "status": "expired"}
    assert engine.own_pass() == 1
    assert engine.tg.sent[-1]["text"] == ("<b>Limit order ended.</b> No one sold Yes at 45¢ in 15 min, so nothing was bought."
                                          " Your $25 is back in today's limit.")  # fmt: skip
    assert "reply_markup" not in engine.tg.sent[-1] and left() == 250.0
    assert engine.tg.edits[-1] == {"chat_id": "555", "message_id": 2, "reply_markup": {"inline_keyboard": []}}  # its buttons go


def test_cancel_order_ends_it_and_says_what_it_bought(ex: Exchange) -> None:
    setting(miss="limit")
    ex.answers = [dict(MISS)]
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:k")
    ex.cancel_ok = False
    tap(f"cx:{aid}", mid=2)
    assert engine.tg.sent[-1]["text"] == "Couldn't cancel it on Kalshi just now. Tap Cancel order again."
    ex.cancel_ok, ex.ends = True, {"shares": 21.0, "spent": 9.03, "avg": 0.43}  # part of it had filled
    tap(f"cx:{aid}", mid=2)
    assert ex.cancels == ["L1"]
    assert engine.tg.sent[-1]["text"] == ("<b>Limit order cancelled.</b> Bought $9.03 of Yes at 43¢ on Kalshi (21 of 55 contracts)."
                                          " The other $15.97 is back in today's limit.")  # fmt: skip
    assert left() == 250.0 - 9.03
    tap(f"cx:{aid}", mid=2)
    assert engine.tg.sent[-1]["text"] == "That limit order is already over." and ex.cancels == ["L1"]


def test_an_order_the_exchange_left_open_past_its_time_is_cancelled_here(ex: Exchange) -> None:
    setting(miss="limit")
    ex.answers = [dict(MISS)]
    tap(buttons(alert())["Copy $25 on Kalshi"])
    assert engine.own_pass(now=engine.time.time() + 30 * 60 + engine.OWN_LATE_S + 1) == 1
    assert ex.cancels == ["L1"] and engine.tg.sent[-1]["text"].startswith("<b>Limit order ended.</b> No one sold")


def test_buy_now_buys_from_the_seller_shown_at_most_that_price(ex: Exchange) -> None:
    ex.answers = [dict(MISS), {"ok": True, "status": "filled", "order_id": "o2", "shares": 52.0, "spent": 24.96, "avg": 0.48}]
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:k")
    tap(f"cb:{aid}:55", mid=2)  # not the price the reply showed
    assert engine.tg.sent[-1]["text"] == "That price is out of date." and len(ex.orders) == 1
    tap(f"cb:{aid}:48", mid=2)
    o = ex.orders[-1]
    assert (o["max_price"], o["size"], o["market"]) == (0.48, 52, "KX-RAIN")
    assert last()["text"].startswith("<b>Bought.</b> $24.96 of Yes at 48¢ on Kalshi (52 contracts).\nSam paid 42¢.")
    assert under_alert()["Copied · $24.96 at 48¢"] == "noop"
    tap(f"cb:{aid}:48", mid=2)
    tap(f"cl:{aid}", mid=2)
    assert len(ex.orders) == 2 and ex.limits == [] and engine.tg.sent[-1]["text"] == "This one is over."


def test_buy_now_cancels_the_resting_order_first(ex: Exchange) -> None:
    setting(miss="limit")
    ex.answers = [dict(MISS), dict(FILLED)]
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:k")
    ex.cancel_ok = False
    tap(f"cb:{aid}:48", mid=2)
    assert engine.tg.sent[-1]["text"].startswith("Couldn't cancel your limit order on Kalshi") and len(ex.orders) == 1
    assert engine.own_pass() == 0 and left() == 225.0  # still resting, still counted
    ex.cancel_ok = True
    tap(f"cb:{aid}:48", mid=2)
    assert ex.cancels == ["L1"] and len(ex.orders) == 2 and last()["text"].startswith("<b>Bought.</b>")
    assert engine.own_pass() == 0  # nothing left to read back


def test_buy_now_that_finds_the_seller_gone_asks_again_with_the_price_now(ex: Exchange) -> None:
    ex.answers = [dict(MISS)]
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:k")
    ex.ask = 0.51
    tap(f"cb:{aid}:48", mid=2)
    assert last()["text"] == "<b>Not bought.</b> The cheapest seller on Kalshi is at 51¢, above your 45¢ top price. Nothing was spent."
    assert keys(last()["reply_markup"])["Buy now at 51¢"] == f"cb:{aid}:51" and left() == 250.0
    tap(f"cl:{aid}", mid=2)  # the limit order can still be left, at the top price
    assert ex.limits[-1]["max_price"] == 0.45


def test_skip_as_a_setting_and_as_a_tap(ex: Exchange) -> None:
    ex.answers, ex.ask = [dict(MISS)], None
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:k")
    assert last()["text"] == "<b>Not bought.</b> No one is selling Yes on Kalshi right now. Nothing was spent."
    assert "Buy now" not in " ".join(keys(last()["reply_markup"]))
    tap(f"ck:{aid}", mid=2)
    assert engine.tg.edits[-1] == {"chat_id": "555", "message_id": 2, "reply_markup": {"inline_keyboard": []}}
    tap(f"cl:{aid}", mid=2)
    assert ex.limits == [] and engine.tg.sent[-1]["text"] == "This one is over."
    setting(miss="skip")
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:k")
    assert last()["text"].startswith("<b>Not bought.</b>") and last()["reply_markup"] == {"inline_keyboard": []}
    tap(f"cl:{aid}")
    assert ex.limits == []


def test_always_leave_a_limit_order_saves_the_setting_and_leaves_this_one(ex: Exchange) -> None:
    ex.answers = [dict(MISS)]
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:k")
    tap(f"cw:{aid}", mid=2)
    assert len(ex.limits) == 1
    assert engine.tg.sent[-1]["text"] == "Saved. A copy that doesn't fill now becomes a limit order for 30 min. Change it any time with /copy."
    tap(buttons(alert())["Copy $25 on Kalshi"])
    assert len(ex.limits) == 2  # the next miss leaves one itself


def test_a_limit_order_the_exchange_refuses_says_why_and_frees_the_day(ex: Exchange, monkeypatch: pytest.MonkeyPatch) -> None:
    setting(miss="limit")
    ex.answers = [dict(MISS)]
    monkeypatch.setattr(own_trading, "place_limit", lambda o, d: {"ok": False, "code": "insufficient_balance"})
    tap(buttons(alert())["Copy $25 on Kalshi"])
    assert last()["text"] == "No limit order: your Kalshi balance is under $25." and left() == 250.0


# ---- the amount ----


def test_other_amount_changes_this_one_trade(ex: Exchange) -> None:
    msg = alert()
    aid = buttons(msg)["Other amount"][3:]
    tap(f"ca:{aid}")
    ask = engine.tg.sent[-1]
    assert ask["text"] == "<b>How much for this trade?</b>\nOnly this one. Your usual stays $25. Smallest is $1."
    assert buttons(ask) == {"$5": f"cu:{aid}:5", "$10": f"cu:{aid}:10", "$50": f"cu:{aid}:50", "Type it": f"ct:{aid}"}
    tap(f"cu:{aid}:5", mid=2)
    assert last()["text"] == "This trade: $5. The Copy buttons on the alert now say $5."
    b = under_alert()
    assert b["Copy $5 on Kalshi"] == f"cv:{aid}:k" and b["Copy $5 on Polymarket US"] == f"cv:{aid}:u" and "Other amount" in b
    ex.answers = [{"ok": True, "status": "filled", "order_id": "o1", "shares": 11.0, "spent": 4.73, "avg": 0.43}]
    tap(f"cv:{aid}:u")
    assert (ex.orders[-1]["usd"], ex.orders[-1]["size"]) == (5.0, 11)
    assert last()["text"] == ("<b>Bought.</b> $4.73 of Yes at 43¢ on Polymarket US (11 contracts).\n"
                              "Sam paid 42¢. $245.27 left of today's $250.")  # fmt: skip
    tap(f"cu:{aid}:10", mid=2)
    assert engine.tg.sent[-1]["text"] == "You already tapped Copy on this one."
    assert buttons(alert())["Copy $25 on Kalshi"]  # the next alert is at the usual amount again


def test_a_typed_amount_for_one_trade(ex: Exchange) -> None:
    aid = buttons(alert())["Other amount"][3:]
    tap(f"ct:{aid}")
    for bad in ("lots", "0.50", "900"):
        say(bad)
        assert engine.tg.sent[-1]["text"] == "That's not an amount I can use. Send a number from 1 to 250."
    say("7.50")
    assert "Copy $7.50 on Kalshi" in under_alert()
    assert engine.tg.sent[-1]["text"] == "This trade: $7.50. The Copy buttons on the alert now say $7.50."
    say("12")  # no longer asked: ignored
    assert "Copy $7.50 on Kalshi" in under_alert()
    ex.answers = [dict(MISS)]
    tap(f"cv:{aid}:k")
    tap(f"cl:{aid}", mid=4)
    assert (ex.limits[-1]["usd"], ex.limits[-1]["size"]) == (7.5, 16)  # the limit order follows the amount


def test_copy_shows_the_settings_and_changes_them(ex: Exchange) -> None:
    old = alert()
    say("/copy")
    assert engine.tg.sent[-1]["text"] == ("<b>Your copy settings</b>\nUsed every time you tap Copy under an alert.\n\n"
                                          "Amount: $25 a trade\nTop price: up to 3¢ above the alert's price\n"
                                          "If it doesn't fill: ask me each time\nLimit order waits: 30 min\nMost in a day: $250")  # fmt: skip
    assert buttons(engine.tg.sent[-1]) == {"Amount": "os:a", "If it doesn't fill": "os:m"}
    tap("os:a")
    assert engine.tg.sent[-1]["text"] == "<b>Your usual amount?</b>\nEvery Copy button shows this amount. Now $25."
    tap("oa:5", mid=3)
    assert engine.tg.sent[-1]["text"] == "Saved. Copy buttons on new alerts will say $5. Change it any time with /copy."
    new = alert()
    assert "Copy $5 on Kalshi" in buttons(new) and "Copy $25 on Kalshi" in buttons(old)
    tap(buttons(old)["Copy $25 on Kalshi"])
    assert ex.orders[-1]["usd"] == 25.0  # an alert buys what its button says, whatever the usual amount is now
    tap("oa:t")
    say("12")
    assert "Copy $12 on Kalshi" in buttons(alert())
    tap("os:m")
    assert engine.tg.sent[-1]["text"].startswith("<b>If no one is selling at your top price?</b>\nA limit order waits")
    assert list(buttons(engine.tg.sent[-1])) == ["Leave a limit order", "✓ Ask me each time", "Skip the trade"]
    tap("om:l", mid=9)
    assert engine.tg.sent[-1]["text"] == "<b>How long should it wait?</b>"
    assert list(buttons(engine.tg.sent[-1])) == ["15 min", "✓ 30 min", "1 hour"]
    tap("ow:60", mid=10)
    assert engine.tg.sent[-1]["text"] == "Saved. A copy that doesn't fill now becomes a limit order for 1 hour. Change it any time with /copy."
    tap("ow:45", mid=10)  # not a wait on offer: nothing changes
    tap("om:s", mid=9)
    assert engine.tg.sent[-1]["text"] == "Saved. A copy that doesn't fill is skipped. Change it any time with /copy."
    say("/copy")
    assert "If it doesn't fill: skip the trade\nMost in a day" in engine.tg.sent[-1]["text"]
    assert "Amount: $12 a trade" in engine.tg.sent[-1]["text"]


def test_orders_lists_what_is_waiting(ex: Exchange) -> None:
    say("/orders")
    assert engine.tg.sent[-1]["text"] == "No limit orders waiting."
    setting(miss="limit")
    ex.answers = [dict(MISS)]
    aid = buttons(alert())["Other amount"][3:]
    tap(f"cv:{aid}:u")
    ex.ask = 0.46
    say("/orders")
    assert engine.tg.sent[-2]["text"] == "<b>1 limit order waiting</b>"
    text = engine.tg.sent[-1]["text"]
    assert text.startswith("<b>Yes</b> · ") and "\n55 contracts at 45¢ on Polymarket US · 30 min left\n" in text
    assert text.endswith("Copied from Sam. Cheapest seller now: 46¢.")
    assert buttons(engine.tg.sent[-1]) == {"Cancel order": f"cx:{aid}"}


def test_someone_without_it_is_told_so(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    monkeypatch.setattr(own_trading, "OWN_UID", "user_someone_else")
    for cmd in ("/copy", "/orders"):
        say(cmd)
        assert engine.tg.sent[-1]["text"] == "Copying isn't on for your account."


# ---- the words, and an older store ----


@pytest.mark.parametrize(("answer", "says"), [
    ({"ok": False, "code": "not_filled"}, "Not bought: no one is selling at 45¢ or less on Kalshi right now."),
    ({"ok": False, "code": "insufficient_balance"}, "Not bought: your Kalshi balance is under $25."),
    ({"ok": False, "code": "auth_failed"}, "Not bought: Kalshi didn't accept your API key."),
])  # fmt: skip
def test_what_a_tap_says_when_nothing_was_bought(answer: dict[str, Any], says: str) -> None:
    order = {"name": "Kalshi", "max_price": 0.45, "usd": 25.0}
    assert own_trading.result_text(order, answer).startswith(says)


def test_names_from_the_exchange_are_escaped() -> None:
    order = {"name": "Kalshi", "max_price": 0.45, "usd": 25.0, "label": "A <b> & B", "size": 55, "minutes": 30.0, "alert_id": "a"}
    assert "<b>A &lt;b&gt; &amp; B</b>" in own_trading.buying_text(order)
    assert "A &lt;b&gt; &amp; B at 45¢" in own_trading.resting_text(order, 0.5)


def test_a_store_from_before_offers_kept_their_amount_still_copies_25(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    con = sqlite3.connect(tmp_path / "old.db")
    con.execute("CREATE TABLE own_offers (alert_id TEXT NOT NULL, code TEXT NOT NULL, uid TEXT NOT NULL, market TEXT NOT NULL,"
                " side TEXT NOT NULL, price REAL NOT NULL, at REAL NOT NULL, PRIMARY KEY (alert_id, code))")  # fmt: skip
    con.execute("INSERT INTO own_offers VALUES ('a1', 'k', ?, 'KX-RAIN', 'yes', 0.42, 0)", (OWNER,))
    con.executescript(own_trading.SCHEMA + engine.copying.SCHEMA)
    own_trading.migrate(con)
    own_trading.migrate(con)  # twice is fine
    monkeypatch.setattr(own_trading, "OWN_UID", OWNER)
    monkeypatch.setenv("SIGNALS_OWN_KALSHI_KEY_ID", "kid")
    monkeypatch.setenv("SIGNALS_OWN_KALSHI_PRIVATE_KEY", "pem")
    own_trading.save(con, OWNER, usd=5.0)  # the usual amount changed since: the old alert's button still says $25
    o = own_trading.claim(con, "a1", OWNER, "k")
    assert (o["usd"], o["size"], o["label"]) == (25.0, 55, "it")
