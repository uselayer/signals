"""Breakdowns beyond 15-minute windows: market types (signals/research/markets.py), a market's reads over weeks
(data.py), its replay and tile (workspace.build_market), Start's market tiles (case.prebuild_markets), the plan's
market type, and the wording check (trace.banned_words). The 15-minute path's own tests are test_research.py."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("RESEARCH_STORE_DIR", tempfile.mkdtemp(prefix="research-test-"))

from signals.research import agent as A  # noqa: E402
from signals.research import case as C  # noqa: E402
from signals.research import data as D  # noqa: E402
from signals.research import markets as M  # noqa: E402
from signals.research import trace, workspace  # noqa: E402
from signals.research.store import Store  # noqa: E402

W = "0x" + "cd" * 20
DAY = 86_400
T0 = 1_790_000_000  # 21 Sep 2026
SLUG = "will-bitcoin-reach-100000-by-december-31-2026"
CID = "0x" + "11" * 32
REACH_RULES = ('This market will immediately resolve to "Yes" if any Binance 1 minute candle for Bitcoin (BTC/USDT) '
               'between November 24, 2025, 14:00 and December 31, 2026, 23:59 in the ET timezone has a final "High" '
               'price equal to or greater than the price specified in the title. Otherwise, this market will resolve '
               'to "No."')  # fmt: skip
DIP_RULES = ('This market will immediately resolve to "Yes" if any Binance 1 minute candle for BTC/USDT during the '
             'month specified in the title has a final Low price equal to or less than the price specified in the title.')
CLOSE_RULES = ('This market will resolve to "Yes" if the Binance 1 minute candle for BTC/USDT closing at 12:00 in the ET '
               'timezone (noon) on the date specified in the title has a final "Close" price higher than the price '
               'specified in the title. Otherwise, this market will resolve to "No".')  # fmt: skip


# ---- market types ----


def test_each_market_reads_its_own_rule_from_its_rules() -> None:
    reach = M.btc_rule({"question": "Will Bitcoin reach $100,000 by December 31, 2026?", "description": REACH_RULES})
    assert reach["kind"] == "touch_high" and reach["strike"] == 100_000 and reach["binance"]
    assert "Binance BTCUSDT 1-minute candle's High reaches $100,000" in reach["says"]
    dip = M.btc_rule({"question": "Will Bitcoin dip to $67.5k in November?", "description": DIP_RULES})
    assert dip["kind"] == "touch_low" and dip["strike"] == 67_500
    close = M.btc_rule({"question": "Will the price of Bitcoin be above $66,000 on November 14?", "description": CLOSE_RULES})
    assert close["kind"] == "close_above" and "one moment, not any time" in close["says"]
    other = M.btc_rule({"question": "Will Bitcoin reach $1m?", "description": "Resolves per Coinbase BTC-USD."})
    assert other["kind"] == "other" and other["source"] == "Coinbase" and not other["binance"] and other["strike"] == 1e6


def test_market_types_are_a_list_politics_and_sports_join_with_one_entry() -> None:
    assert [t.id for t in M.TYPES][:2] == ["btc-updown-15m", "btc-long"]
    assert M.of_scope(None).id == "btc-updown-15m" and M.of_scope({"family": "btc-updown-15m"}).unit == "window"
    assert M.of_scope({"market_type": "btc-long"}).unit == "market" and M.by_id("long-dated-crypto").id == "btc-long"
    assert M.btc_long_matches("will-bitcoin-dip-to-65k-in-november-2026", {})
    assert not M.btc_long_matches("btc-updown-15m-1794285000", {}) and not M.btc_long_matches("will-china-unban-bitcoin", {})
    assert M.is_window("btc-updown-15m-1794285000") and not M.is_window(SLUG)
    # every type's section is in the agent's instructions, under "# The markets"
    assert all(t.prompt in A.SYSTEM for t in M.TYPES) and A.SYSTEM.index("# The markets") < A.SYSTEM.index("## Long-dated BTC")


def test_the_15_minute_section_is_the_one_the_agent_had_before() -> None:
    old = ("A BTC 15-minute window's slug is btc-updown-15m-<start unix seconds>; it runs 900 seconds and is listed about a "
           "day ahead, so fills before the start are real (pre_open).")  # fmt: skip
    assert old in A.SYSTEM and "buying both sides (Up + Down under $1 together locks a profit" in A.SYSTEM
    # the instructions' own example numbers count as sources: the long-dated section adds none beyond 0, 1 and 15
    import re

    assert set(re.findall(r"\d+", M.BTC_LONG_PROMPT)) <= {"0", "1", "15"}


# ---- the wording check ----


def test_banned_words_are_caught_and_trade_is_not() -> None:
    assert [w for w, _ in trace.banned_words("The strikes it bet against; its bets; betting on BTC")] == ["bet", "bets", "betting"]
    assert trace.banned_words("It trades No on far strikes, a better price, Betty") == []
    assert trace.banned_words("its edge") and trace.banned_words("It's a bot") and trace.banned_words("ROI of 3%")


def test_a_finding_with_bet_is_sent_back_once_to_reword() -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    events: list[dict[str, Any]] = []
    case = C.Case(sid, 1, store, None, events.append, lambda: trace.Sources(["{}"]))
    f = {"label": "observed", "title": "The strikes it bet against were far from BTC"}
    text, failed, _ = case.handle("finding", f)
    assert failed and "'bet' (say trade, never bet)" in text and not events
    assert not case.handle("finding", {**f, "title": "The strikes it traded No on were far from BTC"})[1]
    assert events[-1]["type"] == "finding.added"


# ---- reads over weeks ----


class Whales:
    """The SDK's Whales for a market: 1-minute price history refused over 15 days, as Polymarket does."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self._poly = Poly()

    def price_history(self, token: str, a: int, b: int) -> list[tuple[int, float]]:
        assert b - a <= 15 * DAY, "interval is too long"
        self.calls.append((a, b))
        return [(t, 0.2 + 0.6 * (t - T0) / (120 * DAY)) for t in range(a - a % 60 + 60, b + 1, 60)]

    def trades_between(self, *a: Any, **k: Any) -> list[Any]:
        return []


def _gamma(slug: str = SLUG, cid: str = CID, closed: bool = False, prices: str = '["0.3", "0.7"]', **kw: Any) -> dict[str, Any]:
    return {"slug": slug, "conditionId": cid, "question": "Will Bitcoin reach $100,000 by December 31, 2026?",
            "description": REACH_RULES, "outcomes": '["Yes", "No"]', "clobTokenIds": '["tY", "tN"]',
            "outcomePrices": prices, "closed": closed, "startDate": "2025-11-24T19:00:00Z", "endDate": "2027-01-01T05:00:00Z",
            "events": [{"slug": "what-price-will-bitcoin-hit-before-2027", "title": "What price will Bitcoin hit before 2027?"}],
            **kw}  # fmt: skip


def _act(ts: int, action: str, outcome: str, price: float, size: float, tx: str) -> dict[str, Any]:
    return {"timestamp": ts, "conditionId": CID, "side": action.upper(), "outcome": outcome,
            "outcomeIndex": 0 if outcome == "Yes" else 1, "asset": "tY" if outcome == "Yes" else "tN", "price": price,
            "size": size, "usdcSize": round(price * size, 6), "transactionHash": tx, "slug": SLUG}  # fmt: skip


