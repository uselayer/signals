"""Alert rules (owner, 10 Nov): a rule per trader you follow (smallest trade, markets, skips, a pause), set in Telegram
right after a follow, under every alert (Edit rule, Pause 24 h) and with /rules; short alerts that say which rule they
matched. Places no orders. No network: Telegram, PostHog and the SDK are stand-ins."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import test_alerts as alerts
from fastapi.testclient import TestClient
from test_alerts import ANN, BOB, SAM, _busy, auth, detail_of, sold, trade, user
from uselayer import Trader, TraderDetail, WhalePosition, WhaleTrade

from conftest import live_reads
from signals import app as engine


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    """The alerts tests' engine: a store of its own, a pretend bot, signed in with test keys, every market Politics."""
    return alerts.api.__wrapped__(monkeypatch, tmp_path)  # type: ignore[attr-defined,no-any-return]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """What the engine queued for PostHog (the sender thread is never started)."""
    monkeypatch.setattr(engine, "POSTHOG_KEY", "phc_test")
    monkeypatch.setattr(engine, "_ph_state", {"thread": object()})
    engine._ph_queue.clear()
    yield engine._ph_queue
    engine._ph_queue.clear()


def stored(uid: str = "user_1") -> dict[str, Any]:
    return engine._load_follows()["users"][uid].get("alert_for") or {}


def set_rule(w: str, uid: str = "user_1", **fields: Any) -> None:
    d = engine._load_follows()
    d["users"][uid].setdefault("alert_for", {})[w] = fields
    engine._save_follows(d)


def tap(data: str, chat: int = 555, message_id: int = 1) -> None:
    engine._on_update({"callback_query": {"id": "q", "data": data, "message": {"chat": {"id": chat}, "message_id": message_id}}})


def say(text: str, chat: int = 555) -> None:
    engine._on_update({"message": {"chat": {"id": chat}, "text": text}})


def buttons(markup: dict[str, Any]) -> list[list[tuple[str, str]]]:
    return [[(b["text"], b.get("callback_data", "")) for b in row] for row in markup["inline_keyboard"]]


def last() -> dict[str, Any]:
    return engine.tg.sent[-1]  # type: ignore[no-any-return]


# ---- the rule in follows.json: backward compatible ----


def test_an_older_follows_json_reads_as_it_did(api: TestClient) -> None:
    user(follows=(SAM, ANN, BOB))
    set_rule(SAM, mode="over", usd=1500)
    set_rule(ANN, mode="summary")
    u = engine._load_follows()["users"]["user_1"]
    assert engine._rule(u, SAM) == {"mode": "over", "usd": 1500.0, "cats": [], "first_only": False, "px": None, "paused_until": None}
    assert engine._rule(u, ANN)["mode"] == "summary" and engine._rule(u, BOB)["mode"] == "all"
    assert engine._wants(u, SAM, 1499) == "skip" and engine._wants(u, SAM, 1500) == "send"
    assert engine._wants(u, ANN, 5) == "hold" and engine._wants(u, BOB, 1) == "send"
    me = api.get("/api/me", headers=auth()).json()["alert_for"]  # the page's shape, unchanged for an older rule
    assert me == {SAM: {"mode": "over", "usd": 1500.0}, ANN: {"mode": "summary", "usd": None}, BOB: {"mode": "all", "usd": None}}
    # junk is read as no rule, never a crash
    set_rule(BOB, mode="sometimes", usd="lots", cats="Politics", px=[90, 10], paused_until="soon", first_only="yes")
    u = engine._load_follows()["users"]["user_1"]
    assert engine._rule(u, BOB) == {"mode": "all", "usd": None, "cats": [], "first_only": False, "px": None, "paused_until": None}


def test_the_pages_choice_keeps_the_rest_of_the_rule(api: TestClient) -> None:
    user(follows=(SAM,))
    until = time.time() + 3600
    set_rule(SAM, mode="over", usd=500, cats=["Politics"], first_only=True, px=[10, 90], paused_until=until)
    r = api.put(f"/api/me/follows/{SAM}/alerts", json={"mode": "over", "usd": 700}, headers=auth())
    assert r.status_code == 200
    assert stored()[SAM] == {"mode": "over", "usd": 700.0, "cats": ["Politics"], "first_only": True, "px": [10, 90], "paused_until": until}
    assert r.json()["alert_for"][SAM] == {"mode": "over", "usd": 700.0, "cats": ["Politics"], "first_only": True, "px": [10, 90],
                                          "paused_until": until}  # fmt: skip
    api.put(f"/api/me/follows/{SAM}/alerts", json={"mode": "all"}, headers=auth())  # every trade: the amount goes, the rest stays
    assert stored()[SAM] == {"mode": "all", "cats": ["Politics"], "first_only": True, "px": [10, 90], "paused_until": until}
    api.put(f"/api/me/follows/{SAM}/alerts", json={"mode": "summary"}, headers=auth())
    assert stored()[SAM]["mode"] == "summary" and stored()[SAM]["cats"] == ["Politics"]
    set_rule(SAM, mode="over", usd=500)  # nothing else set: "all" leaves no entry, as before
    api.put(f"/api/me/follows/{SAM}/alerts", json={"mode": "all"}, headers=auth())
    assert SAM not in stored()


