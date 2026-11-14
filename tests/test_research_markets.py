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
    assert got["available"] and got["step"] == "1 hour" and len(got["points"]) in (60 * 24, 60 * 24 + 1)
    assert got["highest"]["high"] == max(h for _, h, _ in got["ranges"]) and got["lowest"]["low"] == got["ranges"][0][2]
    calls = r.web.calls  # type: ignore[attr-defined]
    r.outside_prices("binance", T0 + DAY, T0 + 50 * DAY)
    assert r.web.calls == calls  # type: ignore[attr-defined]  # ended 1,000-hour blocks are read once
    assert r.outside_prices("binance", T0, T0 + 200 * DAY)["step"] == "1 day"


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
    assert r["value"]["profit"] is None and r["coverage"]["bought_before_read"] and not r["coverage"]["fills_complete"]
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
               "bought_before_read": False, "chainlink": "none", "book": False, "outage": False}  # fmt: skip
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