class Poly:
    def __init__(self) -> None:
        self.fills = [_act(T0, "buy", "No", 0.8, 100, "0xa"), _act(T0 + 5 * DAY, "buy", "No", 0.85, 100, "0xb"),
                      _act(T0 + 20 * DAY, "sell", "No", 0.9, 50, "0xc")]  # fmt: skip
        self.market = _gamma()

    def markets(self, ids: list[str], closed: bool) -> list[dict[str, Any]]:
        return [self.market] if self.market["closed"] == closed and self.market["conditionId"] in ids else []

    def _list(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [self.market] if str(self.market["closed"]).lower() == params["closed"] else []

    _profiles = "https://gamma"

    def trades_in(self, wallet: str, markets: list[str], limit: int) -> list[dict[str, Any]]:
        return list(reversed(self.fills))  # newest first, as Polymarket lists them


class Binance:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url: str, params: dict[str, Any]) -> Any:
        self.calls += 1
        step = {"1h": 3_600, "1d": DAY, "1m": 60}[params["interval"]]
        a, b = params["startTime"] // 1000, params["endTime"] // 1000
        rows = [[t * 1000, "0", str(80_000 + (t - T0) / 3600), str(79_000 + (t - T0) / 3600), str(79_500 + (t - T0) / 3600)]
                for t in range(a - a % step, b + 1, step)][: params["limit"]]  # fmt: skip
        return type("R", (), {"status_code": 200, "json": lambda self: rows, "raise_for_status": lambda self: None})()


def _reads() -> D.Reads:
    return D.Reads(Whales(), Binance())  # type: ignore[arg-type]


def test_price_history_over_weeks_reads_in_pieces_and_states_its_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 200 * DAY)
    r = _reads()
    pts, step = r.price_series("tY", T0, T0 + 90 * DAY)
    assert step == 3_600 and len(r.whales.calls) == 7 and all(b - a <= 14 * DAY for a, b in r.whales.calls)
    assert len(pts) in (90 * 24, 90 * 24 + 1) and all(q[0] - p[0] <= 3_600 for p, q in zip(pts, pts[1:], strict=False))
    assert r.price_series("tY", T0, T0 + DAY)[1] == 60 and r.price_series("tY", T0, T0 + 10 * DAY)[1] == 900
    m = r.market(SLUG, start=T0, end=T0 + 30 * DAY)
    assert m["coverage"]["price_step_s"] == 3_600 and m["prices"]["No"][0][1] == pytest.approx(1 - m["prices"]["Yes"][0][1])
    assert "1 minus" in m["coverage"]["price_note"] and m["event_slug"] == "what-price-will-bitcoin-hit-before-2027"


def test_binance_past_two_days_gives_hourly_highs_and_lows_and_keeps_ended_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 400 * DAY)
    r = _reads()
    got = r.outside_prices("binance", T0, T0 + 60 * DAY)
    assert got["available"] and got["step"] == "1 hour" and len(got["points"]) in (60 * 24 + 1, 60 * 24 + 2)
    # the first candle's open at its start, then each close at its candle's end: a fill in the first hour has a price
    assert got["points"][0][0] == got["ranges"][0][0] and got["points"][1][0] == got["ranges"][0][0] + 3_600
    assert got["highest"]["high"] == max(h for _, h, _ in got["ranges"]) and got["lowest"]["low"] == got["ranges"][0][2]
    calls = r.web.calls  # type: ignore[attr-defined]
    r.outside_prices("binance", T0 + DAY, T0 + 50 * DAY)
    assert r.web.calls == calls  # type: ignore[attr-defined]  # ended 1,000-hour blocks are read once
    assert r.outside_prices("binance", T0, T0 + 200 * DAY)["step"] == "1 day"


def test_a_long_title_is_cut_at_a_whole_word_with_an_ellipsis() -> None:
    q = "How does WilT (0xd6b6…af8b) make money on long-dated Bitcoin price markets like 'Will Bitcoin reach $85,000 in September?'"
    t = D.clip(q)
    assert len(t) <= 120 and t.endswith("in…") and D.clip("How does it trade?") == "How does it trade?"


# ---- a market's replay and tile ----


def _store_with_wallet() -> tuple[Store, str]:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.set_wallet(sid, W)
    return store, sid


def test_an_open_market_is_valued_at_todays_price_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 40 * DAY)
    monkeypatch.setattr(workspace, "now", lambda: T0 + 40 * DAY)
    store, sid = _store_with_wallet()
    r = workspace.build(store, _reads(), sid, SLUG)
    assert r["kind"] == "market" and r["market_type"] == "btc-long" and r["rule"]["kind"] == "touch_high"
    assert [f["action"] for f in r["trades"]] == ["buy", "buy", "sell"] and r["position"][-1]["held"]["No"] == 150
    v = r["value"]
    assert v["profit_kind"] == "open" and v["cost"] == 165 and v["sold_for"] == 45
    assert v["value_now"] == pytest.approx(150 * v["last_prices"]["No"], abs=0.01)
    assert v["profit"] == round(v["value_now"] + 45 - 165, 2)
    assert r["outside"]["name"] == "Binance BTCUSDT" and r["outside"]["step"] == "1 hour" and r["trades"][0]["outside"]
    assert r["axis"]["from"] == T0 - DAY and r["coverage"]["fills_complete"] and r["hold"]["still_held"]
    s = store.summaries(sid)[0]
    assert s["kind"] == "market" and s["profit_kind"] == "open" and "not a result" in s["profit_note"]
    assert s["spark_side"] == "No" and s["event_slug"] and s["held_days"] == 40.0
    assert store.window(sid, SLUG)["complete"]  # the market's whole life was read


def test_a_resolved_market_pays_its_winning_shares_and_one_sold_out_counts_its_sells(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 40 * DAY)
    monkeypatch.setattr(workspace, "now", lambda: T0 + 40 * DAY)
    reads = _reads()
    reads.whales._poly.market = _gamma(closed=True, prices='["0", "1"]', closedTime="2026-10-20 12:00:00+00")
    store, sid = _store_with_wallet()
    v = workspace.build(store, reads, sid, SLUG)["value"]
    assert v["profit_kind"] == "resolved" and v["payout"] == 150 and v["profit"] == 150 + 45 - 165
    reads2 = _reads()
    reads2.whales._poly.fills.append(_act(T0 + 30 * DAY, "sell", "No", 0.95, 150, "0xd"))
    store2, sid2 = _store_with_wallet()
    r = workspace.build(store2, reads2, sid2, SLUG)
    assert r["value"]["profit_kind"] == "closed" and r["value"]["profit"] == round(45 + 142.5 - 165, 2)
    assert r["hold"]["to"] == T0 + 30 * DAY and not r["hold"]["still_held"]


def test_shares_sold_without_a_buy_in_the_fills_leave_the_profit_uncounted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 40 * DAY)
    reads = _reads()
    reads.whales._poly.fills = [_act(T0, "sell", "Yes", 0.2, 100, "0xs")]  # its Yes came from a split, not a fill
    store, sid = _store_with_wallet()
    r = workspace.build(store, reads, sid, SLUG)
    assert r["value"]["profit"] is None and r["coverage"]["shares_not_from_fills"] and not r["coverage"]["fills_complete"]
    assert "splitting dollars" in " ".join(r["coverage"]["notes"])


# ---- Start's tiles for a market type ----


class MarketReads:
    def __init__(self) -> None:
        self.asked: list[tuple[Any, ...]] = []

    def wallet_markets(self, wallet: str, a: int, b: int, mt: str, days: float | None, top: int) -> dict[str, Any]:
        self.asked.append((wallet, a, b, mt, days, top))
        return {"wallet": wallet, "start": a, "asked_from": a, "end": b, "min_days": days or 7.0, "top": top, "matched": 3,
                "markets_traded": 9, "markets_looked_at": 9, "trades_read": 120, "trades_complete": True, "read_to": b,
                "markets": [{"slug": f"will-bitcoin-reach-{k}k-in-november-2026"} for k in (90, 95)]}  # fmt: skip