# ---- matching ----


def test_each_part_of_a_rule() -> None:
    def wants(rule: dict[str, Any], usd: float = 1000, **kw: Any) -> str:
        return engine._wants({"alert_for": {SAM: rule}}, SAM, usd, **kw)

    assert wants({"mode": "over", "usd": 500}, 499) == "skip" and wants({"mode": "over", "usd": 500}, 500) == "send"
    politics = {"mode": "all", "cats": ["Politics", "Sports"]}
    assert wants(politics, category="Politics") == "send" and wants(politics, category="Sports") == "send"
    assert wants(politics, category="Crypto") == "skip"
    assert wants(politics, category=None) == "skip"  # couldn't read its category: not one you picked (as big trades)
    band = {"mode": "all", "px": [10, 90]}
    assert [wants(band, price=p) for p in (0.09, 0.10, 0.5, 0.90, 0.91)] == ["skip", "send", "send", "send", "skip"]
    assert wants(band, price=None) == "send"  # no price known: it passes
    first = {"mode": "all", "first_only": True}
    assert wants(first, held_before=True) == "skip" and wants(first, held_before=False) == "send"
    assert wants(first, held_before=None) == "send"  # unknown: it passes (an alert too many, never one too few)
    assert wants({"mode": "all"}, held_before=True) == "send"  # off: adds alert as before
    every = {"mode": "over", "usd": 500, "cats": ["Politics"], "px": [10, 90], "first_only": True}
    assert wants(every, 600, category="Politics", price=0.4, held_before=False) == "send"
    assert wants(every, 600, category="Politics", price=0.4, held_before=True) == "skip"
    # a summary holds only what passes the rule
    assert wants({"mode": "summary", "usd": 500}, 600) == "hold" and wants({"mode": "summary", "usd": 500}, 400) == "skip"


def test_a_pause_stops_everything_from_them_then_ends_by_itself() -> None:
    now = time.time()
    paused = {"alert_for": {SAM: {"mode": "all", "paused_until": now + 3600}}}
    assert engine._wants(paused, SAM, 50_000, now=now) == "skip"
    assert engine._wants(paused, SAM, 50, told=True, now=now) == "skip"  # even a sale an alert told you about
    assert engine._wants(paused, SAM, 50_000, now=now + 3601) == "send"  # over: as before
    # not paused: a sale of something an alert told you about still comes, whatever the rule
    strict = {"alert_for": {SAM: {"mode": "over", "usd": 5000, "cats": ["Sports"], "px": [10, 90]}}}
    assert engine._wants(strict, SAM, 10, told=True, category="Politics", price=0.95) == "send"
    assert engine._wants(strict, SAM, 10, category="Politics", price=0.95) == "skip"


def test_first_only_means_they_held_it_before_these_buys() -> None:
    pos = lambda size: WhalePosition("0xa:0", None, "Yes", size, 0.4, 0.5, None, None)  # noqa: E731
    assert engine._held_before(pos(1000), 100, 0, 0.4) is True  # 900 contracts before: an add
    assert engine._held_before(pos(100), 100, 0, 0.4) is False  # all of it is this buy: a first buy
    assert engine._held_before(pos(100.5), 100, 0, 0.4) is False  # half a contract left over: rounding, not a holding
    assert engine._held_before(pos(102), 100, 0, 0.4) is False  # $0.80 before: under a dollar, a stray fill
    assert engine._held_before(pos(60), 100, 50, 0.4) is True  # they sold 50 since: 10 before, $4
    assert engine._held_before(pos(80), 100, 0, 0.4) is False  # Polymarket's positions not caught up: a first buy
    assert engine._held_before(None, 100, 0, 0.4) is None


def _round(monkeypatch: pytest.MonkeyPatch, trades: list[WhaleTrade], held: dict[str, float], prices: dict[str, float]) -> None:
    """Sam's trades and open positions (contracts held, price now) as the poller reads them."""
    live_reads(monkeypatch, lambda *a, **k: TraderDetail(
        Trader(venue="polymarket", id=SAM, name="Sam"), "visible", {},
        [WhalePosition(m, None, "Yes", held.get(m, 1), 0.4, p, None, None) for m, p in prices.items()],
        [t for t in trades if t.trader == (a[1] if len(a) > 1 else SAM)]))  # fmt: skip


