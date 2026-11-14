"""The owner's own one-tap copy on Kalshi and Polymarket US (signals/own_trading.py): one Copy button that buys
on the cheaper exchange, the amount, a limit order after a miss, Copy settings. No real order is sent and no
exchange is read: own_trading.place, place_limit, check, cheapest and balance are replaced."""

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
FILLED = {"ok": True, "status": "filled", "order_id": "o1", "shares": 55.0, "spent": 23.65, "avg": 0.43}
MISS = {"ok": False, "code": "not_filled"}


class Now:
    def __init__(self, target: Any, args: tuple[Any, ...] = (), **kw: Any) -> None:
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


class Exchange:
    """What stands in for both exchanges: ``asks`` and ``cash`` are each one's cheapest seller and balance;
    ``answer`` is what an IOC buy gets; a limit order rests until ``ends`` says how it ended."""

    def __init__(self) -> None:
        self.answer: dict[str, Any] = dict(FILLED)
        self.orders: list[dict[str, Any]] = []
        self.limits: list[dict[str, Any]] = []
        self.cancels: list[str] = []
        self.asks: dict[str, float | None] = {"k": 0.43, "u": 0.44}
        self.cash: dict[str, float | None] = {"k": 100.0, "u": 100.0}
        self.ends: dict[str, Any] | None = None  # how the resting order ends, once it has
        self.cancel_ok = True

    def place(self, order: dict[str, Any], store_dir: Any) -> dict[str, Any]:
        self.orders.append(order)
        return dict(self.answer)

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
        return self.asks[order["code"]]

    def balance(self, code: str, store_dir: Any) -> float | None:
        return self.cash[code]


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
    for name in ("place", "place_limit", "check", "cheapest", "balance"):
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


def new_alert() -> str:
    """An alert sent to the owner; its id."""
    return buttons(alert())["Copy $25"][3:]


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


# ---- the alert ----