def test_start_tiles_a_market_type_scope_and_says_what_it_left_out(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []

    def fake_build(store: Any, reads: Any, sid: str, slug: str, tags: Any = None) -> dict[str, Any]:
        built.append(slug)
        cov = {"window_id": slug, "kind": "market", "fills_complete": True, "price_step_s": 3600, "outside": "Binance BTCUSDT",
               "shares_not_from_fills": False, "chainlink": "none", "book": False, "outage": False}  # fmt: skip
        return {"kind": "market", "window_id": slug, "coverage": cov}

    monkeypatch.setattr(workspace, "build", fake_build)
    monkeypatch.setattr(workspace, "summary", lambda r: {"window_id": r["window_id"], "kind": "market"})
    store, sid = _store_with_wallet()
    events: list[dict[str, Any]] = []
    reads = MarketReads()
    scope = {"wallet": W, "market_type": "btc-long", "from": "2026-08-15T00:00:00Z", "to": "2026-11-13T00:00:00Z", "top": 2}
    assert C.prebuild(store, reads, sid, scope, events.append) == 2
    assert sorted(built) == sorted(m["slug"] for m in reads.wallet_markets(W, 0, 1, "btc-long", None, 2)["markets"])
    assert reads.asked[0][3:] == ("btc-long", None, 2)
    cov = events[-1]
    assert cov["type"] == "coverage" and cov["per_source"]["kind"] == "market"
    assert cov["per_source"]["selection"]["matched"] == 3 and cov["per_source"]["selection"]["shown"] == 2
    assert cov["per_source"]["outside"]["name"] == "Binance BTCUSDT"


def test_a_busy_wallets_markets_read_newest_week_first_and_say_where_they_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _reads()
    weeks: list[tuple[int, int]] = []

    def wallet_trades(w: str, a: int, b: int, prefix: Any) -> dict[str, Any]:
        weeks.append((a, b))
        n = 20_000 if len(weeks) <= 2 else 0
        rows = [{"ts": b - 1, "slug": SLUG, "condition_id": CID, "usd": 1.0}] * n
        return {"trades": rows, "count": n, "complete": True, "read_to": b, "note": "", "source": "s"}

    monkeypatch.setattr(reads, "wallet_trades", wallet_trades)
    got = reads._newest_trades(W, T0, T0 + 90 * DAY)
    assert weeks[0] == (T0 + 83 * DAY, T0 + 90 * DAY) and len(weeks) == 2  # newest week first, then it stopped
    assert not got["complete"] and got["start"] == weeks[-1][0] and got["count"] == 40_000
    assert "Partial: read back" in got["note"]


# ---- the plan names its market type ----


def test_a_plan_with_a_market_type_gets_its_defaults_and_a_made_up_one_is_refused() -> None:
    store, sid = _store_with_wallet()
    events: list[dict[str, Any]] = []
    case = C.Case(sid, 1, store, None, events.append, lambda: trace.Sources(["{}"]))
    steps = [{"id": "s", "title": "Read its markets", "source": "Polymarket trades"}]
    out = case.handle("propose_plan", {"title": "t", "scope": {"wallet": W, "market_type": "btc-long", "from": "2026-08-15T00:00:00Z", "to": "now"}, "steps": steps})
    assert not out[1]
    p = events[-1]
    assert p["market"] == {"id": "btc-long", "label": "Long-dated BTC", "unit": "market"}
    assert p["scope"]["min_days"] == 7.0 and p["scope"]["top"] == 20
    bad = case.handle("propose_plan", {"title": "t", "scope": {"wallet": W, "family": "Long-dated Bitcoin price markets"}, "steps": steps})
    assert bad[1] and "isn't a market type" in bad[0]
    ok = case.handle("propose_plan", {"title": "t", "scope": {"wallet": W, "family": "btc-updown-15m"}, "steps": steps})
    assert not ok[1] and events[-1]["market"]["unit"] == "window" and "market_type" not in events[-1]["scope"]


# ---- the page's market data (node) ----


def test_the_pages_market_data_counts_open_markets_apart() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    js = (Path(__file__).resolve().parent.parent / "signals" / "research" / "static" / "js" / "marketdata.js").as_uri()
    code = f"""
import {{ marketTally, filterMarkets, eventGroups, buyDots, marketTypeOf, prepMarket, marketAutoSteps }} from '{js}';
const tiles = [
  {{ window_id: 'a', kind: 'market', profit: 10, profit_kind: 'resolved', event_slug: 'e', event_title: 'E', market_end: 1000000, entries: [{{ t: 913600, action: 'buy', price: 0.9, side: 'No', usd: 9 }}] }},
  {{ window_id: 'b', kind: 'market', profit: -4, profit_kind: 'closed', event_slug: 'e', event_title: 'E', market_end: 1000000, entries: [] }},
  {{ window_id: 'c', kind: 'market', profit: 7, profit_kind: 'open', entries: [] }},
  {{ window_id: 'd', kind: 'market', profit: null, profit_kind: 'open', entries: [] }},
];
const n = marketTally(tiles);
const r = {{ window_id: 'a', title: 'Q', axis: {{ from: 900000, to: 1000000 }}, outcomes: ['Yes', 'No'],
  prices: {{ Yes: [{{ t: 900000, p: 0.1 }}], No: [{{ t: 900000, p: 0.9 }}] }}, rule: {{ strike: 100000 }},
  outside: {{ name: 'Binance BTCUSDT', step: '1 hour', points: [{{ t: 900000, p: 80000 }}], ranges: [] }},
  trades: [{{ trade_id: 'x', t: 913600, side: 'No', action: 'buy', shares: 10, price: 0.9, usd: 9 }}],
  position: [{{ t: 913600, held: {{ Yes: 0, No: 10 }} }}], value: {{ cost: 9, sold_for: 0, profit: 1, profit_kind: 'resolved', payout: 10 }}, result: 'No', market_end: 1000000 }};
const w = prepMarket(r, null), st = marketAutoSteps(w);
console.log(JSON.stringify({{ n, open: filterMarkets(tiles, 'open').map(x => x.window_id), groups: eventGroups(tiles).length,
  days: buyDots(tiles)[0].daysLeft, label: marketTypeOf({{ plans: {{ p: {{ market: {{ label: 'Long-dated BTC', unit: 'market' }} }} }}, planOrder: ['p'] }}).label,
  old: marketTypeOf({{ plans: {{ p: {{}} }}, planOrder: ['p'], summaries: [] }}).label, steps: st.map(s => s.title), at: w.priceAt('No', 950000) }}));
"""
    out = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30, check=True)
    got = json.loads(out.stdout)
    assert got["n"]["made"] == 1 and got["n"]["lostMoney"] == 1 and got["n"]["open"] == 1 and got["n"]["uncounted"] == 1
    assert got["n"]["profitOpen"] == 7 and got["n"]["decided"] == 2
    assert got["open"] == ["c", "d"] and got["groups"] == 1 and got["days"] == 1
    assert got["label"] == "Long-dated BTC" and got["old"] == "BTC Up or Down 15m"
    assert got["steps"] == ["First buy: No", "Resolves No"] and got["at"] == 90


# ---- politics (markets.POLITICS): Gamma's tags, the market's own rules, no outside line, events, merges ----

SENATE_RULES = ("This market will resolve according to the winner of the 2026 midterm Michigan U.S. Senate election, "
                "inclusive of any run-offs.  A candidate shall be considered to represent a party in the event that "
                "he or she is the nominee of the party in question. The resolution source for this market is the "
                "Associated Press, Fox News, and NBC.")  # fmt: skip