def test_rules_decide_who_gets_each_buy_in_a_round(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    for uid, chat in (("plain", "1"), ("politics", "2"), ("sports", "3"), ("first", "4"), ("band", "5"), ("paused", "6")):
        user(uid, chat, follows=(SAM,))
    set_rule(SAM, "politics", mode="over", usd=500, cats=["Politics"])
    set_rule(SAM, "sports", mode="all", cats=["Sports"])
    set_rule(SAM, "first", mode="all", first_only=True)
    set_rule(SAM, "band", mode="all", px=[10, 90])
    set_rule(SAM, "paused", mode="all", paused_until=time.time() + 3600)
    trades: list[WhaleTrade] = []
    held = {"0xnew:0": 2000 / 0.4, "0xadd:0": 5000.0}  # 0xadd: they held 3,750 contracts before this buy
    _round(monkeypatch, trades, held, {"0xnew:0": 0.41, "0xadd:0": 0.41})
    t0 = datetime.now(UTC) - timedelta(minutes=3)
    engine.alert_pass(now=t0.timestamp() - 60)  # first round: noted only
    trades += [trade(SAM, t0, 0.40, 2000, "0xnew:0", "n"), trade(SAM, t0, 0.40, 500, "0xadd:0", "a")]
    engine._cache.clear()
    engine.alert_pass(now=t0.timestamp() + 3 * 60)
    got = sorted((m["chat_id"], "0xnew" in m["text"]) for m in engine.tg.sent)
    # plain: both; politics ($500+ in Politics): both; sports: none (they're Politics); first: only the new position;
    # band (10–90¢, 40¢): both; paused: none
    assert got == [("1", False), ("1", True), ("2", False), ("2", True), ("4", True), ("5", False), ("5", True)]
    tags = {m["chat_id"]: m["text"].splitlines()[0] for m in engine.tg.sent if "0xnew" in m["text"]}
    assert tags["1"].startswith("<b>Sam</b> bought")  # no rule: no tag
    assert tags["2"] == "<i>Matches your rule · $500+ in Politics</i>"
    assert tags["4"] == "<i>Matches your rule · first buys</i>" and tags["5"] == "<i>Matches your rule · 10¢–90¢</i>"
    assert engine._sent_today("paused") == 0 and engine._sent_today("sports") == 0


def test_a_paused_trader_sends_no_sale_and_a_sale_you_were_told_about_still_comes(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user("told", "1", follows=(SAM,))
    user("paused", "2", follows=(SAM,))
    trades: list[WhaleTrade] = []
    live_reads(monkeypatch, detail_of(trades, {"0xb:0": 0.5}))
    t0 = datetime.now(UTC) - timedelta(minutes=10)
    engine.alert_pass(now=t0.timestamp() - 60)
    trades.append(trade(SAM, t0, usd=2000, market="0xb:0", i="b"))
    engine._cache.clear()
    assert engine.alert_pass(now=t0.timestamp() + 60) == 2  # both told about the buy
    set_rule(SAM, "told", mode="over", usd=10_000, cats=["Sports"])  # then a rule the sale doesn't pass
    set_rule(SAM, "paused", mode="all", paused_until=time.time() + 3600)
    trades.append(sold(SAM, t0 + timedelta(minutes=2), usd=300, market="0xb:0"))
    engine._cache.clear()
    assert engine.alert_pass(now=t0.timestamp() + 3 * 60) == 1
    assert engine.tg.sent[-1]["chat_id"] == "1" and "<b>Sam</b> sold" in engine.tg.sent[-1]["text"]


def test_a_buy_a_rule_skips_never_joins_a_group(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(follows=(SAM, ANN))
    set_rule(ANN, mode="over", usd=5000)
    trades: list[WhaleTrade] = []
    live_reads(monkeypatch, detail_of(trades, {"0xg:0": 0.5}))
    t0 = datetime.now(UTC) - timedelta(minutes=10)
    engine.alert_pass(now=t0.timestamp() - 60)
    trades += [trade(SAM, t0, usd=1000, market="0xg:0", i="s"), trade(ANN, t0 + timedelta(minutes=1), usd=1000, market="0xg:0", i="a")]
    engine._cache.clear()
    assert engine.alert_pass(now=t0.timestamp() + 3 * 60) == 1
    assert "traders you follow" not in engine.tg.sent[-1]["text"] and "<b>Sam</b> bought" in engine.tg.sent[-1]["text"]


def test_a_rule_with_markets_reads_a_sales_market_only_when_it_needs_it(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[list[str]] = []
    monkeypatch.setattr(engine, "_categories", lambda markets: asked.append(list(markets)) or {m: "Politics" for m in markets})
    user(follows=(SAM,))
    trades: list[WhaleTrade] = []
    live_reads(monkeypatch, detail_of(trades, {"0xs:0": 0.5}))
    t0 = datetime.now(UTC) - timedelta(minutes=10)
    engine.alert_pass(now=t0.timestamp() - 60)
    trades.append(sold(SAM, t0, usd=300, market="0xs:0", i="1"))
    engine._cache.clear()
    assert engine.alert_pass(now=t0.timestamp() + 60) == 1 and asked == []  # no rule with markets: no read
    set_rule(SAM, mode="all", cats=["Sports"])
    trades.append(sold(SAM, t0 + timedelta(minutes=1), usd=300, market="0xs:1", i="2"))
    engine._cache.clear()
    assert engine.alert_pass(now=t0.timestamp() + 2 * 60) == 0 and asked == [["0xs:1"]]  # Politics: not picked


# ---- short alerts ----


def test_the_tag_names_the_parts_of_the_rule_that_are_set() -> None:
    def tag(**c: Any) -> str:
        return engine._rule_tag(engine._rule({"alert_for": {SAM: c}}, SAM))

    assert tag(mode="all") == "" and tag(mode="summary") == "" and tag(mode="all", paused_until=time.time() + 60) == ""
    assert tag(mode="over", usd=500, cats=["Politics"]) == "<i>Matches your rule · $500+ in Politics</i>\n"
    assert tag(mode="over", usd=1250.5) == "<i>Matches your rule · $1,250.50+</i>\n"
    assert tag(mode="all", cats=["Sports", "Politics"]) == "<i>Matches your rule · in Politics, Sports</i>\n"
    assert (tag(mode="over", usd=1000, cats=["Crypto"], px=[10, 90], first_only=True)
            == "<i>Matches your rule · $1,000+ in Crypto · 10¢–90¢ · first buys</i>\n")  # fmt: skip


def test_a_buy_alert_is_three_short_lines_and_its_links(api: TestClient) -> None:
    user(follows=(SAM,))
    set_rule(SAM, mode="over", usd=500, cats=["Politics"])
    t0 = datetime(2026, 11, 10, 14, 2, tzinfo=UTC)
    b = engine.NewBuy(SAM, [trade(SAM, t0, 0.41, 1240)], 0.42, seen=t0.timestamp() + 6 * 60)
    engine._deliver("user_1", "555", b, "Politics", engine._rule_tag(engine._rule(engine._load_follows()["users"]["user_1"], SAM)))
    lines = last()["text"].splitlines()
    assert lines[:3] == ["<i>Matches your rule · $500+ in Politics</i>", "<b>Sam</b> bought <b>Yes</b> · Will it &lt;rain&gt;?",
                         "$1,240 at 41¢ · 6 min ago. Now 42¢."]  # fmt: skip
    assert lines[3] == engine.TRADED_INTL and "Check current price" in lines[4] and "Buy on Polymarket International" in lines[4]
    assert len(lines) == 5 and "UTC" not in last()["text"] and "typically" not in last()["text"]
    assert buttons(last()["reply_markup"]) == [[("Edit rule", f"re:{SAM}"), ("Pause 24 h", f"rp:{SAM}")],
                                               [("Useful", buttons(last()["reply_markup"])[1][0][1]),
                                                ("Not useful", buttons(last()["reply_markup"])[1][1][1])]]  # fmt: skip
    moved = engine._alert_text(SAM, trade(SAM, t0, 0.41, 1240), 0.41, 0.60, 1240, t0.timestamp(), t0.timestamp() + 2 * 3600)
    assert "$1,240 at 41¢ · 2 h ago. Now 60¢, price already moved." in moved and "get in" not in moved


# ---- setup right after a follow ----


def test_set_my_rule_in_three_steps(api: TestClient, monkeypatch: pytest.MonkeyPatch, sent: Any) -> None:
    user(follows=(SAM,))
    _busy(monkeypatch, 100, time.time(), big=3)
    engine._pace_after_follow("user_1", SAM)
    tap(f"rs:{SAM}")
    step1 = last()
    assert step1["text"].startswith("<b>1 of 3 · Alert me when Sam buys at least…</b>")
    assert "Based on their past week, trades of about $2,000 or more came roughly 3 times a day." in step1["text"]
    assert "not a promise" in step1["text"]  # the suggested amount is an estimate, as before
    assert buttons(step1["reply_markup"]) == [
        [("$100", f"rm:{SAM}:100:s"), ("$500", f"rm:{SAM}:500:s"), ("$1,000", f"rm:{SAM}:1000:s")],
        [("$2,000", f"rm:{SAM}:2000:s"), ("Type my own", f"rt:{SAM}:s")]]
    tap(f"rm:{SAM}:500:s", message_id=7)
    assert stored()[SAM] == {"mode": "over", "usd": 500.0}  # saved at once
    assert buttons(engine.tg.edits[-1]["reply_markup"])[0][1] == ("✓ $500", f"rm:{SAM}:500:s")  # ✓ where it was tapped
    step2 = last()
    assert step2["text"].startswith("<b>2 of 3 · Which markets?</b>")
    names = [t for row in buttons(step2["reply_markup"]) for t, _ in row]
    assert names[: len(engine.INTEREST_CHOICES)] == list(engine.INTEREST_CHOICES) and names[-2:] == ["✓ All markets", "Done"]
    n = len(engine.tg.sent)
    tap(f"rc:{SAM}:0:s", message_id=8)  # Politics
    tap(f"rc:{SAM}:1:s", message_id=8)  # Sports
    tap(f"rc:{SAM}:1:s", message_id=8)  # Sports off again
    assert len(engine.tg.sent) == n  # toggles edit the keyboard in place: no new message
    edit = engine.tg.edits[-1]
    assert edit["message_id"] == 8 and buttons(edit["reply_markup"])[0][:2] == [("✓ Politics", f"rc:{SAM}:0:s"), ("Sports", f"rc:{SAM}:1:s")]
    assert buttons(edit["reply_markup"])[-1][0][0] == "All markets" and stored()[SAM]["cats"] == ["Politics"]
    tap(f"rn:{SAM}:2:s")
    step3 = last()
    assert step3["text"].startswith("<b>3 of 3 · Skip these?</b>")
    assert buttons(step3["reply_markup"]) == [[("Adds to a position they already hold", f"rk:{SAM}:f:s")],
                                              [("Prices above 90¢ or below 10¢", f"rk:{SAM}:p:s")], [("Done", f"rn:{SAM}:3:s")]]
    tap(f"rk:{SAM}:p:s", message_id=9)
    assert buttons(engine.tg.edits[-1]["reply_markup"])[1][0][0] == "✓ Prices above 90¢ or below 10¢"
    tap(f"rn:{SAM}:3:s")
    assert last()["text"] == ("Saved: <b>Sam</b>\nWhen: $500 or more\nIn: Politics\nSkip: prices above 90¢ or below 10¢\n"
                              "Change it any time with /rules.")  # markets set: last week's count isn't known, so none
    assert stored()[SAM] == {"mode": "over", "usd": 500.0, "cats": ["Politics"], "px": [10, 90]}
    evs = [(e["event"], e["properties"].get("fields")) for e in sent if e["event"].startswith("telegram rule")]
    assert evs == [("telegram rule setup started", []), ("telegram rule saved", ["usd", "cats", "px"])]
    assert "555" not in json.dumps(list(sent))  # never the chat
    with engine._db() as con:
        assert con.execute("SELECT kind, target FROM events WHERE kind LIKE 'rule%' ORDER BY rowid").fetchall() == [
            ("rule_started", "none"), ("rule_saved", "usd,cats,px")]


def test_every_trade_from_the_setup_clears_any_rule(api: TestClient) -> None:
    user(follows=(SAM,))
    set_rule(SAM, mode="over", usd=500, cats=["Politics"])
    tap(f"ra:{SAM}")
    assert SAM not in stored() and last()["text"] == "OK, every trade from <b>Sam</b>. Change it any time with /rules."


def test_saved_says_how_many_alerts_last_week_only_when_it_can_be_known(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user(follows=(SAM,))
    _busy(monkeypatch, 100, time.time(), big=3)  # 700 $50 buys and 21 $2,000 ones over the week, all at 50¢
    engine._measure_pace(SAM)
    tap(f"ro:{SAM}:m")
    tap(f"rm:{SAM}:1000:e")
    assert last()["text"] == ("Saved: <b>Sam</b>\nWhen: $1,000 or more\nIn: all markets\nAbout 21 buy alerts last week instead of 721.\n"
                              "Change it any time with /rules.")  # fmt: skip
    tap(f"ro:{SAM}:k")
    tap(f"rk:{SAM}:f:e")
    tap(f"rn:{SAM}:3:e")
    assert "last week" not in last()["text"]  # "first buys": what they held wasn't read, so no count
    tap(f"rk:{SAM}:f:e")
    with engine._db() as con:
        con.execute("UPDATE pace SET days = 3")  # a measure that didn't cover the whole week: no count
    tap(f"rn:{SAM}:3:e")
    assert "last week" not in last()["text"]


# ---- Type my own ----


@pytest.mark.parametrize(("typed", "usd"), [("750", 750.0), ("$750", 750.0), ("1,000", 1000.0), ("$1,250.50", 1250.5),
                                            (" 750 dollars ", 750.0), ("$ 2,500,000", 2_500_000.0), ("80 USD", 80.0)])  # fmt: skip
def test_a_typed_amount(typed: str, usd: float) -> None:
    assert engine.parse_amount(typed) == usd


@pytest.mark.parametrize("typed", ["abc", "", "0", "$0", "-5", "7,50", "1e5", "750.123", "10000001", "seven hundred", "1.000,00"])
def test_not_a_typed_amount(typed: str) -> None:
    assert engine.parse_amount(typed) is None


def test_type_my_own_waits_for_the_amount_and_says_when_it_isnt_one(api: TestClient, sent: Any) -> None:
    user(follows=(SAM,))
    tap(f"rt:{SAM}:s")
    assert last()["text"] == "Send the smallest buy you want to hear about, in dollars. For example 750."
    say("lots")
    assert last()["text"] == "That's not an amount. Send a number, like 750." and SAM not in stored()
    say("$1,250")  # still waiting: this one counts
    assert stored()[SAM] == {"mode": "over", "usd": 1250.0}
    assert last()["text"].startswith("<b>2 of 3 · Which markets?</b>")  # the setup goes on
    n = len(engine.tg.sent)
    say("900")  # answered already: plain words are ignored again
    assert len(engine.tg.sent) == n and stored()[SAM]["usd"] == 1250.0
    assert [e["event"] for e in sent] == ["telegram typed amount invalid"] and sent[0]["properties"]["wallet"] == SAM
    assert "lots" not in json.dumps(list(sent))  # never what they typed


def test_type_my_own_ends_after_ten_minutes_or_any_command_and_survives_a_restart(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user(follows=(SAM,))
    tap(f"rt:{SAM}:e")
    engine._db_ready.clear()  # a restart: the wait is in alerts.db, not memory
    say("600")
    assert stored()[SAM]["usd"] == 600.0 and last()["text"].startswith("Saved: <b>Sam</b>\nWhen: $600 or more")
    tap(f"rt:{SAM}:e")
    say("/list")  # a command cancels it
    say("700")
    assert stored()[SAM]["usd"] == 600.0
    tap(f"rt:{SAM}:e")
    later = time.time() + engine.TYPING_S + 1
    monkeypatch.setattr(engine.time, "time", lambda: later)
    n = len(engine.tg.sent)
    say("800")  # too late: ignored, never "not an amount"
    assert stored()[SAM]["usd"] == 600.0 and len(engine.tg.sent) == n
    with engine._db() as con:
        assert con.execute("SELECT COUNT(*) FROM typing").fetchone()[0] == 0


def test_type_my_own_is_only_for_a_trader_this_chat_follows(api: TestClient) -> None:
    user(follows=(SAM,))
    tap(f"rt:{ANN}:s")  # not followed: nothing asked
    tap(f"rt:{SAM}:s", chat=999)  # not a connected chat: nothing asked
    assert engine.tg.sent == []
    say("750", chat=999)
    assert SAM not in stored()


# ---- Edit rule, Pause 24 h, /rules ----


def test_edit_rule_shows_the_rule_and_each_part_changes_it(api: TestClient, sent: Any) -> None:
    user(follows=(SAM,))
    set_rule(SAM, mode="over", usd=500, cats=["Politics"], first_only=True)
    tap(f"re:{SAM}")
    assert last()["text"] == ("<b>Alert rule for Sam</b>\nWhen: $500 or more\nIn: Politics\nSkip: adds to a position they already hold\n"
                              "Delivery: each trade as it comes")  # fmt: skip
    assert buttons(last()["reply_markup"]) == [
        [("Minimum size", f"ro:{SAM}:m"), ("Markets", f"ro:{SAM}:c")], [("Skip", f"ro:{SAM}:k"), ("Delivery", f"ro:{SAM}:d")],
        [("Stop alerts from Sam", f"unf:{SAM}")]]
    tap(f"ro:{SAM}:m")
    assert last()["text"].startswith("<b>Alert me when Sam buys at least…</b>")
    assert buttons(last()["reply_markup"]) == [
        [("$100", f"rm:{SAM}:100:e"), ("✓ $500", f"rm:{SAM}:500:e"), ("$1,000", f"rm:{SAM}:1000:e")],
        [("Type my own", f"rt:{SAM}:e")], [("Any amount", f"rm:{SAM}:0:e")]]
    tap(f"rm:{SAM}:0:e")  # any amount: the rest of the rule stays
    assert stored()[SAM] == {"mode": "all", "cats": ["Politics"], "first_only": True}
    assert last()["text"].startswith("Saved: <b>Sam</b>\nWhen: any amount\nIn: Politics")
    tap(f"ro:{SAM}:c")
    assert last()["text"].startswith("<b>Which markets for Sam?</b>") and buttons(last()["reply_markup"])[0][0][0] == "✓ Politics"
    tap(f"rc:{SAM}:a:e")
    assert "cats" not in stored()[SAM]
    tap(f"ro:{SAM}:d")
    assert buttons(last()["reply_markup"]) == [[("✓ Each trade as it comes", f"rd:{SAM}:e")], [("A summary every 6 hours", f"rd:{SAM}:s")]]
    tap(f"rm:{SAM}:500:e")
    tap(f"rd:{SAM}:s")  # a summary keeps the amount: only what passes the rule is summed up
    assert stored()[SAM] == {"mode": "summary", "usd": 500.0, "first_only": True}
    assert "Delivery: a summary every 6 hours" in last()["text"]
    assert engine._choice(engine._load_follows()["users"]["user_1"], SAM) == ("summary", None)  # the page's view
    tap(f"rd:{SAM}:e")
    assert stored()[SAM] == {"mode": "over", "usd": 500.0, "first_only": True}
    edits = [e["properties"]["field"] for e in sent if e["event"] == "telegram rule edited"]
    assert edits == ["usd", "usd", "delivery", "delivery"]  # a market tap saves at once; "rule edited" is on Done


def test_pause_24_hours_and_undo(api: TestClient, sent: Any) -> None:
    user(follows=(SAM,))
    tap(f"rp:{SAM}")
    assert last()["text"] == "<b>Sam</b> paused for 24 hours."
    assert buttons(last()["reply_markup"]) == [[("Undo", f"ru:{SAM}")]]
    until = stored()[SAM]["paused_until"]
    assert until == pytest.approx(time.time() + 24 * 3600, abs=5)
    u = engine._load_follows()["users"]["user_1"]
    assert engine._wants(u, SAM, 10_000) == "skip"
    tap(f"re:{SAM}")
    assert "Paused: alerts resume in 24 h." in last()["text"]
    assert ("Resume alerts now", f"ru:{SAM}") in [b for row in buttons(last()["reply_markup"]) for b in row]
    tap(f"ru:{SAM}")
    assert last()["text"] == "Alerts from <b>Sam</b> are back on." and SAM not in stored()
    assert [e["event"] for e in sent] == ["telegram trader paused", "telegram trader unpaused"]
    assert sent[0]["properties"]["hours"] == 24


def test_rules_lists_every_trader_with_a_button_each(api: TestClient) -> None:
    user(follows=(SAM, ANN, BOB))
    set_rule(SAM, mode="over", usd=500, cats=["Politics"], px=[10, 90])
    set_rule(ANN, mode="summary", paused_until=time.time() + 3 * 3600 + 60)
    say("/rules")
    assert last()["text"].splitlines() == ["<b>Your alert rules</b>", "• <b>Sam</b>: $500+ in Politics · 10¢–90¢",
                                           "• <b>Ann</b>: every trade · a summary every 6 hours · paused, 3 h left",
                                           "• <b>Bob</b>: every trade", "Tap a trader to change their rule."]  # fmt: skip
    assert buttons(last()["reply_markup"]) == [[("Sam", f"re:{SAM}")], [("Ann", f"re:{ANN}")], [("Bob", f"re:{BOB}")]]
    user("user_2", chat="777", follows=())
    say("/rules", chat=777)
    assert last()["text"].startswith("You don't follow anyone yet.")


def test_stop_alerts_from_the_rule_still_unfollows_and_old_buttons_still_work(api: TestClient) -> None:
    user(follows=(SAM, ANN))
    tap(f"unf:{SAM}")  # "Stop alerts from Sam", now in Edit rule (and on alerts sent before 10 Nov)
    assert engine._load_follows()["users"]["user_1"]["follows"] == [ANN]
    tap(f"few:{ANN}")  # "Fewer alerts" on an older alert
    assert last()["text"].startswith("From <b>Ann</b> you get every trade.")
    set_rule(ANN, mode="all", cats=["Politics"])
    tap(f"am:{ANN}:s")  # an older choice keeps the rule's markets
    assert stored()[ANN] == {"mode": "summary", "cats": ["Politics"]}


def test_rule_buttons_do_nothing_for_a_trader_not_followed_or_a_stranger(api: TestClient) -> None:
    user(follows=(SAM,))
    for data in (f"rs:{ANN}", f"rm:{ANN}:500:s", f"rp:{ANN}", f"re:{ANN}", f"rc:{ANN}:0:s"):
        tap(data)
    for data in (f"rs:{SAM}", f"rp:{SAM}", f"rm:{SAM}:500:e"):
        tap(data, chat=999)
    tap(f"rc:{SAM}:99:s")  # no such market
    tap(f"rm:{SAM}:lots:s")
    assert engine.tg.sent == [] and stored() == {}


def test_every_buttons_data_fits_telegrams_64_bytes(api: TestClient) -> None:
    user(follows=(SAM,))
    r = engine._rule({"alert_for": {SAM: {"mode": "summary", "usd": 9_999_999, "paused_until": time.time() + 60}}}, SAM)
    p = {"per_day": 500.0, "usd": 9_999_999.0, "days": 7.0, "at": time.time()}
    markups = [engine._setup_markup(SAM), engine._min_markup(SAM, p, "s", r), engine._min_markup(SAM, p, "e", r),
               engine._cats_markup(SAM, r, "e"), engine._skip_markup(SAM, r, "s"), engine._edit_markup(SAM, r),
               engine._delivery_markup(SAM, r), engine._keyboard("abcdefgh", SAM)]  # fmt: skip
    for m in markups:
        for row in m["inline_keyboard"]:
            for b in row:
                assert len(b.get("callback_data", "").encode()) <= 64, b


def test_metrics_count_rules(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "METRICS_KEY", "k")
    user(follows=(SAM, ANN))
    tap(f"rs:{SAM}")
    tap(f"rm:{SAM}:500:s")
    tap(f"rn:{SAM}:3:s")
    tap(f"rp:{ANN}")
    tap(f"rt:{SAM}:e")
    say("nope")
    m = api.get("/api/metrics", headers={"Authorization": "Bearer k"}).json()["rules"]
    assert (m["setup_started"], m["saved"], m["saved_with"], m["paused"], m["typed_amount_invalid"]) == (1, 1, {"usd": 1}, 1, 1)
    assert (m["follows_now"], m["follows_with_a_rule_now"], m["by_part_now"]["usd"], m["paused_now"]) == (2, 1, 1, 1)


def test_the_bots_words_never_mention_copying_or_fewer_alerts() -> None:
    r = engine._rule({"alert_for": {SAM: {"mode": "over", "usd": 500, "cats": ["Politics"], "px": [10, 90]}}}, SAM)
    p = {"per_day": 50.0, "usd": 2000.0, "days": 7.0, "at": time.time()}
    words = " ".join([engine.CONNECTED, engine._setup_text(SAM, p), engine._min_text(SAM, p, "s"), engine._cats_text(SAM, "s"),
                      engine._skip_text(SAM, "s"), engine._edit_text(SAM, r), engine.TYPE_ASK, engine.TYPE_AGAIN,
                      json.dumps([engine._setup_markup(SAM), engine._skip_markup(SAM, r, "s"), engine._edit_markup(SAM, r)])])  # fmt: skip
    assert "copy" not in words.lower() and "Fewer alerts" not in words and " bet" not in words.lower()


# ---- follow-ups (owner, 11 Nov): the name once after a follow; no clock times in summaries ----


@pytest.fixture
def pace_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Following measures pace and asks for a rule right away, on this thread (no Polymarket: _busy stands in)."""
    monkeypatch.setattr(engine, "_pace_later", lambda uid, trader, wait_s=None: engine._pace_after_follow(uid, trader, wait_s))


def _start_link(api: TestClient, monkeypatch: pytest.MonkeyPatch, wallet: str, chat: int) -> None:
    monkeypatch.setattr(engine, "_tg", {"bot": "SignalsAlertsBot", "offset": 0, "error": None, "login_refused": None})
    code = api.post("/api/follow/telegram", json={"wallet": wallet}).json()["code"]
    say(f"/start {code}", chat=chat)


def test_a_follow_from_the_bot_names_the_trader_once(api: TestClient, monkeypatch: pytest.MonkeyPatch, pace_now: None) -> None:
    _busy(monkeypatch, 30, time.time())
    _start_link(api, monkeypatch, SAM, 900)  # a new chat: the help (no names), then the rule setup
    texts = [m["text"] for m in engine.tg.sent]
    assert len(texts) == 2 and texts[0].startswith("Connected.") and "/rules: your alert rules" in texts[0]
    assert texts[1] == "You're following <b>Sam</b>. They made about 30 trades a day last week.\n\nChoose which ones reach you?"
    assert sum(t.count("Sam") for t in texts) == 1
    assert buttons(engine.tg.sent[1]["reply_markup"]) == [[("Set my rule", f"rs:{SAM}"), ("Every trade", f"ra:{SAM}")]]
    engine.tg.sent.clear()
    _start_link(api, monkeypatch, ANN, 900)  # the same chat follows another: only the setup
    assert [m["text"] for m in engine.tg.sent] == [
        "You're following <b>Ann</b>. They made about 30 trades a day last week.\n\nChoose which ones reach you?"]
    engine.tg.sent.clear()
    _start_link(api, monkeypatch, ANN, 900)  # already following: said once, no setup again
    assert [m["text"] for m in engine.tg.sent] == ["You already follow <b>Ann</b>. Change their alerts with /rules."]


def test_a_follow_from_the_site_names_the_trader_once(api: TestClient, monkeypatch: pytest.MonkeyPatch, pace_now: None) -> None:
    user(follows=())
    _busy(monkeypatch, 30, time.time())
    api.post("/api/me/follows", json={"wallet": SAM}, headers=auth())
    assert [m["text"].count("Sam") for m in engine.tg.sent] == [1]


def test_a_follow_from_the_bot_asks_without_the_pace_when_measuring_is_slow(
    api: TestClient, monkeypatch: pytest.MonkeyPatch, pace_now: None
) -> None:
    measured = []

    def slow(trader: str, now: float | None = None) -> dict[str, Any]:
        time.sleep(0.3)
        measured.append(trader)
        return {"per_day": 40.0, "usd": None, "days": 7.0, "at": time.time()}

    monkeypatch.setattr(engine, "_measure_pace", slow)
    monkeypatch.setattr(engine, "FOLLOW_PACE_WAIT_S", 0.02)
    _start_link(api, monkeypatch, SAM, 900)
    assert engine.tg.sent[-1]["text"] == "You're following <b>Sam</b>.\n\nChoose which ones reach you?"  # no made-up pace
    time.sleep(0.5)
    assert measured == [SAM]  # it carried on, for the next step's suggestion


def test_a_summary_says_how_long_it_covers_never_a_clock_time() -> None:
    now = time.time()
    rows = [(SAM, "buy", 700.0, now - 6 * 3600 - 120), (SAM, "sell", 300.0, now - 600)]
    text = engine._summary_text(rows, None, now)
    assert text.splitlines()[0] == "From traders you follow, over the last 6 h:" and "UTC" not in text
    assert engine._summary_text(rows[1:], None, now).splitlines()[0] == "From traders you follow, over the last 10 min:"