def test_the_owner_gets_one_copy_button_and_no_one_else_does(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(OWNER)
    msg = alert()
    rows = [[b["text"] for b in row] for row in msg["reply_markup"]["inline_keyboard"]]
    assert rows == [["Copy $25"], ["Change amount", "Edit rule", "Pause 24 h"], ["Useful", "Not useful"]]  # no row more than before Copy
    assert buttons(msg)["Copy $25"].startswith("cv:") and buttons(msg)["Copy $25"].count(":") == 1
    assert msg["text"].endswith("\n\n" + own_trading.INTRO)
    assert own_trading.INTRO not in alert()["text"]  # said once
    monkeypatch.setattr(own_trading, "OWN_UID", "user_someone_else")
    assert not any(t.startswith("Copy") or t == "Change amount" for t in buttons(alert()))
    monkeypatch.setattr(own_trading, "OWN_UID", OWNER)
    monkeypatch.setattr(engine, "us_of", lambda *a, **k: {"found": False})
    assert "Copy $25" in buttons(alert())  # on Kalshi alone: still the one button
    monkeypatch.setattr(engine, "kalshi_of", lambda *a, **k: {"found": False})  # no verified match: no button
    assert not any(t.startswith("Copy") or t == "Change amount" for t in buttons(alert()))


# ---- a tap ----


def test_a_tap_buys_on_the_cheaper_exchange_and_says_which_once(ex: Exchange) -> None:
    aid = new_alert()
    tap(f"cv:{aid}")
    o = ex.orders[-1]
    assert (o["venue"], o["market"], o["side"], o["max_price"], o["size"]) == ("kalshi", "KX-RAIN", "yes", 0.45, 55)
    assert engine.tg.sent[-1]["text"] == ("Buying $25 of <b>Yes</b> at 45¢ or less, on whichever of Polymarket US and Kalshi"
                                          " is cheaper. One second…")  # fmt: skip
    assert engine.tg.sent[-1]["reply_to_message_id"] == 1
    said = last()
    assert said["message_id"] == 2  # the same message changes
    assert said["text"] == ("<b>Bought on Kalshi.</b> $23.65 of Yes at 43¢ (55 contracts).\n"
                            "Polymarket US was at 44¢. Sam paid 42¢. $226.35 left of today's $250.")  # fmt: skip
    assert keys(said["reply_markup"]) == {"View position ↗": "https://kalshi.com/m", "Copy settings": "os:o"}
    rows = [[b["text"] for b in row] for row in next(
        e for e in reversed(engine.tg.edits) if "text" not in e and e["message_id"] == 1)["reply_markup"]["inline_keyboard"]]  # fmt: skip
    assert rows == [["Copied · $23.65 at 43¢"], ["Edit rule", "Pause 24 h"], ["Useful", "Not useful"]]
    with engine._db() as con:
        assert con.execute("SELECT token FROM copy_orders WHERE alert_id = ?", (aid,)).fetchone()[0] == "kalshi:KX-RAIN:yes"
    tap(f"cv:{aid}")
    assert len(ex.orders) == 1 and engine.tg.sent[-1]["text"] == "Already copied."


def test_the_other_exchange_wins_when_it_is_cheaper(ex: Exchange) -> None:
    ex.asks = {"k": 0.44, "u": 0.42}
    tap(f"cv:{new_alert()}")
    assert (ex.orders[-1]["venue"], ex.orders[-1]["market"]) == ("polymarket_us", "rain:long")
    assert last()["text"].startswith("<b>Bought on Polymarket US.</b>") and "Kalshi was at 44¢." in last()["text"]
    assert keys(last()["reply_markup"])["View position ↗"] == "https://polymarket.us/event/rain"


def test_an_exchange_without_the_money_is_left_out(ex: Exchange) -> None:
    ex.asks, ex.cash = {"k": 0.44, "u": 0.40}, {"k": 57.70, "u": 0.79}
    tap(f"cv:{new_alert()}")
    assert ex.orders[-1]["venue"] == "kalshi"  # dearer, but the only one that can pay
    assert "Polymarket US left out: your balance there is under $25." in last()["text"]
    ex.cash = {"k": 3.0, "u": 0.79}
    tap(f"cv:{new_alert()}")
    assert len(ex.orders) == 1  # nothing sent
    assert last()["text"] == "Not bought: your Polymarket US and Kalshi balances are under $25." and left() == 226.35
    ex.cash = {"k": None, "u": None}  # balances that can't be read don't stop a copy
    tap(f"cv:{new_alert()}")
    assert len(ex.orders) == 2


def test_with_one_exchange_nothing_is_compared(ex: Exchange, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "us_of", lambda *a, **k: {"found": False})
    monkeypatch.setattr(own_trading, "balance", lambda *a: pytest.fail("no need to read a balance"))
    tap(f"cv:{new_alert()}")
    assert engine.tg.sent[-1]["text"] == "Buying $25 of <b>Yes</b> on Kalshi at 45¢ or less. One second…"
    assert last()["text"] == "<b>Bought on Kalshi.</b> $23.65 of Yes at 43¢ (55 contracts).\nSam paid 42¢. $226.35 left of today's $250."


def test_a_button_from_when_each_exchange_had_its_own_still_buys_there(ex: Exchange) -> None:
    aid = new_alert()
    tap(f"cv:{aid}:u")
    assert ex.orders[-1]["venue"] == "polymarket_us" and last()["text"].startswith("<b>Bought on Polymarket US.</b>")
    tap(f"cv:{aid}:k")
    assert len(ex.orders) == 1  # still once an alert


def test_a_tap_that_may_have_gone_through_says_so_and_never_sends_again(ex: Exchange) -> None:
    ex.answer = {"ok": False, "code": "outcome_unknown"}
    aid = new_alert()
    tap(f"cv:{aid}")
    assert last()["text"].startswith("Not sure the order went through: Kalshi didn't answer in time.")
    tap(f"cv:{aid}")
    assert len(ex.orders) == 1 and left() == 225.0  # counted in the day, as it may have bought


def test_the_daily_limit_stops_copies(ex: Exchange, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(own_trading, "OWN_DAILY_USD", 50.0)
    for _ in range(3):
        tap(f"cv:{new_alert()}")
    assert len(ex.orders) == 2 and "today's copy limit of $50" in engine.tg.sent[-1]["text"]


def test_a_tap_from_another_chat_does_nothing(ex: Exchange) -> None:
    user("user_2", chat="777")
    aid = new_alert()
    for data in (f"cv:{aid}", f"ca:{aid}", f"cj:{aid}:5", f"ce:{aid}:5", f"cl:{aid}", f"cx:{aid}", "os:o", "oa:5", "oy:1"):
        tap(data, chat="777")
        assert engine.tg.sent[-1]["text"] == "Copying isn't on for your account."
    assert ex.orders == [] and ex.limits == []
    with engine._db() as con:
        assert own_trading.settings(con, OWNER)["usd"] == 25.0 and own_trading.settings(con, "user_2")["miss"] is None


# ---- when no one is selling at the top price ----


def test_a_miss_offers_one_button_and_a_tap_leaves_the_limit_order(ex: Exchange) -> None:
    ex.answer, ex.asks = dict(MISS), {"k": 0.46, "u": 0.48}
    aid = new_alert()
    tap(f"cv:{aid}")
    said = last()
    assert said["text"] == "<b>Not bought.</b> The cheapest seller is at 46¢, on Kalshi, above your 45¢ top price. Nothing was spent."
    assert keys(said["reply_markup"]) == {"Leave a limit order at 45¢": f"cl:{aid}", "Copy settings": "os:o"}
    assert ex.limits == [] and left() == 250.0  # nothing rests without a tap, nothing counted
    tap(f"cl:{aid}", mid=2)
    o = ex.limits[-1]
    assert (o["venue"], o["market"], o["side"], o["max_price"], o["size"], o["minutes"]) == ("kalshi", "KX-RAIN", "yes", 0.45, 55, 30.0)
    said = last()
    assert said["message_id"] == 2
    assert said["text"] == ("<b>Limit order placed.</b> 55 contracts of Yes at 45¢ on Kalshi, waiting 30 min.\n"
                            "It buys only if a seller comes down to 45¢. I'll message you when it fills or ends.")  # fmt: skip
    assert keys(said["reply_markup"]) == {"Cancel order": f"cx:{aid}"}
    assert engine.tg.sent[-1]["text"] == "<b>Do this every time a copy doesn't fill?</b>\nYou can change it later in Copy settings."
    assert buttons(engine.tg.sent[-1]) == {"Yes, always": "oy:1", "No, ask me": "oy:0"}
    assert left() == 225.0  # counted while it rests
    tap(f"cl:{aid}", mid=2)
    assert len(ex.limits) == 1 and engine.tg.sent[-1]["text"] == "Your limit order is already there."
    assert engine.own_pass() == 0  # still open: nothing said
    ex.ends = {"over": True, "status": "filled", "shares": 55.0, "spent": 24.75, "avg": 0.45}
    before = len(engine.tg.sent)
    assert engine.own_pass() == 1 and engine.own_pass() == 0  # said once
    assert len(engine.tg.sent) == before + 1  # a new message, so the phone buzzes
    assert engine.tg.sent[-1]["text"] == ("<b>Limit order filled.</b> Bought $24.75 of Yes at 45¢ on Kalshi (55 contracts).\n"
                                          "Sam paid 42¢. $225.25 left of today's $250.")  # fmt: skip
    assert buttons(engine.tg.sent[-1]) == {"View position ↗": "https://kalshi.com/m", "Copy settings": "os:o"}
    assert under_alert()["Copied · $24.75 at 45¢"] == "noop"


def test_the_first_limit_order_asks_whether_to_always_and_only_the_first(ex: Exchange) -> None:
    ex.answer, ex.asks = dict(MISS), {"k": 0.46, "u": 0.48}
    aid = new_alert()
    tap(f"cv:{aid}")
    tap(f"cl:{aid}", mid=2)
    tap("oy:0", mid=3)
    assert last()["text"] == "Saved. When a copy doesn't fill, I'll ask before leaving a limit order."
    aid = new_alert()
    tap(f"cv:{aid}")
    assert len(ex.limits) == 1  # still asks
    tap(f"cl:{aid}", mid=5)
    assert len(ex.limits) == 2 and "Do this every time" not in engine.tg.sent[-1]["text"]  # not asked again
    tap("oy:1", mid=3)
    assert last()["text"] == "Saved. A copy that doesn't fill now becomes a limit order for 30 min."
    tap(f"cv:{new_alert()}")
    assert len(ex.limits) == 3  # now left at once
    assert last()["text"] == ("<b>Not bought yet</b>: no one is selling at 45¢ or less. <b>Limit order placed</b>, as you set:"
                              " 55 contracts of Yes at 45¢ on Kalshi, waiting 30 min.\n"
                              "It buys only if a seller comes down to 45¢. I'll message you when it fills or ends.")  # fmt: skip
    assert "Cancel order" in keys(last()["reply_markup"])


def test_a_limit_order_that_ends_empty_gives_the_day_its_dollars_back(ex: Exchange) -> None:
    setting(miss="limit")
    ex.answer, ex.asks = dict(MISS), {"k": 0.48, "u": 0.46}
    tap(f"cv:{new_alert()}")
    assert ex.limits[0]["venue"] == "polymarket_us"  # where the cheaper seller is
    ex.ends = {"over": True, "status": "expired"}
    assert engine.own_pass() == 1
    assert engine.tg.sent[-1]["text"] == ("<b>Limit order ended.</b> No one sold Yes at 45¢ in 30 min, so nothing was bought."
                                          " Your $25 is back in today's limit.")  # fmt: skip
    assert "reply_markup" not in engine.tg.sent[-1] and left() == 250.0
    assert engine.tg.edits[-1] == {"chat_id": "555", "message_id": 2, "reply_markup": {"inline_keyboard": []}}  # its button goes


def test_cancel_order_ends_it_and_says_what_it_bought(ex: Exchange) -> None:
    setting(miss="limit")
    ex.answer, ex.asks = dict(MISS), {"k": 0.46, "u": 0.48}
    aid = new_alert()
    tap(f"cv:{aid}")
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


def test_cancel_with_nothing_bought(ex: Exchange) -> None:
    setting(miss="limit")
    ex.answer, ex.asks = dict(MISS), {"k": 0.46, "u": 0.48}
    aid = new_alert()
    tap(f"cv:{aid}")
    tap(f"cx:{aid}", mid=2)
    assert engine.tg.sent[-1]["text"] == "<b>Limit order cancelled.</b> Nothing was bought. Your $25 is back in today's limit."
    assert left() == 250.0 and "Copy $25" in buttons(engine.tg.sent[0])  # the alert stays as it was: not copied


def test_an_order_the_exchange_left_open_past_its_time_is_cancelled_here(ex: Exchange) -> None:
    setting(miss="limit")
    ex.answer, ex.asks = dict(MISS), {"k": 0.46, "u": 0.48}
    tap(f"cv:{new_alert()}")
    assert engine.own_pass(now=engine.time.time() + 30 * 60 + engine.OWN_LATE_S + 1) == 1
    assert ex.cancels == ["L1"] and engine.tg.sent[-1]["text"].startswith("<b>Limit order ended.</b> No one sold")


def test_no_seller_at_all_and_a_limit_order_the_exchange_refuses(ex: Exchange, monkeypatch: pytest.MonkeyPatch) -> None:
    ex.answer, ex.asks = dict(MISS), {"k": None, "u": None}
    aid = new_alert()
    tap(f"cv:{aid}")
    assert last()["text"] == "<b>Not bought.</b> No one is selling Yes on Polymarket US right now. Nothing was spent."
    monkeypatch.setattr(own_trading, "place_limit", lambda o, d: {"ok": False, "code": "insufficient_balance"})
    tap(f"cl:{aid}", mid=2)
    assert last()["text"] == "No limit order: your Polymarket US balance is under $25." and left() == 250.0
    tap(f"cl:{aid}", mid=2)
    assert engine.tg.sent[-1]["text"] == "This one is over."


# ---- the amount ----


def test_change_amount_for_just_this_trade(ex: Exchange) -> None:
    aid = new_alert()
    tap(f"ca:{aid}")
    ask = engine.tg.sent[-1]
    assert ask["text"] == "<b>How much?</b>\nNow $25. Smallest is $1."
    assert buttons(ask) == {"$5": f"cu:{aid}:5", "$10": f"cu:{aid}:10", "$50": f"cu:{aid}:50", "Type my own": f"ct:{aid}"}
    tap(f"cu:{aid}:5", mid=2)
    assert last()["message_id"] == 2 and last()["text"] == "<b>$5 for which trades?</b>"
    assert keys(last()["reply_markup"]) == {"Just this trade": f"cj:{aid}:5", "Every trade": f"ce:{aid}:5"}
    tap(f"cj:{aid}:5", mid=2)
    assert last()["text"] == "$5 for this trade. Your usual stays $25."
    b = under_alert()
    assert b["Copy $5"] == f"cv:{aid}" and "Change amount" in b and "Copy $25" not in b
    ex.answer = {"ok": True, "status": "filled", "order_id": "o1", "shares": 11.0, "spent": 4.73, "avg": 0.43}
    tap(f"cv:{aid}")
    assert (ex.orders[-1]["usd"], ex.orders[-1]["size"]) == (5.0, 11)
    assert "$4.73 of Yes at 43¢ (11 contracts)" in last()["text"] and "$245.27 left of today's $250." in last()["text"]
    tap(f"cj:{aid}:10", mid=2)
    assert last()["text"] == "You already tapped Copy on this one."
    assert "Copy $25" in buttons(alert())  # the next alert is at the usual amount again


def test_change_amount_for_every_trade(ex: Exchange) -> None:
    old = new_alert()
    aid = new_alert()
    tap(f"ce:{aid}:10", mid=3)
    assert last()["text"] == "$10 from now on. New alerts' Copy button will say $10."
    assert "Copy $10" in under_alert(2)  # this alert's button too
    assert "Copy $10" in buttons(alert())
    tap(f"cv:{old}")
    assert ex.orders[-1]["usd"] == 25.0  # an alert buys what its button says, whatever the usual amount is now


def test_a_typed_amount(ex: Exchange) -> None:
    aid = new_alert()
    tap(f"ct:{aid}")
    for bad in ("lots", "0.50", "900"):
        say(bad)
        assert engine.tg.sent[-1]["text"] == "That's not an amount I can use. Send a number from 1 to 250."
    say("7.50")
    assert engine.tg.sent[-1]["text"] == "<b>$7.50 for which trades?</b>"
    which = buttons(engine.tg.sent[-1])
    assert which == {"Just this trade": f"cj:{aid}:7.5", "Every trade": f"ce:{aid}:7.5"}
    tap(which["Just this trade"], mid=len(engine.tg.sent))
    assert "Copy $7.50" in under_alert()
    say("12")  # no longer asked: ignored
    assert "Copy $7.50" in under_alert()
    ex.answer, ex.asks = dict(MISS), {"k": 0.46, "u": 0.48}
    tap(f"cv:{aid}")
    tap(f"cl:{aid}", mid=len(engine.tg.sent))
    assert (ex.limits[-1]["usd"], ex.limits[-1]["size"]) == (7.5, 16)  # the limit order follows the amount


# ---- Copy settings ----


def test_copy_settings_opens_from_a_result_and_changes_them(ex: Exchange) -> None:
    tap(f"cv:{new_alert()}")
    tap(keys(last()["reply_markup"])["Copy settings"], mid=2)
    assert engine.tg.sent[-1]["text"] == ("<b>Your copy settings</b>\nAmount: $25 a trade\nIf a copy doesn't fill: ask me\n"
                                          "Top price: 3¢ above the alert's price. Most in a day: $250.")  # fmt: skip
    assert buttons(engine.tg.sent[-1]) == {"Amount": "os:a", "If it doesn't fill": "os:m"}
    tap("os:a", mid=3)
    assert engine.tg.sent[-1]["text"] == "<b>Your usual amount?</b>\nNow $25. Smallest is $1."
    assert list(buttons(engine.tg.sent[-1])) == ["$5", "$10", "$50", "Type my own"]
    tap("oa:5", mid=4)
    assert engine.tg.sent[-1]["text"] == "$5 from now on. New alerts' Copy button will say $5."
    assert "Copy $5" in buttons(alert())
    tap("oa:t", mid=4)
    say("12")
    assert "Copy $12" in buttons(alert())
    tap("os:m", mid=3)
    assert engine.tg.sent[-1]["text"].startswith("<b>If a copy doesn't fill?</b>\nA limit order waits on the exchange at your top price for 30 min.")
    assert list(buttons(engine.tg.sent[-1])) == ["✓ Ask me", "Leave a limit order"]
    tap("om:l", mid=len(engine.tg.sent))
    assert engine.tg.sent[-1]["text"] == "Saved. A copy that doesn't fill now becomes a limit order for 30 min."
    assert list(keys(engine.tg.edits[-1]["reply_markup"])) == ["Ask me", "✓ Leave a limit order"]
    tap("os:o")
    assert "Amount: $12 a trade\nIf a copy doesn't fill: leave a limit order\n" in engine.tg.sent[-1]["text"]


def test_there_are_no_commands_to_remember(ex: Exchange) -> None:
    before = len(engine.tg.sent)
    say("/copy")
    say("/orders")
    assert len(engine.tg.sent) == before


# ---- the words, and an older store ----


@pytest.mark.parametrize(("answer", "says"), [
    ({"ok": False, "code": "not_filled"}, "Not bought: no one is selling at 45¢ or less on Kalshi right now."),
    ({"ok": False, "code": "insufficient_balance"}, "Not bought: your Kalshi balance is under $25."),
    ({"ok": False, "code": "auth_failed"}, "Not bought: Kalshi didn't accept your API key."),
])  # fmt: skip
def test_what_a_tap_says_when_nothing_was_bought(answer: dict[str, Any], says: str) -> None:
    order = {"name": "Kalshi", "max_price": 0.45, "usd": 25.0}
    assert own_trading.result_text(order, answer).startswith(says)


def test_the_choice_between_exchanges() -> None:
    k, u = {"code": "k", "name": "Kalshi"}, {"code": "u", "name": "Polymarket US"}
    order = {"usd": 25.0}
    assert own_trading.pick(order, [u | {"ask": 0.44, "short": False}, k | {"ask": 0.43, "short": False}])["code"] == "k"
    assert own_trading.pick(order, [u | {"ask": 0.43, "short": False}, k | {"ask": 0.43, "short": False}])["code"] == "u"  # a tie: the first
    assert own_trading.pick(order, [u | {"ask": None, "short": False}, k | {"ask": 0.60, "short": False}])["code"] == "k"  # a seller beats none
    assert own_trading.pick(order, [u | {"ask": None, "short": True}, k | {"ask": None, "short": True}])["none"] is True


def test_names_from_the_exchange_are_escaped() -> None:
    order = {"name": "Kalshi", "max_price": 0.45, "usd": 25.0, "label": "A <b> & B", "size": 55, "minutes": 30.0, "alert_id": "a",
             "choices": [{}]}  # fmt: skip
    assert "<b>A &lt;b&gt; &amp; B</b>" in own_trading.buying_text(order)
    assert "A &lt;b&gt; &amp; B at 45¢" in own_trading.resting_text(order)


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
    assert (o["usd"], o["size"], o["label"], o["venue"]) == (25.0, 55, "it", "kalshi")