CEASEFIRE_RULES = ("This market will resolve to “No” if the United States takes a qualifying military action against "
                   "Iran by the specified date, 11:59 PM Iran Standard Time. Otherwise this market will resolve to “Yes.”")
POL_SLUG = "will-the-democrats-win-the-michigan-senate-race-in-2026"
POL_CID = "0x" + "22" * 32


def test_a_politics_market_is_known_by_its_tags_never_its_slug() -> None:
    assert M.by_id("politics") is M.POLITICS and M.by_id("elections") is M.POLITICS and M.POLITICS.outside is None
    assert M.politics_matches(POL_SLUG, {}) and not M.politics_matches("btc-updown-15m-1794285000", {})  # no facts yet
    assert M.politics_matches(POL_SLUG, {"category": "Politics"}) and not M.politics_matches("x", {"category": "Economy"})
    assert M.politics_matches("x", {"tags": ["Senate Midterm Winners", "Politics"]})
    assert not M.politics_matches("x", {"tags": ["Fed Rates", "Trump", "Economy"]})  # Economy comes first, as on Signals
    assert M.politics_near({"category": "Economy", "tags": ["Fed", "Trump"]}) and not M.politics_near({"category": "Politics"})
    f = D.market_facts({"slug": POL_SLUG, "conditionId": POL_CID, "question": "Will the Democrats win the Michigan Senate race in 2026?",
                        "outcomes": '["Yes", "No"]', "clobTokenIds": '["a", "b"]', "negRisk": True,
                        "groupItemTitle": "Abdul El-Sayed (D)", "tags": [{"label": "Politics"}, {"label": "Midterms"}]})
    assert f["category"] == "Politics" and f["neg_risk"] and f["group_item"] == "Abdul El-Sayed (D)"
    assert M.of_market(POL_SLUG, f) is M.POLITICS and M.of_market(SLUG, D.market_facts(_gamma())) is M.BTC_LONG


def test_what_resolves_a_politics_market_is_quoted_from_its_rules_and_a_kind_only_when_sure() -> None:
    r = M.politics_rule({"question": "Will the Democrats win the Michigan Senate race in 2026?", "description": SENATE_RULES})
    assert r["kind"] == "result" and r["source"] == "the Associated Press, Fox News, and NBC" and r["strike"] is None
    assert r["quote"].endswith("Michigan U.S. Senate election, inclusive of any run-offs.")  # not cut at "U.S."
    c = M.politics_rule({"question": "US x Iran ceasefire continues through November 30?", "description": CEASEFIRE_RULES})
    assert c["kind"] == "by_date" and c["quote"].startswith("This market will resolve to “No” if the United States")
    o = M.politics_rule({"question": "Who will Trump endorse?", "description": "Resolves per the market's group rules."})
    assert o["kind"] == "other" and o["says"].startswith("Its rules say: “Resolves per")
    # a "by a date" chip is never put on an election: the rules and the question have to agree
    assert M.politics_rule({"question": "Will X win the election?", "description": CEASEFIRE_RULES})["kind"] == "other"
    # every type's section is in the agent's instructions, and the politics one adds no example numbers
    import re

    assert M.POLITICS_PROMPT in A.SYSTEM and set(re.findall(r"\d+", M.POLITICS_PROMPT)) <= {"0", "1"}
    assert "never say a trade followed news" in M.POLITICS_PROMPT


class PolPoly(Poly):
    """A politics wallet: the Michigan Senate race's two markets (one per party, negRisk), and a Fed market."""

    def __init__(self) -> None:
        super().__init__()
        self.moves: list[dict[str, Any]] = []
        self.pages: list[dict[str, Any]] = []
        self.market = self._m(POL_SLUG, POL_CID, "Abdul El-Sayed (D)")
        self.fills = [_act(T0, "buy", "Yes", 0.5, 100, "0xa") | {"conditionId": POL_CID, "slug": POL_SLUG},
                      _act(T0 + DAY, "buy", "No", 0.45, 100, "0xb") | {"conditionId": POL_CID, "slug": POL_SLUG}]  # fmt: skip

    @staticmethod
    def _m(slug: str, cid: str, item: str, tags: tuple[str, ...] = ("Politics",), closed: bool = False,
           prices: str = '["0.6", "0.4"]') -> dict[str, Any]:  # fmt: skip
        return {"slug": slug, "conditionId": cid, "question": f"Will {item} win the Michigan Senate race in 2026?",
                "description": SENATE_RULES, "outcomes": '["Yes", "No"]', "clobTokenIds": '["tY", "tN"]',
                "outcomePrices": prices, "closed": closed, "negRisk": True, "groupItemTitle": item,
                "startDate": "2026-06-01T00:00:00Z", "endDate": "2026-11-04T00:00:00Z",
                "tags": [{"label": t} for t in tags],
                "events": [{"slug": "michigan-senate", "title": "Michigan Senate Election Winner"}]}  # fmt: skip

    def _pages(self, path: str, params: dict[str, Any], limit: int, offset: int, page: int) -> list[dict[str, Any]]:
        self.pages.append(params)
        assert params["type"] == "MERGE,SPLIT,CONVERSION" and params["condition"]
        return [m for m in self.moves if m["conditionId"] == params["condition"]]


def _pol_reads() -> D.Reads:
    r = _reads()
    r.whales._poly = PolPoly()
    return r


def test_a_politics_replay_has_no_outside_line_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 10 * DAY)
    monkeypatch.setattr(workspace, "now", lambda: T0 + 10 * DAY)
    store, sid = _store_with_wallet()
    r = workspace.build(store, _pol_reads(), sid, POL_SLUG)
    assert r["market_type"] == "politics" and r["rule"]["kind"] == "result" and r["outside"] is None
    assert r["group_item"] == "Abdul El-Sayed (D)" and r["neg_risk"] and r["event_title"] == "Michigan Senate Election Winner"
    cov = r["coverage"]
    assert cov["outside"] is None and cov["moves_read"] and "no trade here can be tied to news" in " ".join(cov["notes"])
    assert r["value"]["exit"] == {"how": "open"} and r["value"]["profit_kind"] == "open"
    s = store.summaries(sid)[0]
    assert s["group_item"] == "Abdul El-Sayed (D)" and s["coverage"]["outside_none"] and s["exit"] == {"how": "open"}
    assert workspace.totals([cov])["outside"]["none"] and workspace.totals([cov])["moves"] == {"read": 1, "total": 1, "markets_with": 0, "converted": 0}


def test_a_merge_takes_its_pairs_out_and_is_how_it_got_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 40 * DAY)
    monkeypatch.setattr(workspace, "now", lambda: T0 + 40 * DAY)
    reads = _pol_reads()
    reads.whales._poly.market = PolPoly._m(POL_SLUG, POL_CID, "Abdul El-Sayed (D)", closed=True, prices='["1", "0"]') | {
        "closedTime": "2026-11-04 12:00:00+00"}
    reads.whales._poly.moves = [{"timestamp": T0 + 2 * DAY, "conditionId": POL_CID, "type": "MERGE", "size": 100,
                                 "usdcSize": 100, "transactionHash": "0xm"}]  # fmt: skip
    store, sid = _store_with_wallet()
    r = workspace.build(store, reads, sid, POL_SLUG)
    v = r["value"]
    # it bought 100 Yes at 50¢ and 100 No at 45¢, then merged the 100 pairs for $100: out before the result
    assert r["position"][-1]["held"] == {"Yes": 0, "No": 0} and r["moves"][0]["kind"] == "merge"
    assert v["profit_kind"] == "resolved" and v["payout"] == 0 and v["sold_for"] == 100 and v["profit"] == 5
    assert v["exit"]["how"] == "merged" and v["exit"]["t"] == T0 + 2 * DAY and v["exit"]["merged_pairs"] == 100
    assert r["hold"]["to"] == T0 + 2 * DAY and r["hold"]["days"] == 2.0  # held until the merge, not to the result
    assert "Merges and splits are counted" in " ".join(r["coverage"]["notes"])


def test_moves_that_cant_be_read_are_said_and_never_taken_as_held(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 40 * DAY)
    monkeypatch.setattr(workspace, "now", lambda: T0 + 40 * DAY)
    reads = _pol_reads()
    reads.whales._poly.market = PolPoly._m(POL_SLUG, POL_CID, "Abdul El-Sayed (D)", closed=True, prices='["1", "0"]')

    def refused(*a: Any, **k: Any) -> list[dict[str, Any]]:
        raise RuntimeError("venue_unavailable")

    reads.whales._poly._pages = refused  # type: ignore[method-assign]
    store, sid = _store_with_wallet()
    r = workspace.build(store, reads, sid, POL_SLUG)
    assert r["value"]["exit"] == {"how": "not_known"} and not r["coverage"]["moves_read"]
    assert "couldn't be read" in " ".join(r["coverage"]["notes"])
    # a conversion's sides aren't listed: its profit isn't counted
    reads2 = _pol_reads()
    reads2.whales._poly.moves = [{"timestamp": T0 + 2 * DAY, "conditionId": POL_CID, "type": "CONVERSION", "size": 50,
                                  "usdcSize": 0, "transactionHash": "0xc"}]  # fmt: skip
    store2, sid2 = _store_with_wallet()
    r2 = workspace.build(store2, reads2, sid2, POL_SLUG)
    assert r2["coverage"]["converted"] and r2["value"]["profit"] is None


def test_a_politics_scope_reads_tags_past_the_first_batch_and_shows_each_event(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _reads()
    fed = [("0x" + f"{i:064x}", f"fed-{i}") for i in range(60)]  # 60 busier Fed markets first, then the two races
    races = [(POL_CID, POL_SLUG, "Abdul El-Sayed (D)"), ("0x" + "33" * 32, "will-the-republicans-win-michigan", "Mike Rogers (R)")]
    rows = [{"ts": T0 + i, "slug": s, "condition_id": c, "usd": 1000.0 - i, "action": "buy", "outcome": "Yes"} for i, (c, s) in enumerate(fed)]
    rows += [{"ts": T0 + 100, "slug": POL_SLUG, "condition_id": POL_CID, "usd": 50.0, "action": "buy", "outcome": "Yes"},
             {"ts": T0 + 101, "slug": races[1][1], "condition_id": races[1][0], "usd": 40.0, "action": "buy", "outcome": "No"}]
    asked: list[list[str]] = []

    def facts(ids: list[str]) -> dict[str, dict[str, Any]]:
        asked.append(ids)
        out = {c: D.market_facts(PolPoly._m(s, c, "Fed", tags=("Fed Rates", "Trump", "Economy"))) for c, s in fed if c in ids}
        out |= {c: D.market_facts(PolPoly._m(s, c, item)) for c, s, item in races if c in ids}
        return out

    monkeypatch.setattr(reads, "_newest_trades", lambda w, a, b: {"trades": rows, "count": len(rows), "start": a,
                                                                   "complete": True, "read_to": b, "source": "s", "note": ""})
    monkeypatch.setattr(reads, "markets_facts", facts)
    got = reads.wallet_markets(W, T0, T0 + 90 * DAY, "politics", top=20)
    assert [len(a) for a in asked] == [60, 2] and got["markets_looked_at"] == 62  # a second batch for the races
    assert [m["group_item"] for m in got["markets"]] == ["Abdul El-Sayed (D)", "Mike Rogers (R)"] and got["matched"] == 2
    assert got["not_this_type"] == 60 and len(got["skipped_near"]) == 5 and got["skipped_near"][0]["category"] == "Economy"
    e = got["events"][0]
    assert e["event_title"] == "Michigan Senate Election Winner" and e["markets"] == 2 and e["shown"] == 2
    assert [(x["name"], x["bought_in_range"]) for x in e["legs"]] == [("Abdul El-Sayed (D)", {"Yes": 50.0}), ("Mike Rogers (R)", {"No": 40.0})]
    # long-dated BTC still reads one batch of 60 at most, as before
    assert M.BTC_LONG.looks_at == 60 and M.BTC_LONG.near is None


def test_the_pages_politics_tiles_say_how_it_got_out_and_each_event_s_sides() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    js = (Path(__file__).resolve().parent.parent / "signals" / "research" / "static" / "js" / "marketdata.js").as_uri()
    code = f"""
import {{ statusText, ruleChip, eventGroups, eventLegs, legsText, prepMarket, marketAutoSteps }} from '{js}';
const tiles = [
  {{ window_id: 'a', event_slug: 'mi', event_title: 'Michigan Senate', group_item: 'El-Sayed (D)', rule: {{ kind: 'result' }}, shares: {{ Yes: 10, No: 0 }} }},
  {{ window_id: 'b', event_slug: 'mi', event_title: 'Michigan Senate', group_item: 'Rogers (R)', rule: {{ kind: 'result' }}, shares: {{ Yes: 0, No: 5 }} }},
];
const g = eventGroups(tiles)[0];
const events = [{{ event_slug: 'mi', markets: 3, shown: 2, legs: [{{ name: 'El-Sayed (D)', bought_in_range: {{ Yes: 5 }}, shown: true }},
  {{ name: 'Rogers (R)', bought_in_range: {{ No: 4 }}, shown: true }}, {{ name: 'Other', bought_in_range: {{ Yes: 1, No: 1 }}, shown: false }}] }}];
const r = {{ window_id: 'a', title: 'Q', axis: {{ from: 900000, to: 1000000 }}, outcomes: ['Yes', 'No'], prices: {{ Yes: [], No: [] }}, rule: {{ kind: 'result' }}, outside: null,
  trades: [{{ trade_id: 'x', t: 913600, side: 'Yes', action: 'buy', shares: 10, price: 0.5, usd: 5 }}, {{ trade_id: 'y', t: 913700, side: 'No', action: 'buy', shares: 10, price: 0.45, usd: 4.5 }}],
  moves: [{{ t: 920000, kind: 'merge', shares: 10, usd: 10 }}], position: [{{ t: 913700, held: {{ Yes: 10, No: 10 }} }}, {{ t: 920000, held: {{ Yes: 0, No: 0 }} }}],
  value: {{ cost: 9.5, sold_for: 10, profit: 0.5, profit_kind: 'resolved', payout: 0, exit: {{ how: 'merged', t: 920000, merged_pairs: 10, merged_usd: 10 }} }}, result: 'Yes', market_end: 990000 }};
const st = marketAutoSteps(prepMarket(r, null));
console.log(JSON.stringify({{ s: [statusText({{ profit_kind: 'resolved', result: 'No', exit: {{ how: 'merged' }} }}), statusText({{ profit_kind: 'resolved', result: 'No', exit: {{ how: 'held' }} }}),
  statusText({{ profit_kind: 'open', exit: {{ how: 'open' }} }}), statusText({{ profit_kind: 'closed', exit: {{ how: 'sold_and_merged' }} }})],
  chips: [ruleChip({{ kind: 'result' }}), ruleChip({{ kind: 'by_date' }}), ruleChip({{ kind: 'other' }}), ruleChip({{ kind: 'touch_high' }}), ruleChip({{ kind: 'one_of', deadline: '2026-10-01T03:59:00Z' }})],
  strikes: g.strikes, tiles: legsText(eventLegs(g)), sel: eventLegs(g, events), selText: legsText(eventLegs(g, events)), steps: st.map(s => s.title) }}));
"""
    out = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30, check=True)
    got = json.loads(out.stdout)
    assert got["s"] == ["Merged out, resolved No", "Resolved No", "Open", "Sold and merged out"]
    assert got["chips"] == ["Who wins", "By a date", "See its rules", "Any-time high", "One of several outcomes · by 1 Oct"] and got["strikes"] is False
    assert got["tiles"] == "Yes on El-Sayed (D), No on Rogers (R)"
    assert got["sel"]["markets"] == 3 and got["sel"]["shown"] == 2
    assert got["selText"] == "Yes on El-Sayed (D), No on Rogers (R), both sides of Other"
    assert got["steps"] == ["First buy: Yes", "Buys 10 No", "Merges out", "Merged out before the result", "Resolves Yes"]


def test_a_market_plan_without_a_start_reads_back_90_days_so_start_can_tile_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(C, "now", lambda: T0)
    store, sid = _store_with_wallet()
    events: list[dict[str, Any]] = []
    case = C.Case(sid, 1, store, None, events.append, lambda: trace.Sources(["{}"]))
    steps = [{"id": "s", "title": "Read its markets", "source": "Polymarket trades"}]
    assert not case.handle("propose_plan", {"title": "t", "scope": {"wallet": W, "market_type": "politics", "to": "now"}, "steps": steps})[1]
    p = events[-1]
    assert p["market"] == {"id": "politics", "label": "Politics", "unit": "market"}
    assert p["scope"]["from"] == D.iso(T0 - 90 * DAY) and C.scope_ok(p["scope"])
    assert store.scope(sid) == p["scope"]  # what Start tiles: the scope with its defaults


TALKS_RULES = ("On June 22, the first round of U.S.-Iran diplomatic talks in Switzerland concluded, with mediators "
               "reporting progress toward a roadmap for a final deal.\n\nThis market will resolve according to the country "
               "in which the next formal senior-level round of peace talks between representatives of the United States "
               "and Iran begins by September 30, 2026, 11:59 PM ET.")  # fmt: skip
TALKS_EVENT = "Where will the next next round of US-Iran peace talks be...?"


def test_a_leg_of_a_which_or_where_event_is_one_of_several_outcomes_never_by_a_date() -> None:
    def rule(q: str, item: str, **kw: Any) -> dict[str, Any]:
        return M.politics_rule({"question": q, "description": TALKS_RULES, "group_item": item, "event_title": TALKS_EVENT,
                                "neg_risk": True, "end_iso": "2026-10-01T03:59:00Z", **kw})  # fmt: skip

    oman = rule("Will the next diplomatic US-Iran meeting be in Oman by September 30, 2026?", "Oman")
    assert oman["kind"] == "one_of" and oman["deadline"] == "2026-10-01T03:59:00Z"
    assert oman["says"].startswith("Whether Oman is the one of its event's outcomes, decided by 2026-10-01: “This market")
    # the event's "none by <date>" leg is a date market
    none = rule("Will no qualifying diplomatic US-Iran meeting occur by September 30, 2026?", "No Meeting by September 30")
    assert none["kind"] == "by_date"
    # a "who" event where several can be Yes (not negRisk) stays a date market; an election stays "who wins"
    insult = M.politics_rule({"question": "Will Donald Trump publicly insult Ken Paxton by October 31, 2026?",
                              "description": 'This market will resolve to "Yes" if Donald Trump makes any public statement '
                                             "in which he insults the listed individual between market creation and the "
                                             'specified date (ET). Otherwise, this market will resolve to "No".',
                              "group_item": "Ken Paxton", "event_title": "Who will Trump publicly insult by October 31?",
                              "neg_risk": False})  # fmt: skip
    assert insult["kind"] == "by_date"
    race = M.politics_rule({"question": "Will the Democrats win the Michigan Senate race in 2026?", "description": SENATE_RULES,
                            "group_item": "Abdul El-Sayed (D)", "event_title": "Who will win the Michigan Senate race?",
                            "neg_risk": True})  # fmt: skip
    assert race["kind"] == "result"


# ---- the Premier League (session 3: season futures first; match markets only when listed 7+ days ahead) ----

CHAMP_RULES = ("This market will resolve according to the team that wins the 2026-27 English Premier League (EPL) "
               "Championship.\n\nIf at any point it becomes impossible for a listed team to win the 2026-27 English "
               "Premier League (EPL) Championship per the rules of English Premier League (EPL), the corresponding "
               "market will resolve to \"No\".\n\nThe primary resolution source for this market will be official "
               "information from English Premier League (EPL); however, a consensus of credible reporting may also "
               "be used.")  # fmt: skip
SCORER_RULES = ("This market will resolve to the player who scores the most goals during the 2026-27 Premier League "
                "season.\n\nOnly goals scored in Premier League matches will count.\n\nIf multiple players tie for the "
                "top goal scorer, this market will resolve to the player whose last name comes first alphabetically.")
RELEGATED_RULES = ("This market will resolve to \"Yes\" if the listed team is relegated from Premier League at the "
                   "conclusion of the 2026-27 Premier League season. Otherwise, this market will resolve to \"No\".")
UCL_RULES = ("This market will resolve to \"Yes\" if the listed team earns a place in the 2027-28 UEFA Champions League "
             "through the 2026-27 Premier League season or by winning a 2026-27 UEFA club competition. Otherwise, this "
             "market will resolve to \"No\".\n\nIf at any point it becomes impossible for the listed team to qualify, "
             "the market will resolve to \"No\".")  # fmt: skip
MATCH_RULES = ("In the upcoming Premier League game between AFC Bournemouth and Nottingham Forest FC, originally "
               "scheduled for Saturday, November 21, 2026 at 10:00 AM ET (as of creation of the first market related to "
               "the event):\nIf AFC Bournemouth wins, this market will resolve to \"Yes\".\nOtherwise, this market will "
               "resolve to \"No\".")  # fmt: skip
SCORE_RULES = ("In the upcoming Premier League game between Hull City AFC and Brighton & Hove Albion FC, originally "
               "scheduled for Sunday, November 22, 2026 at 9:00 AM ET (as of creation of the first market related to the "
               "event): This market will resolve based on the final score of the Hull City AFC vs. Brighton & Hove Albion "
               "FC match, considering only the result at the end of 90 minutes of regulation plus stoppage time.")
MANAGER_RULES = ("This market will resolve according to the person who is appointed as the next permanent manager of "
                 "Manchester United.  If no permanent manager is appointed by December 31, 2026, 11:59 PM ET, the market "
                 "will resolve to \"Other.\"")  # fmt: skip
PUNISH_RULES = ("This market will resolve to \"Yes\" if the sanctions imposed on Manchester City FC by the independent "
                "Regulatory Commission for the breaches found in the Premier League's proceedings against Manchester "
                "City FC are officially announced by the specified date. Otherwise, it will resolve to \"No\".")
BALLON_RULES = ("This market will resolve to “Yes” if Vinicius Jr wins the 2024 Ballon D’Or. Otherwise, this market "
                "will resolve to “No”.  The primary resolution source for this market is official information from "
                "France Football (https://www.francefootball.fr/).")
EPL_SLUG = "will-arsenal-win-the-2026-27-english-premier-league-epl-championship-20260701200428761"
EPL_CID = "0x" + "44" * 32
EPL_TAGS = [{"label": "EPL"}, {"label": "Soccer"}, {"label": "Sports"}]


def _epl(question: str, rules: str, tags: tuple[str, ...] = ("EPL", "Soccer", "Sports"), **kw: Any) -> dict[str, Any]:
    return {"question": question, "description": rules, "tags": list(tags), **kw}


def test_a_premier_league_market_is_known_by_its_epl_tag_and_its_own_text() -> None:
    assert M.by_id("premier-league") is M.PREMIER_LEAGUE and M.by_id("epl") is M.PREMIER_LEAGUE
    assert M.PREMIER_LEAGUE.outside is None and M.PREMIER_LEAGUE.min_days == 7.0 and M.PREMIER_LEAGUE.looks_at == 180
    pl = M.premier_league_matches
    assert pl(EPL_SLUG, {}) and not pl("btc-updown-15m-1794285000", {})  # no facts yet: not ruled out
    assert pl("x", _epl("Will Arsenal win the 2026-27 English Premier League (EPL) Championship?", CHAMP_RULES))
    assert pl("x", _epl("Will Arsenal be relegated from the 2026-27 Premier League?", RELEGATED_RULES))
    # a Champions League place: its question doesn't name the league, its rules do
    assert pl("x", _epl("Will Arsenal qualify for the 2027-28 UEFA Champions League?", UCL_RULES))
    # a club's manager names the club, not the league; a national team's manager isn't the league
    assert pl("x", _epl("Will Darren Fletcher be appointed as manager of Manchester United?", MANAGER_RULES,
                        tags=("Sports", "man united", "EPL", "Soccer")))  # fmt: skip
    assert not pl("x", _epl("Will Thomas Tuchel be the next England manager?", "Resolves to the next permanent manager."))
    # Polymarket put the EPL tag on the Ballon d'Or, Euro 2024 and the FA Cup: their own text doesn't name the league
    ballon = _epl("Will Vinicius Jr win the Ballon D’Or?", BALLON_RULES, event_title="Ballon d'Or Winner")
    assert not pl("x", ballon) and M.premier_league_near(ballon)
    assert not pl("x", _epl("Will England win the 2024 Euros?", "Resolves Yes if England wins Euro 2024.", ("Sports", "EPL")))
    assert not pl("x", _epl("Will Preston North End win the 2024-25 FA Cup?", "Resolves to the winner of the FA Cup.",
                            ("Sports", "Soccer", "FA Cup", "EPL")))  # fmt: skip
    # an older match market doesn't name the league: its "Premier League" tag or its epl-<home>-<away>-<date> slug do
    old_match = _epl("Will Arsenal FC win on 2026-10-10?", "In the upcoming game, scheduled for October 10, 2026 If "
                     "Arsenal FC wins, this market will resolve to \"Yes\".", slug="epl-ars-lee-2026-10-10-ars")  # fmt: skip
    assert pl("x", old_match) and pl("x", old_match | {"slug": "x", "tags": ["EPL", "Premier League"]})
    assert M.premier_league_rule(old_match)["quote"] == "If Arsenal FC wins, this market will resolve to \"Yes\"."
    # the league's name without the tag (cricket's Indian Premier League), or another country's league, isn't it
    assert not pl("x", _epl("Will Mumbai win the Indian Premier League?", "The Indian Premier League final.", ("Cricket",)))
    assert not pl("x", _epl("Will Zenit win the Russian Premier League?", "The Russian Premier League table."))
    assert not M.premier_league_near(_epl("Will Mumbai win?", "x", ("Cricket",)))
    # the facts the service reads carry Gamma's tag labels; the type is found, not politics or BTC
    f = D.market_facts({"slug": EPL_SLUG, "conditionId": EPL_CID, "question": "Will Arsenal win the 2026-27 English "
                        "Premier League (EPL) Championship?", "outcomes": '["Yes", "No"]', "clobTokenIds": '["a", "b"]',
                        "negRisk": True, "groupItemTitle": "Arsenal", "description": CHAMP_RULES, "tags": EPL_TAGS})
    assert M.of_market(EPL_SLUG, f) is M.PREMIER_LEAGUE and f["category"] != "Politics"
    assert M.premier_league_hint(EPL_SLUG) and M.premier_league_hint("epl-bou-not-2026-11-21-bou")
    assert not M.premier_league_hint("will-arsenal-qualify-for-the-2027-28-uefa-champions-league")
    assert not M.premier_league_hint("will-the-sepl-ban-pass")  # a whole word, not a substring
    # the types before it have no hint, so their reads are as before
    assert all(t.hint is None for t in M.TYPES if t is not M.PREMIER_LEAGUE)


def test_what_resolves_a_premier_league_market_is_read_from_its_own_rules() -> None:
    r = M.premier_league_rule
    champ = r(_epl("Will Arsenal win the 2026-27 English Premier League (EPL) Championship?", CHAMP_RULES,
                   group_item="Arsenal", neg_risk=True, end_iso="2027-06-15T00:00:00Z"))  # fmt: skip
    assert champ["kind"] == "one_of" and champ["ends_early"] and champ["tie"] is None
    assert champ["source"] == "official information from English Premier League (EPL)"  # not "…; however, a consensus"
    assert champ["says"].startswith("Whether Arsenal is the one of its event's outcomes: “This market will resolve according")
    scorer = r(_epl("Will Erling Haaland (Man City) be the top goalscorer of the 2026-27 Premier League season?",
                    SCORER_RULES, group_item="Erling Haaland", neg_risk=True))  # fmt: skip
    assert scorer["kind"] == "one_of" and not scorer["ends_early"] and "alphabetically" in scorer["tie"]
    rel = r(_epl("Will Arsenal be relegated from the 2026-27 Premier League?", RELEGATED_RULES, group_item="Arsenal"))
    assert rel["kind"] == "season" and rel["says"].startswith("At the end of the season: “This market will resolve to")
    ucl = r(_epl("Will Arsenal qualify for the 2027-28 UEFA Champions League?", UCL_RULES, group_item="Arsenal"))
    assert ucl["kind"] == "season" and ucl["ends_early"]
    old = r(_epl("Will Southampton be relegated?", "This market will resolve to “Yes” if Southampton finishes in the "
                 "bottom 3 of the 2024-25 Premier League season."))  # fmt: skip
    assert old["kind"] == "season"
    win = r(_epl("Will AFC Bournemouth win on 2026-11-21?", MATCH_RULES, slug="epl-bou-not-2026-11-21-bou",
                 group_item="AFC Bournemouth", neg_risk=True))  # fmt: skip
    assert win["kind"] == "match" and win["quote"] == "If AFC Bournemouth wins, this market will resolve to \"Yes\"."
    score = r(_epl("Exact Score: Hull City AFC 0 - 0 Brighton & Hove Albion FC?", SCORE_RULES,
                   slug="epl-hul-bri-2026-11-22-exact-score-0-0"))  # fmt: skip
    assert score["kind"] == "match" and "Hull City AFC vs. Brighton & Hove Albion FC match" in score["quote"]  # not cut at "vs."
    mgr = r(_epl("Will Darren Fletcher be appointed as manager of Manchester United?", MANAGER_RULES,
                 group_item="Darren Fletcher", neg_risk=True))  # fmt: skip
    assert mgr["kind"] == "one_of"
    pun = r(_epl("Manchester City punishment announced by October 9?", PUNISH_RULES, group_item="October 9"))
    assert pun["kind"] == "by_date"
    bucket = r(_epl("Will Manchester City be deducted 0 Premier League points?", "This market will resolve according to "
                    "the total number of Premier League points Manchester City FC is deducted.", group_item="0",
                    neg_risk=True))  # fmt: skip
    assert bucket["kind"] == "one_of" and bucket["says"].startswith("Whether “Will Manchester City be deducted 0")
    # its section is in the agent's instructions, with no example numbers, and never claims a result, a table or news
    import re

    assert M.PREMIER_LEAGUE_PROMPT in A.SYSTEM and set(re.findall(r"\d+", M.PREMIER_LEAGUE_PROMPT)) <= {"0", "1"}
    assert "never say a trade followed a match" in M.PREMIER_LEAGUE_PROMPT and "no league table" in M.PREMIER_LEAGUE_PROMPT


class EplPoly(Poly):
    """A Premier League wallet: Arsenal for the title (negRisk), still held."""

    def __init__(self) -> None:
        super().__init__()
        self.market = {"slug": EPL_SLUG, "conditionId": EPL_CID, "description": CHAMP_RULES,
                       "question": "Will Arsenal win the 2026-27 English Premier League (EPL) Championship?",
                       "outcomes": '["Yes", "No"]', "clobTokenIds": '["tY", "tN"]', "outcomePrices": '["0.25", "0.75"]',
                       "closed": False, "negRisk": True, "groupItemTitle": "Arsenal", "tags": EPL_TAGS,
                       "startDate": "2026-07-01T20:04:28Z", "endDate": "2027-06-15T00:00:00Z",
                       "events": [{"slug": "epl-2027-champion", "title": "English Premier League Winner"}]}  # fmt: skip
        self.fills = [_act(T0, "buy", "Yes", 0.2, 100, "0xa") | {"conditionId": EPL_CID, "slug": EPL_SLUG},
                      _act(T0 + 9 * DAY, "buy", "Yes", 0.22, 50, "0xb") | {"conditionId": EPL_CID, "slug": EPL_SLUG}]

    def _pages(self, path: str, params: dict[str, Any], limit: int, offset: int, page: int) -> list[dict[str, Any]]:
        return []


def test_a_premier_league_replay_has_no_outside_line_and_is_open_at_todays_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: T0 + 10 * DAY)
    monkeypatch.setattr(workspace, "now", lambda: T0 + 10 * DAY)
    store, sid = _store_with_wallet()
    reads = _reads()
    reads.whales._poly = EplPoly()
    r = workspace.build(store, reads, sid, EPL_SLUG)
    assert r["market_type"] == "premier-league" and r["outside"] is None and r["rule"]["kind"] == "one_of"
    assert r["group_item"] == "Arsenal" and r["neg_risk"] and r["rule"]["ends_early"]
    cov = r["coverage"]
    assert cov["outside"] is None and "tied to a match result or news" in " ".join(cov["notes"])
    assert r["value"]["profit_kind"] == "open" and r["value"]["exit"] == {"how": "open"}
    assert store.summaries(sid)[0]["coverage"]["outside_none"].startswith("No outside series for Premier League")


def test_a_premier_league_scope_reads_slugs_naming_the_league_first_and_tiles_the_most_money(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _reads()
    other = [("0x" + f"{i:064x}", f"nba-game-{i}") for i in range(200)]  # 200 busier markets that aren't the league
    ucl = ("0x" + "55" * 32, "will-arsenal-qualify-for-the-2027-28-uefa-champions-league")  # its slug doesn't say
    clubs = [("0x" + f"{0xE0 + i:064x}", f"will-club-{i}-win-the-2026-27-english-premier-league-epl") for i in range(3)]
    ballon = ("0x" + "66" * 32, "ballon-dor-epl-2026")
    rows = [{"ts": T0 + i, "slug": s, "condition_id": c, "usd": 1000.0 - i, "action": "buy", "outcome": "Yes"}
            for i, (c, s) in enumerate(other)]  # fmt: skip
    rows += [{"ts": T0 + 300, "slug": ucl[1], "condition_id": ucl[0], "usd": 950.5, "action": "buy", "outcome": "No"},
             {"ts": T0 + 301, "slug": ballon[1], "condition_id": ballon[0], "usd": 30.0, "action": "buy", "outcome": "Yes"}]
    rows += [{"ts": T0 + 310 + i, "slug": s, "condition_id": c, "usd": 20.0 - i, "action": "buy", "outcome": "Yes"}
             for i, (c, s) in enumerate(clubs)]  # fmt: skip
    base = {"outcomes": '["Yes", "No"]', "clobTokenIds": '["a", "b"]', "startDate": "2026-07-01T00:00:00Z",
            "endDate": "2027-06-15T00:00:00Z"}
    gamma = {c: base | {"slug": s, "conditionId": c, "question": f"Will {s} win?", "description": "An NBA game.",
                        "tags": [{"label": "NBA"}, {"label": "Sports"}]} for c, s in other}  # fmt: skip
    for i, (c, s) in enumerate(clubs):
        gamma[c] = base | {"slug": s, "conditionId": c, "description": CHAMP_RULES, "negRisk": True, "tags": EPL_TAGS,
                           "question": f"Will Club {i} win the 2026-27 English Premier League (EPL) Championship?",
                           "groupItemTitle": f"Club {i}",
                           "events": [{"slug": "epl-2027-champion", "title": "English Premier League Winner"}]}  # fmt: skip
    gamma[ucl[0]] = base | {"slug": ucl[1], "conditionId": ucl[0], "description": UCL_RULES, "tags": EPL_TAGS,
                            "question": "Will Arsenal qualify for the 2027-28 UEFA Champions League?",
                            "groupItemTitle": "Arsenal", "events": [{"slug": "ucl-places", "title": "UCL places"}]}
    gamma[ballon[0]] = base | {"slug": ballon[1], "conditionId": ballon[0], "description": BALLON_RULES,
                               "question": "Will Vinicius Jr win the Ballon D’Or?", "tags": EPL_TAGS}
    asked: list[list[str]] = []

    def facts(ids: list[str]) -> dict[str, dict[str, Any]]:
        asked.append(ids)
        return {c: D.market_facts(gamma[c]) for c in ids if c in gamma}

    monkeypatch.setattr(reads, "_newest_trades", lambda w, a, b: {"trades": rows, "count": len(rows), "start": a,
                                                                   "complete": True, "read_to": b, "source": "s", "note": ""})
    monkeypatch.setattr(reads, "markets_facts", facts)
    got = reads.wallet_markets(W, T0, T0 + 90 * DAY, "premier-league", top=2)
    # the clubs (their slugs name the league) are 203rd to 205th by money, past the cap of 180 by money alone: they're
    # read in the first batch, before the 200 busier markets
    assert {c for c, _ in clubs} <= set(asked[0])
    # with 2 kept, it reads on while a bigger market could still outrank them, and finds the Champions League place
    # (its slug doesn't say): the tiles are the most money first, never the order read
    assert [m["slug"] for m in got["markets"]] == [ucl[1], clubs[0][1]] and got["matched"] == 4
    assert got["markets_looked_at"] == M.PREMIER_LEAGUE.looks_at
    assert [x["question"] for x in got["skipped_near"]] == ["Will Vinicius Jr win the Ballon D’Or?"]
    assert got["not_this_type"] == 176  # 180 read: 4 kept, the Ballon d'Or and 175 NBA markets left out
    e = got["events"][0]
    assert e["event_title"] == "English Premier League Winner" and e["markets"] == 3 and e["shown"] == 1
    assert "whose slugs name the league first" in got["note"]


def test_the_pages_premier_league_chips_say_end_of_the_season_and_one_match() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    js = (Path(__file__).resolve().parent.parent / "signals" / "research" / "static" / "js" / "marketdata.js").as_uri()
    code = (f"import {{ ruleChip }} from '{js}';\n"
            "console.log(JSON.stringify([ruleChip({ kind: 'season' }), ruleChip({ kind: 'match' }),"
            " ruleChip({ kind: 'one_of', deadline: '2027-06-15T00:00:00Z' })]));")  # fmt: skip
    out = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(out.stdout) == ["End of the season", "One match", "One of several outcomes · by 15 Jun"]
