"""The research agent (signals/research): its reads, its number check, its loop (with a scripted model), the server."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

os.environ.setdefault("RESEARCH_STORE_DIR", tempfile.mkdtemp(prefix="research-test-"))

from signals.research import agent as A  # noqa: E402
from signals.research import data as D  # noqa: E402
from signals.research import tools as T  # noqa: E402
from signals.research import trace  # noqa: E402
from signals.research.store import Store  # noqa: E402

W = "0x" + "ab" * 20
SLUG = "btc-updown-15m-1794285000"

# ---- the number check ----


def test_numbers_trace_with_rounding_units_and_prices() -> None:
    s = trace.Sources(['{"pnl": 40055.41, "price": 0.53, "count": 4173, "loss": -24.892}'])
    assert trace.check("It made $40.1k, paid 53¢ (53%), over 4,173 trades; lost −$24.89.", s)["ok"]
    assert trace.check("It made $40,055.41.", s)["ok"]
    out = trace.check("It made $41.2k and paid 61¢.", s)
    assert out["unmatched"] == ["$41.2k", "61¢"]


def test_times_dates_wallets_slugs_and_list_numbers_are_not_checked() -> None:
    s = trace.Sources(["{}"])
    text = (f"1. At 14:02 UTC on 2026-11-09 (Nov 9, 9 Nov) {W} and 0x91…76 traded {SLUG}.\n"
            "2. Then 2026-11-10T04:30:00Z.")  # fmt: skip
    assert trace.check(text, s) == {"ok": True, "checked": 0, "unmatched": []}


def test_sources_leave_out_the_agents_own_words_and_code() -> None:
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "Since 8 Nov, 15-minute windows"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Profit 999"},
            {"type": "server_tool_use", "id": "s1", "name": "code_execution", "input": {"code": "x = 777"}},
            {"type": "code_execution_tool_result", "tool_use_id": "s1", "content": {"stdout": "profit=12.5"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": '{"n": 31}'}]},
    ]  # fmt: skip
    s = A.sources_of(msgs, system="")
    assert trace.check("15 minutes, 12.5 profit, 31 trades", s)["ok"]
    assert trace.check("999", s)["unmatched"] == ["999"] and trace.check("777", s)["unmatched"] == ["777"]


# ---- reads ----


def _trade(ts: int, slug: str = SLUG, tx: str = "0x1", price: float = 0.4) -> Any:
    return SimpleNamespace(at=datetime.fromtimestamp(ts, UTC), slug=slug, market=f"0xc:{0}", outcome="Up", token="9",
                           action="buy", price=price, size=5.0, usd=2.0, trade_id=tx)  # fmt: skip


class Whales019:
    """uselayer 0.19's reads: ``trades_between`` (limit per read, oldest first)."""

    def __init__(self, trades: list[Any]) -> None:
        self.trades, self.calls = trades, []

    def trades_between(self, w: str, a: int, b: int, *, limit: int) -> list[Any]:
        self.calls.append(a)
        return [t for t in self.trades if a <= int(t.at.timestamp()) <= b][:limit]


def test_wallet_trades_reads_on_after_a_full_page_and_drops_the_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "PAGE", 3)
    trades = [_trade(100 + i, tx=f"0x{i}") for i in range(7)] + [_trade(105, slug="eth-updown-15m-1", tx="0xe")]
    wh = Whales019(trades)
    out = D.Reads(wh).wallet_trades(W, 100, 200)
    assert wh.calls == [100, 102, 104, 106]  # each read starts at the last second of the one before
    assert out["count"] == 7 and out["complete"] and out["windows"] == 1  # the ETH trade filtered out
    assert [r["ts"] for r in out["trades"]] == sorted(r["ts"] for r in out["trades"])


def test_wallet_trades_says_where_it_stopped_when_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "PAGE", 2)
    monkeypatch.setattr(D, "MAX_TRADES", 4)
    out = D.Reads(Whales019([_trade(100 + i, tx=f"0x{i}") for i in range(10)])).wallet_trades(W, 100, 200)
    assert not out["complete"] and out["read_to"] == 103 and "Partial" in out["note"]


def test_wallet_trades_rows_from_the_sdk() -> None:
    from uselayer.whales import WhaleTrade

    t = WhaleTrade(venue="polymarket", trader=W, name=None, market="0xc:1", side="yes", action="sell", price=0.6,
                   size=10.0, usd=6.0, at=datetime.fromtimestamp(100, UTC), trade_id="0xt", outcome="Down", token="7",
                   slug=SLUG, event_slug=SLUG)  # fmt: skip
    out = D.Reads(Whales019([t])).wallet_trades(W, 0, 200)
    row = dict(out["trades"][0])
    assert row.pop("id") == D.trade_id("0xt", "7", "sell", 0.6, 10.0, 100) == D.trade_id("0xt", "7", "sell", "0.60", 10, "100")
    assert row == {"ts": 100, "slug": SLUG, "condition_id": "0xc", "outcome": "Down", "outcome_index": 1,
                   "token": "7", "action": "sell", "price": 0.6, "size": 10.0, "usd": 6.0, "tx": "0xt"}  # fmt: skip


def test_an_sdk_warning_marks_the_history_cut_short() -> None:
    import logging

    class Warns(Whales019):
        def trades_between(self, w: str, a: int, b: int, *, limit: int) -> list[Any]:
            logging.getLogger("uselayer").warning("uselayer: %s has over 5,000 trades at %d; the rest are skipped", w, a)
            return super().trades_between(w, a, b, limit=limit)

    class FullPage(Whales019):  # 0.19.1 warns on every full page; reading on handles it
        def trades_between(self, w: str, a: int, b: int, *, limit: int) -> list[Any]:
            got = super().trades_between(w, a, b, limit=limit)
            if len(got) == limit:
                logging.getLogger("uselayer").warning("uselayer: stopped at the limit of %d trades for %s", limit, w)
            return got

    old = D.PAGE
    D.PAGE = 2
    try:
        full = D.Reads(FullPage([_trade(100 + i, tx=f"0x{i}") for i in range(5)])).wallet_trades(W, 100, 200)
    finally:
        D.PAGE = old
    assert full["complete"] and full["count"] == 5 and "sdk_warnings" not in full
    out = D.Reads(Warns([_trade(100)])).wallet_trades(W, 100, 200)
    assert not out["complete"] and "cut short" in out["note"]
    assert out["sdk_warnings"] == [f"uselayer: {W} has over 5,000 trades at 100; the rest are skipped"]
    assert "sdk_warnings" not in D.Reads(Whales019([_trade(100)])).wallet_trades(W, 100, 200)
    logging.getLogger("uselayer").warning("outside any read")  # no handler left behind
    assert not any(type(h).__name__ == "Catch" for h in logging.getLogger("uselayer").handlers)


def test_wallet_trades_refuses_a_bad_wallet() -> None:
    with pytest.raises(D.ReadError):
        D.Reads(SimpleNamespace()).wallet_trades("bob", 0, 1)


def _market() -> dict[str, Any]:
    return {"slug": SLUG, "conditionId": "0xc", "question": "Bitcoin Up or Down", "closed": True,
            "outcomes": '["Up", "Down"]', "clobTokenIds": '["1", "2"]', "outcomePrices": '["0", "1"]',
            "resolutionSource": "https://data.chain.link/streams/btc-usd-twap-60s-streams",
            "events": [{"eventMetadata": {"priceToBeat": 74719.68, "finalPrice": 74620.4}}]}  # fmt: skip


def test_window_facts_prices_trades_and_coverage() -> None:
    poly = SimpleNamespace(
        _profiles="https://gamma", _list=lambda url, p: [_market()] if p["closed"] == "true" else [],
        markets=lambda ids, closed: [_market()],
        market_trades=lambda cid, limit: [{"timestamp": 1794285010, "proxyWallet": W, "outcome": "Up", "side": "BUY",
                                           "price": "0.5", "size": "2", "transactionHash": "0x1"}],
    )  # fmt: skip
    wh = SimpleNamespace(_poly=poly, price_history=lambda tok, a, b: [(1794285000, 0.5), (1794285060, 0.4), (1794285240, 0.3)])
    w = D.Reads(wh).window(SLUG)
    assert (w["start"], w["end"], w["result"], w["price_to_beat"]) == (1794285000, 1794285900, "Down", 74719.68)
    assert w["tokens"] == {"Up": "1", "Down": "2"} and w["prices"]["Up"][0] == [1794285000, 0.5]
    assert w["coverage"]["largest_price_gap_s"] == 180 and w["coverage"]["price_step_s"] == 180
    assert w["coverage"]["trades_complete"] and not w["book"]["available"]
    assert w["book"]["status"] == "not_processed" and "isn't processed yet" in w["book"]["why"]  # after 2 Nov 17:00


LAYER_WINDOW = {
    "schema": "btc-15m-window-v1", "slug": SLUG, "start": 1794285000000, "end": 1794285900000,
    "startPrice": {"polymarket": 74719.68, "chainlinkAtStart": 74719.5, "chainlinkAvg60": 74720.1},
    "endPrice": {"polymarket": 74620.4, "chainlinkAtEnd": 74620.0, "chainlinkAvg60": 74621.0},
    "result": {"polymarket": "Down", "fromChainlink": "Down", "resolutionSource": "chainlink"},
    "columns": {"prices": ["receive_ms", "up_bid", "up_ask", "down_bid", "down_ask"],
                "book": ["unix_s", "up_bids", "up_asks", "down_bids", "down_asks"],
                "trades": ["venue_unix_s", "stream_receive_ms", "outcome", "side", "price", "size", "taker_wallet",
                           "transaction_hash"]},
    "prices": [[1794285000500, 0.49, 0.51, 0.49, 0.51]],
    "book": [[1794285000, [[0.49, 100]], [[0.51, 80]], [[0.49, 90]], [[0.51, 70]]]],
    "trades": [[1794285010, 1794285008000, "Up", "BUY", 0.51, 20, W, "0xt"]],
    "chainlink": [[1794285000, 74719.5]], "binance": [[1794285000, 74827.09]],
    "coverage": {"usable": True, "reasons": [], "trades": {"dataApi": 364, "onStream": 246, "pct": 67.6},
                 "book": {"secondsWithoutBook": 3, "of": 900, "lost": [  # as Layer's recording writes them
                     {"from": "2026-11-09T04:45:14.181Z", "to": "2026-11-09T04:45:16.613Z", "why": "reconnected"}]}},
}  # fmt: skip


def test_a_recorded_window_in_the_tools_shape() -> None:
    from signals.research import recorded

    s = recorded.shaped(LAYER_WINDOW)
    assert s["prices"] == {"Up": [[1794285000, 0.5]], "Down": [[1794285000, 0.5]]}
    assert s["trades"] == [{"ts": 1794285010, "wallet": W, "outcome": "Up", "action": "buy", "price": 0.51,
                            "size": 20, "tx": "0xt", "stream_ms": 1794285008000}]  # fmt: skip
    assert s["book"]["available"] and s["book"]["rows"][0]["up_asks"] == [[0.51, 80]]
    assert (s["result"], s["chainlink_at_start"], s["coverage"]["book"]["secondsWithoutBook"]) == ("Down", 74719.5, 3)


def test_r2_signed_get_and_the_window_reading_it() -> None:
    import gzip

    from signals.research import recorded

    asked: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req)
        if req.url.path.endswith(f"{SLUG}.json.gz"):
            return httpx.Response(200, content=gzip.compress(json.dumps(LAYER_WINDOW).encode()))
        return httpx.Response(404)

    r2 = recorded.R2("acct", "kid", "secret", web=_web(handler), now=lambda: datetime(2026, 11, 10, 5, 0, tzinfo=UTC))
    read = recorded.reader(r2)
    poly = SimpleNamespace(_profiles="g", _list=lambda url, p: [_market()] if p["closed"] == "true" else [],
                           market_trades=lambda *a, **k: pytest.fail("a recorded window reads no API trades"))  # fmt: skip
    w = D.Reads(SimpleNamespace(_poly=poly), recorded_window=read).window(SLUG)
    req = asked[0]
    assert req.url.host == "acct.r2.cloudflarestorage.com"
    assert req.url.path == f"/layer-history/derived/windows/btc-15m/2026/11/10/{SLUG}.json.gz"
    auth = req.headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=kid/20261110/auto/s3/aws4_request")
    assert "secret" not in auth and req.headers["x-amz-date"] == "20261110T050000Z"
    assert w["source"].startswith("Layer recording") and w["book"]["available"] and w["chainlink"]
    assert w["start"] == 1794285000 and w["recording_notes"] == []
    assert read("btc-updown-15m-1794286800") is None  # not cached yet: the API instead
    assert recorded.reader(None)(SLUG) is None


def test_recording_notes() -> None:
    assert "no order book" in D.recording_notes(1_793_000_000, 1_793_000_900)[0]
    assert any("overloaded" in n for n in D.recording_notes(1_794_080_000, 1_794_080_900))
    assert D.recording_notes(1_794_300_000, 1_794_300_900) == []


def _web(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_binance_seconds_and_a_refusing_location() -> None:
    ok = _web(lambda r: httpx.Response(200, json=[[1794285000000, "1", "1", "1", "74827.09", "0"]]))
    out = D.Reads(None, ok).outside_prices("binance", 1794285000, 1794285900)
    assert out["available"] and out["points"] == [[1794285000, 74827.09]] and out["step"] == "1 second"
    blocked = _web(lambda r: httpx.Response(451, json={"code": 0, "msg": "restricted location"}))
    out = D.Reads(None, blocked).outside_prices("binance", 1794285000, 1794285900)
    assert not out["available"] and "this server's location (HTTP 451)" in out["why"]


def test_chainlink_says_why_it_isnt_there() -> None:
    reads = D.Reads(None, _web(lambda r: httpx.Response(500)))
    before = reads.outside_prices("chainlink", 1794285000, 1794285900)  # 10 Nov 04:30, before recording began
    assert not before["available"] and "wasn't recorded before 10 Nov 05:27 UTC" in before["why"]
    after = reads.outside_prices("chainlink", 1794290000, 1794290900)
    assert "can't be read from here right now" in after["why"] and "price_to_beat" in after["why"]


def test_raw_chainlink_from_layers_live_feed_recording() -> None:
    import brotli

    from signals.research import recorded

    def line(c: str, payload: dict[str, Any]) -> str:
        return json.dumps({"t": 0, "c": c, "m": {"topic": "crypto_prices_chainlink", "payload": payload}})

    s = LATE  # a file starting at the window's start
    body = "\n".join([
        json.dumps({"t": 0, "ev": "file", "venue": "crypto"}),
        line("rh1", {"symbol": "btc/usd", "data": [{"timestamp": (s + 1) * 1000, "value": 1.0},
                                                    {"timestamp": (s + 2) * 1000, "value": 2.0}]}),
        line("rt1", {"symbol": "btc/usd", "timestamp": (s + 2) * 1000 + 400, "value": 2.5}),  # live wins its second
        line("rt1", {"symbol": "btcusdt", "timestamp": (s + 2) * 1000, "value": 9.0}),
    ]).encode()  # fmt: skip
    day = "2026/11/10"
    key = f"raw/ticks/crypto/{day}/polymarket-rtds-2026-11-10T06-{s * 1000}.jsonl.br"
    old = f"raw/ticks/crypto/{day}/polymarket-rtds-2026-11-10T03-{(s - 9000) * 1000}.jsonl.br"  # far too early

    class FakeR2:
        def __init__(self) -> None:
            self.got: list[str] = []

        def keys(self, prefix: str, limit: int) -> list[str]:
            return [old, key] if prefix.endswith(day + "/") else []

        def get(self, k: str) -> bytes:
            self.got.append(k)
            return brotli.compress(body)

    r2 = FakeR2()
    raw = recorded.RawCrypto(r2)  # type: ignore[arg-type]
    assert raw.prices("btc/usd", s, s + 900) == [[s + 1, 1.0], [s + 2, 2.5]]
    assert raw.prices("btcusdt", s, s + 900) == [[s + 2, 9.0]]
    assert r2.got == [key]  # the early file isn't read, and the file is read once for both symbols
    assert raw.prices("btc/usd", 1_793_000_000, 1_793_000_900) is None  # before the recording began


def test_times_parse() -> None:
    assert D.unix("2026-11-10T04:30:00Z") == D.unix("2026-11-10T04:30:00") == D.unix("1794285000") == 1794285000
    with pytest.raises(D.ReadError):
        D.unix("yesterday")


# ---- the case file: a window's replay, built by the server ----

LATE = 1794290400  # 10 Nov 06:00 UTC: after Chainlink recording began
LATE_SLUG = f"btc-updown-15m-{LATE}"


def _recorded_read(start: int = LATE) -> dict[str, Any]:
    from signals.research import recorded

    j = json.loads(json.dumps(LAYER_WINDOW).replace("1794285", str(start)[:7]))
    j["prices"] = [[(start + 2) * 1000, 0.40, 0.42, 0.57, 0.59], [(start + 10) * 1000, 0.60, 0.62, 0.37, 0.39]]
    j["trades"] = [[start + 12, (start + 11) * 1000 + 500, "Up", "BUY", 0.62, 10, "0xother", "0xa"],
                   [start + 14, (start + 3) * 1000, "Up", "BUY", 0.40, 5, "0xother", "0xb"]]  # fmt: skip
    j["chainlink"] = [[start, 74719.5], [start + 1, 74720.0]]
    j["binance"] = [[start - 300, 74800.0], [start, 74827.09]]  # recordings begin 5 minutes before the start
    s = recorded.shaped(j)
    return {"slug": f"btc-updown-15m-{start}", "start": start, "end": start + 900, "title": "BTC", **s}


def _wallet_fill(tx: str, ts: int, price: float, size: float, outcome: str = "Up", action: str = "buy") -> dict[str, Any]:
    r = {"ts": ts, "slug": f"btc-updown-15m-{LATE}", "token": "1" if outcome == "Up" else "2", "outcome": outcome,
         "action": action, "price": price, "size": size, "usd": round(price * size, 2), "tx": tx}  # fmt: skip
    return r | {"id": D.trade_id(tx, r["token"], action, price, size, ts)}


def test_a_window_replay_from_a_recording() -> None:
    from signals.research import workspace as WS

    fills = [_wallet_fill("0xa", LATE + 12, 0.62, 10), _wallet_fill("0xb", LATE + 14, 0.41, 5),
             _wallet_fill("0xc", LATE + 20, 0.70, 4, action="sell"), _wallet_fill("0xd", LATE + 30, 0.38, 6, "Down")]  # fmt: skip
    r = WS.ready(_recorded_read(), fills, None, {"jump": {"t": LATE + 10, "side": "Up"}})
    assert r["window_id"] == LATE_SLUG and r["chainlink"] == [{"t": LATE, "p": 74719.5}, {"t": LATE + 1, "p": 74720.0}]
    up = {p["t"]: p for p in r["up"]}
    assert LATE + 1 not in up and up[LATE + 2]["ask"] == 0.42 and up[LATE + 9]["ask"] == 0.42 and up[LATE + 10]["ask"] == 0.62
    assert r["minute_fallback"] is None and r["tags"]["jump"]["side"] == "Up"
    t = {x["trade_id"]: x for x in r["trades"]}
    assert t[fills[0]["id"]]["paid_ask"] is True  # 62¢ = the ask just before it reached the stream
    assert t[fills[1]["id"]]["paid_ask"] is False  # 41¢ when the ask was 42¢: it rested
    assert t[fills[2]["id"]]["paid_ask"] is None and t[fills[3]["id"]]["paid_ask"] is None  # a sell; not on the tape
    assert r["position"] == [{"t": LATE + 12, "up": 10, "down": 0}, {"t": LATE + 14, "up": 15, "down": 0},
                             {"t": LATE + 20, "up": 11, "down": 0}, {"t": LATE + 30, "up": 11, "down": 6}]  # fmt: skip
    s = WS.summary(r)
    assert s["entries"][0] == {"t": LATE + 12, "side": "Up", "action": "buy"} and s["first_entry_s"] == 12
    assert s["result"] == "Down" and s["payout"] == 6 and s["cost"] == round(6.2 + 2.05 + 2.28, 2)
    assert s["profit"] == round(6 + 2.8 - (6.2 + 2.05 + 2.28), 2) and s["coverage"]["chainlink"] == "full"
    # cost is what the fills say was paid (Polymarket's usd), not shares × the rounded price
    r["trades"][0]["usd"] = 6.31
    assert WS.summary(r)["cost"] == round(6.31 + 2.05 + 2.28, 2)
    cov = r["coverage"]
    assert cov["missing_seconds"] == [[1794199514, 2.4]]
    assert cov["lost"][0]["why"] == "The recorder's connection dropped and reconnected"
    assert [t["liquidity"] for t in r["trades"]] == ["taker", "maker", None, None]
    assert cov["market_trades"] == {"recorded": 246, "polymarket": 364, "pct": 67.6}


def test_fills_before_the_window_opens() -> None:
    from signals.research import workspace as WS

    early = _wallet_fill("0xe", LATE - 47, 0.48, 3)
    r = WS.ready(_recorded_read(), [early, _wallet_fill("0xa", LATE + 12, 0.62, 10)], None)
    assert r["axis"] == {"from": LATE - 47 - WS.PAD_S, "to": LATE + 900 + WS.AFTER_S}
    assert [t["pre_open"] for t in r["trades"]] == [True, False]
    assert r["coverage"]["pre_open_entries"] == {"fills": 1, "first_s_before": 47, "before_axis": 0}
    assert any("before the recording of this window's book begins" in n for n in r["coverage"]["notes"])
    assert r["up"][0]["t"] == LATE + 2  # the book exists from its first recorded change
    way_early = _wallet_fill("0xf", LATE - 7_200, 0.45, 2)
    r = WS.ready(_recorded_read(), [way_early], None)
    assert r["axis"]["from"] == LATE - WS.PRE_OPEN_MAX_S - WS.PAD_S
    assert r["coverage"]["pre_open_entries"]["before_axis"] == 1 and r["position"][0]["up"] == 2


def test_before_chainlink_recording_and_without_a_book() -> None:
    from signals.research import workspace as WS

    read = {"slug": SLUG, "start": 1794285000, "end": 1794285900, "price_to_beat": 74719.68, "result": "Down",
            "prices": {"Up": [[1794285000, 0.5]], "Down": [[1794285000, 0.5]]}, "chainlink": [[1794285000, 1.0]],
            "coverage": {"trades_read": 10, "trades_complete": True}}  # fmt: skip
    r = WS.ready(read, [], [[1794285000, 74827.09]])
    assert r["chainlink"] is None and r["coverage"]["chainlink"] == "start_and_result"  # before 10 Nov 05:27 UTC
    assert r["up"] == [] and r["minute_fallback"]["up"] == [{"t": 1794285000, "p": 0.5}]
    assert r["binance"] == [{"t": 1794285000, "p": 74827.09}] and not r["coverage"]["book"]
    assert WS.summary(r)["profit"] == 0 and WS.totals([r["coverage"]])["chainlink"] == {"complete": 0, "total": 1}


class FakeCaseReads:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def window(self, slug: str, condition_id: Any = None, **kw: Any) -> dict[str, Any]:
        self.calls.append("window")
        return _recorded_read()

    def outside_prices(self, *a: Any, **k: Any) -> dict[str, Any]:
        self.calls.append("binance")
        return {"available": True, "points": [[LATE, 1.0]]}

    def wallet_trades(self, wallet: str, a: Any, b: Any, prefix: Any) -> dict[str, Any]:
        self.calls.append(f"trades:{prefix}")
        return {"trades": [_wallet_fill("0xa", LATE + 12, 0.62, 10)]}


def test_build_reads_only_what_the_investigation_hasnt() -> None:
    from signals.research import workspace as WS

    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.set_wallet(sid, W)
    reads = FakeCaseReads()
    r = WS.build(store, reads, sid, LATE_SLUG)
    assert reads.calls == ["window", f"trades:{LATE_SLUG}"]  # a recording brings its own Binance
    assert r["trades"][0]["paid_ask"] is True and store.trade(sid, r["trades"][0]["trade_id"])["tx"] == "0xa"  # type: ignore[index]
    WS.build(store, reads, sid, LATE_SLUG, {"x": 1})
    assert reads.calls == ["window", f"trades:{LATE_SLUG}"] and store.window(sid, LATE_SLUG)["ready"]["tags"] == {"x": 1}
    assert [s["window_id"] for s in store.summaries(sid)] == [LATE_SLUG]


def test_a_window_without_its_file_gets_chainlink_from_the_raw_recording() -> None:
    from signals.research import workspace as WS

    class ApiOnly(FakeCaseReads):  # Layer hasn't built the window yet: Polymarket's API, and the raw recording
        asked: list[tuple[str, int, int]] = []

        def window(self, slug: str, condition_id: Any = None, **kw: Any) -> dict[str, Any]:
            return {"slug": LATE_SLUG, "start": LATE, "end": LATE + 900, "price_to_beat": 74719.5, "result": "Up",
                    "prices": {"Up": [[LATE, 0.5]], "Down": [[LATE, 0.5]]},
                    "book": {"available": False, "status": "not_processed"},
                    "coverage": {"trades_read": None, "trades_complete": None}}  # fmt: skip

        def chainlink(self, symbol: str, a: int, b: int) -> list[list[float]]:
            self.asked.append((symbol, a, b))
            return [[LATE, 74719.5], [LATE + 1, 74720.0]]

    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.set_wallet(sid, W)
    reads = ApiOnly()
    r = WS.build(store, reads, sid, LATE_SLUG)
    assert reads.asked == [("btc/usd", r["axis"]["from"], r["axis"]["to"])]
    assert r["chainlink"] == [{"t": LATE, "p": 74719.5}, {"t": LATE + 1, "p": 74720.0}]
    cov = r["coverage"]
    assert cov["chainlink"] == "full" and cov["chainlink_source"] == "Layer raw recording (live feed)"
    assert cov["book_status"] == "not_processed" and not cov["book"]
    WS.build(store, reads, sid, LATE_SLUG)
    assert len(reads.asked) == 1  # read once, kept


def test_window_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from signals.research import server

    monkeypatch.setattr(server, "store", Store(os.path.join(tempfile.mkdtemp(), "s.db")))
    monkeypatch.setattr(server, "_reads", FakeCaseReads())
    server.app.dependency_overrides[server.auth.user_of] = lambda: "alice"
    try:
        c = TestClient(server.app)
        sid = c.post("/api/research/sessions", json={}).json()["id"]
        assert c.get(f"/api/research/sessions/{sid}/windows/{LATE_SLUG}").status_code == 404  # no wallet yet
        server.store.set_wallet(sid, W)
        r = c.get(f"/api/research/sessions/{sid}/windows/{LATE_SLUG}").json()
        assert r["window_id"] == LATE_SLUG and r["position"][0]["up"] == 10
        tiles = c.get(f"/api/research/sessions/{sid}/windows").json()
        assert tiles["windows"][0]["window_id"] == LATE_SLUG and tiles["coverage"]["book"] == {"complete": 1, "total": 1}
    finally:
        server.app.dependency_overrides.clear()


# ---- tools ----


def test_charts_must_hold_their_own_data() -> None:
    saved: list[Any] = []
    save = lambda t, s, c: saved.append(s) or "c_1"  # noqa: E731
    spec = {"data": {"values": [{"t": 1, "p": 2}]}, "mark": "line"}
    text, failed, summary = T.run("make_chart", {"title": "BTC", "spec": spec}, None, save)  # type: ignore[arg-type]
    assert not failed and json.loads(text)["chart_id"] == "c_1" and summary["rows"] == 1
    assert saved[0]["$schema"].endswith("v5.json")
    text, failed, _ = T.run("make_chart", {"title": "x", "spec": {"data": {"url": "https://evil"}}}, None, save)  # type: ignore[arg-type]
    assert failed and "spec.data.url" in text


def test_every_data_tool_is_called_from_code_only() -> None:
    assert all(t["allowed_callers"] == [T.CALLER] for t in T.TOOLS)
    assert {t["name"] for t in T.TOOLS} == {"wallet_trades", "wallet_profile", "window", "outside_prices", "make_chart"}


# ---- the loop, with a scripted model ----


class FakeReads:
    def wallet_trades(self, w: str, a: Any, b: Any, prefix: Any) -> dict[str, Any]:
        return {"wallet": W, "count": 3, "windows": 2, "complete": True,
                "trades": [_wallet_fill("0xa", LATE + 12, 0.42, 1)]}  # fmt: skip


class Model:
    """A scripted Claude: each request gets the next response; requests are kept."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses, self.requests = list(responses), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw: Any) -> Any:
        self.requests.append(copy.deepcopy(kw))
        r = self.responses.pop(0)
        r = r(kw) if callable(r) else r
        if isinstance(r, Exception):
            raise r
        return Model._Ctx(r)

    class _Ctx:  # what messages.stream returns: a context manager with get_final_message()
        def __init__(self, msg: dict[str, Any]) -> None:
            self.msg = msg

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *a: Any) -> None:
            pass

        def get_final_message(self) -> dict[str, Any]:
            return self.msg


def _model(*responses: dict[str, Any]) -> Model:
    return Model(*responses)


USAGE = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


class ApiError(Exception):
    """What the anthropic SDK raises for a 4xx: it has ``status_code``."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status


def _expired_if_old(kw: dict[str, Any]) -> Any:
    if kw.get("container") == "cont_old":
        return ApiError(400, "container cont_old has expired")
    return _answers("Observed: 3 trades.")


def _calls_tool() -> dict[str, Any]:
    usage = {**USAGE, "server_tool_use": {"code_execution_requests": 1}}
    return {"stop_reason": "tool_use", "usage": usage, "container": {"id": "cont_1"}, "content": [
        {"type": "thinking", "thinking": "Reading the wallet's trades.", "signature": "s"},
        {"type": "server_tool_use", "id": "srv_1", "name": "code_execution", "input": {"code": "await wallet_trades(...)"}},
        {"type": "tool_use", "id": "tu_1", "name": "wallet_trades", "input": {"wallet": W, "start": 0, "end": 9},
         "caller": {"type": T.CALLER, "tool_id": "srv_1"}},
    ]}  # fmt: skip


def _answers(text: str, stdout: str = "windows=2 trades=3 avg_price=0.42") -> dict[str, Any]:
    return {"stop_reason": "end_turn", "usage": USAGE, "container": {"id": "cont_1"}, "content": [
        {"type": "code_execution_tool_result", "tool_use_id": "srv_1",
         "content": {"type": "code_execution_result", "stdout": stdout, "stderr": "", "return_code": 0}},
        {"type": "text", "text": text},
    ]}  # fmt: skip


def _ask(model: Model, question: str = "Analyze it", store: Store | None = None) -> tuple[list[dict[str, Any]], Store, str]:
    store = store or Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    events: list[dict[str, Any]] = []
    A.Agent(FakeReads(), store, model).ask(sid, "u1", question, events.append)  # type: ignore[arg-type]
    return events, store, sid


def test_a_tool_call_from_code_and_a_traced_answer() -> None:
    model = _model(_calls_tool(), _answers("Observed: 3 trades in 2 windows at 42¢ on average."))
    events, store, sid = _ask(model)
    kinds = [e["type"] for e in events]
    assert kinds == ["investigation.created", "ask.started", "answer.progress", "tool.call", "tool.call", "tool.result",
                     "tool.result", "answer.card", "usage", "done"]  # fmt: skip
    created = events[0]
    assert created["subject"] == {"wallet": None, "name": None} and created["question"] == "Analyze it"
    code_call, data_call = events[3], events[4]
    assert code_call["tool"] == "code" and data_call["tool"] == "wallet_trades"
    data_result = [e for e in events if e["type"] == "tool.result" and e["tool"] == "wallet_trades"][0]
    assert data_result["rows"] == 3 and data_result["limit_hit"] is False
    second = model.requests[1]
    assert second["container"] == "cont_1"  # the paused code's container
    assert [b["type"] for b in second["messages"][-1]["content"]] == ["tool_result"]  # only tool results
    assert json.loads(second["messages"][-1]["content"][0]["content"])["count"] == 3
    assert model.requests[0]["tools"][0] == T.CODE_EXECUTION and model.requests[0]["fallbacks"] == "default"
    assert events[kinds.index("answer.card")]["number_check"] == {"passed": True, "flagged": {}}
    run = store.runs()[0]
    assert run["check_ok"] == 1 and run["rounds"] == 2 and run["tool_calls"] == 1 and run["code_runs"] == 1
    assert run["container_s"] == A.CONTAINER_MIN_S  # used: billed 5 minutes at least
    tokens = 2 * (1000 * 4 + 500 * 20) / 1e6
    assert run["cost_usd"] == pytest.approx(tokens + 300 / 3600 * 0.05)
    usage = [e for e in events if e["type"] == "usage"][0]
    assert usage["token_usd"] == pytest.approx(tokens) and usage["container_s"] == 300
    assert store.session(sid, "u1")["container"] == "cont_1"  # type: ignore[index]
    assert all(e["v"] == A.EVENT_VERSION and e["run"] == run["id"] for e in events)


def test_a_follow_up_replays_the_conversation_and_container() -> None:
    model = _model(_calls_tool(), _answers("Observed: 3 trades."), _answers("Observed: 2 windows.", stdout="2"))
    _, store, sid = _ask(model)
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "And windows?", lambda e: None)  # type: ignore[arg-type]
    third = model.requests[2]
    assert third["container"] == "cont_1" and third["messages"][0]["content"][0]["text"] == "Analyze it"
    assert third["messages"][-1]["content"][0]["text"] == "And windows?"


def _session_with_container(container_at: float | None = None) -> tuple[Store, str]:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.add_message(sid, "user", [{"type": "text", "text": "Analyze it"}])
    store.add_message(sid, "assistant", [{"type": "text", "text": "Observed: 3 trades."}])
    store.set_container(sid, "cont_old")
    if container_at is not None:
        store._q("UPDATE sessions SET container_at = ? WHERE id = ?", (container_at, sid))
    return store, sid


def test_an_expired_container_is_rebuilt_and_said() -> None:
    store, sid = _session_with_container()
    model = _model(_expired_if_old, _expired_if_old)
    events: list[dict[str, Any]] = []
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "And the windows?", events.append)  # type: ignore[arg-type]
    assert [r.get("container") for r in model.requests] == ["cont_old", None]
    retry = model.requests[1]["messages"]
    assert retry[-2]["content"][0]["text"] == "And the windows?" and retry[-1] == {"role": "system", "content": A.REBUILT}
    assert [e["type"] for e in events if e["type"] in ("notice", "answer.card", "error")] == ["notice", "answer.card"]
    assert store.session(sid, "u1")["container"] == "cont_1"  # type: ignore[index]
    # the note stays in the conversation (hidden), so the next follow-up replays it in place
    assert {"role": "system", "content": A.REBUILT} in store.messages(sid)


def test_a_container_near_30_days_old_is_not_used() -> None:
    import time as _time

    store, sid = _session_with_container(container_at=_time.time() - 29.5 * 86_400)
    model = _model(_answers("Observed: 3 trades."))
    events: list[dict[str, Any]] = []
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "Again?", events.append)  # type: ignore[arg-type]
    assert "container" not in model.requests[0] and any(e["type"] == "notice" for e in events)


def test_a_container_lost_while_code_waits_on_a_tool_ends_the_step() -> None:
    model = _model(_calls_tool(), ApiError(404, "container cont_1 not found"))
    events, store, sid = _ask(model)
    assert [e["message"] for e in events if e["type"] == "error"] == [
        "The breakdown stopped on an error. Try again in a minute."]  # fmt: skip
    assert store.session(sid, "u1")["container"] is None  # type: ignore[index]  # the next question starts fresh


def test_other_api_errors_are_not_mistaken_for_an_expired_container() -> None:
    store, sid = _session_with_container()
    model = _model(ApiError(400, "messages: text content blocks must be non-empty"))
    events: list[dict[str, Any]] = []
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "Again?", events.append)  # type: ignore[arg-type]
    assert len(model.requests) == 1 and not any(e["type"] == "notice" for e in events)


def test_an_untraced_number_gets_one_retry() -> None:
    model = _model(_calls_tool(), _answers("It made $99.99."), _answers("Observed: 3 trades."))
    events, _, _ = _ask(model)
    assert "$99.99" in model.requests[2]["messages"][-1]["content"][0]["text"]
    cards = [e for e in events if e["type"] == "answer.card"]
    assert len(cards) == 1 and cards[0]["text"] == "Observed: 3 trades." and cards[0]["number_check"]["passed"]


def test_repeating_the_same_untraced_number_doesnt_make_it_trace() -> None:
    model = _model(_calls_tool(), _answers("It made $99.99."), _answers("It made $99.99."))
    events, _, _ = _ask(model)
    card = [e for e in events if e["type"] == "answer.card"][0]
    assert not card["number_check"]["passed"]  # the check's note quoted $99.99; that never makes it data


def test_still_untraced_after_the_retry_is_shown_flagged() -> None:
    model = _model(_calls_tool(), _answers("It made $99.99."), _answers("It made $98.00."))
    events, store, _ = _ask(model)
    card = [e for e in events if e["type"] == "answer.card"][0]
    assert card["number_check"] == {"passed": False, "flagged": {"text": [
        {"value_text": "$98.00", "start": 8, "end": 14, "data_value": None}]}}  # fmt: skip
    assert store.runs()[0]["check_ok"] == 0


def test_the_per_question_budget_stops_a_long_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(A, "MAX_USD", 0.001)
    events, store, _ = _ask(_model(_calls_tool(), _calls_tool()))
    assert any(e["type"] == "error" and "limit" in e["message"] for e in events)
    assert store.runs()[0]["error"] == "over_budget"


def test_the_daily_limit_asks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(A, "DAILY_USD", 0.0)
    model = _model()
    events, _, _ = _ask(model)
    assert model.requests == [] and "today's limit" in [e for e in events if e["type"] == "error"][0]["message"]


def test_near_the_time_limit_the_agent_is_told_to_answer_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(A, "WRAP_AT", 0.0)  # from the first step
    model = _model(_calls_tool(), _answers("Observed: 3 trades."))
    _ask(model)
    notes = [m for m in model.requests[0]["messages"] if m["role"] == "system"]
    assert notes == [{"role": "system", "content": A.WRAP_UP}]
    # the second request answers the code's paused call: only tool results there, and the note isn't repeated
    second = model.requests[1]["messages"]
    assert second[-1]["role"] == "user" and sum(m["role"] == "system" for m in second) == 1


def test_a_stop_with_findings_ends_on_an_answer_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(A, "MAX_USD", 0.001)
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.add_finding(sid, {"label": "observed", "title": "Two-sided in 93 of 94 windows", "counts": True,
                            "stat": {"text": "93 of 94 windows"}})  # fmt: skip
    store.add_finding(sid, {"label": "observed", "title": "Made-up", "counts": False})
    events: list[dict[str, Any]] = []
    A.Agent(FakeReads(), store, _model(_calls_tool(), _calls_tool())).ask(sid, "u1", "Go", events.append)  # type: ignore[arg-type]
    kinds = [e["type"] for e in events]
    assert "error" not in kinds and kinds[-4:] == ["answer.card", "notice", "usage", "done"]
    card = events[kinds.index("answer.card")]
    assert card["partial"] and card["observed"] == ["Two-sided in 93 of 94 windows: 93 of 94 windows"]
    assert card["finding_ids"] == ["F1"]  # the flagged one isn't in it
    assert "limit" in events[kinds.index("notice")]["text"]


def test_start_builds_the_approved_scopes_tiles_without_waiting_for_the_agent() -> None:
    plan = {"title": "t", "scope": {"wallet": W, "family": "btc-updown-15m", "from": LATE - 60, "to": LATE + 900},
            "steps": [{"id": "s", "title": "x", "source": "y"}]}  # fmt: skip
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    reads = FakeCaseReads()
    model = _model(_turn(_direct("propose_plan", plan)), _answers("Observed: 3 trades."))
    A.Agent(reads, store, model).ask(sid, "u1", "How?", lambda e: None)  # type: ignore[arg-type]
    assert store.scope(sid)["from"] == LATE - 60  # type: ignore[index]
    events: list[dict[str, Any]] = []
    A.Agent(reads, store, model).ask(sid, "u1", "Start the plan.", events.append,  # type: ignore[arg-type]
                                     context={"plan_id": "plan-1", "action": "approve"})
    kinds = [e["type"] for e in events]
    assert "window.summary" in kinds and "coverage" in kinds
    assert [e for e in events if e["type"] == "window.summary"][0]["window_id"] == LATE_SLUG
    assert "trades:btc-updown-15m-" in reads.calls  # the scope's trades, read by the server
    assert A.PREBUILD_NOTE.strip()[:30] in model.requests[1]["messages"][-1]["content"][-1]["text"]
    usage = [e for e in events if e["type"] == "usage"][0]
    assert "tiles_done" in usage["phases"] and "first_tile" in usage["phases"]


def test_scope_times_read_the_words_a_plan_is_written_in() -> None:
    now = LATE + 3 * 3600 + 17  # 10 Nov 09:00:17 UTC
    assert D.scope_time("now", now) == now
    assert D.scope_time("today 05:30 UTC", now) == LATE - 1800
    assert D.scope_time("Yesterday at 22:00", now) == LATE - 8 * 3600
    assert D.scope_time("2026-11-10T05:30:00Z", now) == D.scope_time(LATE - 1800, now) == LATE - 1800
    with pytest.raises(D.ReadError):
        D.scope_time("since breakfast", now)
    with pytest.raises(D.ReadError):
        D.scope_time("today 25:00 UTC", now)


def test_a_plans_cost_is_what_recent_starts_cost_never_the_models_guess() -> None:
    """The Breakdowns doc promises the plan shows an estimated cost; the model was never asked for one, so live
    plans showed only the time. The server's figure: the median of the latest Starts that ran to their end."""
    plan = {"title": "t", "scope": {"wallet": W, "from": "2026-11-10T05:30:00Z", "to": "2026-11-10T06:45:00Z"},
            "steps": [{"id": "s", "title": "x", "source": "y", "estimate_s": 60}], "estimate_usd": 0.05}  # fmt: skip
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    events, _, _ = _ask(_model(_turn(_direct("propose_plan", plan))), store=store)
    assert next(e for e in events if e["type"] == "plan.proposed")["estimate_usd"] is None  # too few Starts: no cost

    def run(cost: float, kind: str | None = "start", error: str | None = None) -> None:
        r = store.start_run("s0", "u9")  # another person's Starts (u1's own daily limit stays clear)
        store.update_run(r, kind=kind, ended=time.time(), cost_usd=cost, error=error)

    for c in (0.8, 1.1, 0.95, 1.4, 0.7):
        run(c)
    run(2.0, error="interrupted")  # cut off by a deploy: not what a Start costs
    run(2.0, kind=None)  # a plain question
    run(3.0, error="over_budget")  # stopped at the cost limit: it did cost that
    assert store.start_cost() == 1.02  # median of 0.7, 0.8, 0.95, 1.1, 1.4, 3.0
    events, _, _ = _ask(_model(_turn(_direct("propose_plan", plan))), store=store)
    assert next(e for e in events if e["type"] == "plan.proposed")["estimate_usd"] == 1.02  # not the model's 0.05
    from signals.research import case as C

    assert "estimate_usd" not in next(t for t in C.CASE_TOOLS if t["name"] == "propose_plan")["input_schema"]["properties"]


def test_a_start_is_marked_as_one_for_the_cost_line() -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    A.Agent(FakeReads(), store, _model(_answers("Observed: 3 trades."))).ask(  # type: ignore[arg-type]
        sid, "u1", "Start the plan.", lambda e: None, context={"plan_id": "plan-1", "action": "approve"})
    assert [r["kind"] for r in store.runs()] == ["start"]


def test_a_plan_keeps_its_scope_as_times_start_can_read() -> None:
    plan = {"title": "t", "scope": {"wallet": W, "from": "today 05:30 UTC", "to": "now"},
            "steps": [{"id": "s", "title": "x", "source": "y"}]}  # fmt: skip
    events, store, sid = _ask(_model(_turn(_direct("propose_plan", plan))))
    scope = store.scope(sid)
    assert scope["to"] == "now" and scope["from"].endswith("T05:30:00Z")  # type: ignore[index]
    bad = {**plan, "scope": {"wallet": W, "from": "since breakfast", "to": "now"}}
    model = _model(_turn(_direct("propose_plan", bad)), _answers("Observed: 3 trades."))
    events, store, sid = _ask(model)
    assert "plan.proposed" not in [e["type"] for e in events]
    sent = model.requests[1]["messages"][-1]["content"][0]
    assert sent["is_error"] and "ISO time" in sent["content"]


def test_start_builds_the_tiles_of_a_scope_written_in_words() -> None:
    plan = {"title": "t", "scope": {"wallet": W, "family": "btc-updown-15m", "from": "today 05:30 UTC", "to": "now"},
            "steps": [{"id": "s", "title": "x", "source": "y"}]}  # fmt: skip
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    reads = FakeCaseReads()
    model = _model(_turn(_direct("propose_plan", plan)), _answers("Observed: 3 trades."))
    A.Agent(reads, store, model).ask(sid, "u1", "How?", lambda e: None)  # type: ignore[arg-type]
    events: list[dict[str, Any]] = []
    A.Agent(reads, store, model).ask(sid, "u1", "Start the plan.", events.append,  # type: ignore[arg-type]
                                     context={"plan_id": "plan-1", "action": "approve"})
    assert [e["window_id"] for e in events if e["type"] == "window.summary"] == [LATE_SLUG]
    assert A.PREBUILD_NOTE.strip()[:30] in model.requests[1]["messages"][-1]["content"][-1]["text"]


def test_a_scope_start_cant_read_leaves_the_tiles_to_the_agent() -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    model = _model(_answers("Observed: 3 trades."))
    store.set_scope(sid, {"wallet": W, "from": "since breakfast", "to": "now"})  # a plan saved before the check
    A.Agent(FakeCaseReads(), store, model).ask(sid, "u1", "Start the plan.", lambda e: None,  # type: ignore[arg-type]
                                               context={"plan_id": "plan-1", "action": "approve"})
    assert A.PREBUILD_NOTE.strip()[:30] not in json.dumps(model.requests[0]["messages"])


def test_windows_the_agent_read_but_never_showed_get_tiles_at_the_end() -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.set_wallet(sid, W)
    store.add_trades(sid, [_wallet_fill("0xa", LATE + 12, 0.62, 10)])
    store.put_window(sid, LATE_SLUG, read=_recorded_read())  # read by the window tool, no tile
    store.put_window(sid, "btc-updown-15m-1794291300", read=_recorded_read(1794291300))  # read, but no fills there
    events: list[dict[str, Any]] = []
    A.Agent(FakeCaseReads(), store, _model(_answers("Observed: 3 trades."))).ask(sid, "u1", "Go", events.append)  # type: ignore[arg-type]
    kinds = [e["type"] for e in events]
    assert [e["window_id"] for e in events if e["type"] == "window.summary"] == [LATE_SLUG]
    assert kinds.index("window.summary") > kinds.index("answer.card") and kinds[-2:] == ["usage", "done"]
    assert [c["window_id"] for c in events[kinds.index("coverage")]["windows"]] == [LATE_SLUG]
    assert [s["window_id"] for s in store.summaries(sid)] == [LATE_SLUG] and store.unshown(sid) == ["btc-updown-15m-1794291300"]


def test_usage_reports_the_phases() -> None:
    plan = {"title": "t", "scope": {"wallet": W}, "steps": [{"id": "s", "title": "x", "source": "y"}]}
    events, _, _ = _ask(_model(_turn(_direct("propose_plan", plan))))
    usage = [e for e in events if e["type"] == "usage"][0]
    assert set(usage["phases"]) == {"plan"} and usage["phases"]["plan"] >= 0 and usage["seconds"] >= 0


def test_a_refusal_ends_with_a_sentence() -> None:
    events, _, _ = _ask(_model({"stop_reason": "refusal", "usage": USAGE, "content": []}))
    assert [e["message"] for e in events if e["type"] == "error"] == ["The model declined this request."]


# ---- the case file's tools ----


def _direct(name: str, inp: dict[str, Any], tid: str = "tu_d") -> dict[str, Any]:
    return {"type": "tool_use", "id": tid, "name": name, "input": inp, "caller": {"type": "direct"}}


def _turn(*blocks: dict[str, Any], stop: str = "tool_use") -> dict[str, Any]:
    return {"stop_reason": stop, "usage": USAGE, "content": list(blocks)}


def test_a_plan_waits_for_start_and_start_continues_the_same_turn() -> None:
    plan = {"title": "How it trades BTC 15m", "scope": {"wallet": W, "family": "btc-updown-15m"},
            "steps": [{"id": "trades", "title": "Read its trades", "source": "Polymarket trades", "estimate_s": 20}]}  # fmt: skip
    model = _model(_turn(_direct("propose_plan", plan)), _answers("Observed: 3 trades."))
    events, store, sid = _ask(model, f"How does {W} trade?")
    assert len(model.requests) == 1  # the run ended on the plan
    p = [e for e in events if e["type"] == "plan.proposed"][0]
    assert p["needs_approval"] and p["steps"][0]["id"] == "trades" and p["ask_id"] == events[0]["run"]
    assert events[0]["type"] == "investigation.created" and events[0]["subject"]["wallet"] == W
    assert store.session_any(sid)["wallet"] == W  # type: ignore[index]
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "Start", lambda e: None)  # type: ignore[arg-type]
    last = model.requests[1]["messages"][-1]
    assert [b["type"] for b in last["content"]] == ["tool_result", "text"] and last["content"][1]["text"] == "Start"


def test_a_walkthrough_with_an_untraced_number_fails_once_then_shows_it_flagged() -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.set_wallet(sid, W)
    fill = _wallet_fill("0xa", LATE + 12, 0.62, 10)
    store.add_trades(sid, [fill])
    store.put_window(sid, LATE_SLUG, read=_recorded_read())
    step = {"t": LATE + 12, "title": "It buys Up", "observed": "It bought 10 shares at 62¢, 12 s in.",
            "inferred": None, "trade_ids": [fill["id"]]}  # fmt: skip
    bad = {**step, "observed": "It bought 10 shares at 64¢, 12 s in."}
    events: list[dict[str, Any]] = []
    src = trace.Sources(['{"shares": 10, "price": 0.62, "s_in": 12}'])
    case = __import__("signals.research.case", fromlist=["Case"]).Case(sid, 1, store, FakeCaseReads(), events.append, lambda: src)
    text, failed, _ = case.handle("walkthrough", {"window_id": LATE_SLUG, "steps": [bad]})
    assert failed and "64¢" in text and "closest in the data: 62" in text and not events
    text, failed, _ = case.handle("walkthrough", {"window_id": LATE_SLUG, "steps": [bad]})
    wt = [e for e in events if e["type"] == "walkthrough.ready"][0]
    flag = wt["steps"][0]["number_check"]["flagged"]["observed"][0]
    at = bad["observed"].index("64¢")
    assert flag == {"value_text": "64¢", "start": at, "end": at + 3, "data_value": 62.0}
    assert bad["observed"][flag["start"]:flag["end"]] == "64¢"
    assert [e["type"] for e in events] == ["window.ready", "walkthrough.ready"]  # the replay first, once
    text, failed, _ = case.handle("walkthrough", {"window_id": LATE_SLUG, "steps": [{**step, "trade_ids": ["nope"]}]})
    assert failed and "aren't the wallet's fills" in text


def test_show_windows_and_focus() -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.set_wallet(sid, W)
    events: list[dict[str, Any]] = []
    from signals.research.case import Case

    case = Case(sid, 1, store, FakeCaseReads(), events.append, lambda: trace.Sources())
    text, failed, summary = case.handle("show_windows", {"window_ids": [LATE_SLUG], "tags": {LATE_SLUG: {"jump": 1}}})
    out = json.loads(text)
    assert not failed and out["windows"][0]["fills"] == 1 and "spark" not in out["windows"][0] and summary["rows"] == 1
    assert [e["type"] for e in events] == ["window.summary", "coverage"]
    assert events[0]["entries"] == [{"t": LATE + 12, "side": "Up", "action": "buy"}]
    case.handle("focus", {"stage": "window", "window_id": LATE_SLUG, "step_index": 0, "label": "The clearest one"})
    case.handle("focus", {"stage": "window", "window_id": LATE_SLUG, "step_index": 1})
    kinds = [e["type"] for e in events[2:]]
    assert kinds == ["window.ready", "view.focus", "view.focus"] and events[2]["tags"] == {"jump": 1}
    assert events[3]["step_index"] == 0 and events[3]["label"] == "The clearest one"
    assert case.handle("focus", {"stage": "nowhere"})[1]
    assert case.handle("step_status", {"step_id": "trades", "status": "done", "summary": "94 windows"})[0] == "ok"
    assert json.loads(case.handle("propose", {"text": "Next, I'd look at the losing windows"})[0])["proposal_id"] == "P1"


def _case_with_fill() -> tuple[Any, Store, str, dict[str, Any], list[dict[str, Any]]]:
    from signals.research.case import Case

    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.set_wallet(sid, W)
    fill = _wallet_fill("0xa", LATE + 12, 0.62, 10)
    store.add_trades(sid, [fill])
    store.put_window(sid, LATE_SLUG, read=_recorded_read())
    events: list[dict[str, Any]] = []
    src = trace.Sources(['{"windows": 94, "heavier_lost": 65, "pairs_under_1": 83, "median_pair": 0.929}'])
    return Case(sid, 7, store, FakeCaseReads(), events.append, lambda: src), store, sid, fill, events


def test_findings_observed_inferred_flagged_and_fixed() -> None:
    case, store, sid, fill, events = _case_with_fill()
    obs = {"label": "observed", "kind": "pattern", "title": "Extra shares end on the losing side",
           "stat": {"count": 65, "out_of": 94, "unit": "windows", "text": "65 of 94 windows"},
           "rule": "The side with more shares at the end lost.",
           "evidence": {"supporting_window_ids": [LATE_SLUG], "trade_ids": [fill["id"]]}}  # fmt: skip
    text, failed, _ = case.handle("finding", obs)
    assert not failed and json.loads(text)["finding_id"] == "F1"
    added = events[-1]
    assert added["type"] == "finding.added" and added["counts"] and added["number_check"]["passed"]
    # a made-up count fails once, then shows flagged and doesn't count
    bad = {**obs, "title": "Pairs cost under $1", "stat": {"count": 88, "out_of": 94, "text": "88 of 94 windows"}}
    assert case.handle("finding", bad)[1]
    case.handle("finding", bad)
    f2 = events[-1]
    assert f2["finding_id"] == "F2" and not f2["counts"] and f2["number_check"]["flagged"]["stat"][0]["value_text"] == "88"
    # nothing rests on a flagged finding; an inferred one needs based_on
    read = {"label": "inferred", "title": "Resting orders on both sides", "would_change_mind": "maker flags"}
    assert "needs based_on" in case.handle("finding", read)[0]
    assert "didn't check out" in case.handle("finding", {**read, "based_on": ["F2"]})[0]
    assert not case.handle("finding", {**read, "based_on": ["F1"]})[1] and events[-1]["label"] == "inferred"
    # fixing F2 keeps the earlier version
    case.handle("finding", {**bad, "finding_id": "F2", "stat": {"count": 83, "out_of": 94, "text": "83 of 94 windows"}})
    upd = events[-1]
    assert upd["type"] == "finding.updated" and upd["counts"] and upd["previous"]["stat"]["count"] == 88
    assert store.finding(sid, "F2")["history"][0]["stat"]["count"] == 88  # type: ignore[index]
    assert "aren't the wallet's fills" in case.handle("finding", {**obs, "evidence": {"trade_ids": ["x"]}})[0]
    assert "weren't read" in case.handle("finding", {**obs, "evidence": {"supporting_window_ids": ["btc-updown-15m-1"]}})[0]


def test_the_answer_card_and_the_run_ends_on_it() -> None:
    card = {"label": "Why it lost here", "observed": ["Its heavier side lost in 65 of 94 windows."],
            "inferred": ["Resting orders fill more on the side that's falling."], "finding_ids": ["F1"]}  # fmt: skip
    model = _model(_calls_tool(), _turn(_direct("answer", card, "a1")), _turn(_direct("answer", card, "a2")),
                   _answers("never asked"))  # fmt: skip
    events, store, sid = _ask(model, "Why does it lose?")
    assert "65" in model.requests[2]["messages"][-1]["content"][0]["content"]  # the first card bounced, naming 65
    assert len(model.requests) == 3  # the second is shown flagged, and the run ends on it: no extra call
    cards = [e for e in events if e["type"] == "answer.card"]
    assert len(cards) == 1 and cards[0]["label"] == "Why it lost here" and cards[0]["number_check"]["passed"] is False
    assert cards[0]["number_check"]["flagged"]["observed 1"][0]["value_text"] == "65"  # the fake data has no 65


# ---- the server ----


def test_server_sessions_are_their_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from signals.research import server

    monkeypatch.setattr(server, "store", Store(os.path.join(tempfile.mkdtemp(), "s.db")))

    class Fake:
        reads = None

        def ask(self, sid: str, user: str, q: str, emit: Any, **kw: Any) -> None:
            emit({"type": "answer", "text": "ok", "unverified": []})
            emit({"type": "done"})

    monkeypatch.setattr(server, "_agent", Fake())
    who = {"user": "alice"}
    server.app.dependency_overrides[server.auth.user_of] = lambda: who["user"]
    try:
        c = TestClient(server.app)
        sid = c.post("/api/research/sessions", json={}).json()["id"]
        assert c.post(f"/api/research/sessions/{sid}/ask", json={"question": "hi"}).status_code == 202
        stream = c.get(f"/api/research/sessions/{sid}/events").text
        assert '"type": "answer"' in stream and '"type": "done"' in stream
        assert c.get(f"/api/research/sessions/{sid}").json()["events"][-1]["type"] == "done"
        who["user"] = "bob"
        assert c.get(f"/api/research/sessions/{sid}").status_code == 404
        assert c.post(f"/api/research/sessions/{sid}/ask", json={"question": "hi"}).status_code == 404
        assert c.get(f"/api/research/sessions/{sid}/events").status_code == 404
    finally:
        server.app.dependency_overrides.clear()


class Recorder:
    """A stand-in agent that keeps what each run was asked."""

    reads = None

    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []

    def ask(self, sid: str, user: str, q: str, emit: Any, **kw: Any) -> None:
        self.asked.append({"text": q, **kw})
        emit({"type": "done"})


def _client(monkeypatch: pytest.MonkeyPatch, agent: Any) -> tuple[Any, Any]:
    from fastapi.testclient import TestClient

    from signals.research import server

    monkeypatch.setattr(server, "store", Store(os.path.join(tempfile.mkdtemp(), "s.db")))
    monkeypatch.setattr(server, "_agent", agent)
    monkeypatch.setattr(server, "_reads", FakeCaseReads())
    server.app.dependency_overrides[server.auth.user_of] = lambda: "alice"
    return TestClient(server.app), server


def _settle(server: Any) -> None:
    import time as _time

    for _ in range(100):
        if not server._running:
            return
        _time.sleep(0.01)


def test_plan_start_and_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    c, server = _client(monkeypatch, rec)
    try:
        sid = c.post("/api/research/sessions", json={}).json()["id"]
        server.store.add_event(sid, {"type": "plan.proposed", "plan_id": "plan-1", "steps": [],
                                     "scope_options": [{"id": "oct", "text": "Also October, 1-minute prices"}]})  # fmt: skip
        assert c.post(f"/api/research/sessions/{sid}/plan", json={"plan_id": "plan-9", "action": "approve"}).status_code == 404
        r = c.post(f"/api/research/sessions/{sid}/plan",
                   json={"plan_id": "plan-1", "action": "approve", "scope_option_ids": ["oct"]})  # fmt: skip
        assert r.status_code == 202
        _settle(server)
        assert rec.asked[0]["text"] == "Start the plan.\nAlso: Also October, 1-minute prices"
        assert rec.asked[0]["context"] == {"plan_id": "plan-1", "action": "approve"}
        assert c.post(f"/api/research/sessions/{sid}/plan", json={"plan_id": "plan-1", "action": "approve"}).status_code == 409
        server.store.add_event(sid, {"type": "plan.proposed", "plan_id": "plan-2", "steps": []})
        assert c.post(f"/api/research/sessions/{sid}/plan", json={"plan_id": "plan-2", "action": "edit"}).status_code == 400
        assert c.post(f"/api/research/sessions/{sid}/plan",
                      json={"plan_id": "plan-2", "action": "edit", "text": "Only Nov 9"}).status_code == 202  # fmt: skip
        _settle(server)
        assert rec.asked[1]["text"] == "Change the plan: Only Nov 9"
        answered = [e for e in server.store.events(sid) if e["type"] == "plan.answered"]
        assert [(e["plan_id"], e["action"]) for e in answered] == [("plan-1", "approve"), ("plan-2", "edit")]
    finally:
        server.app.dependency_overrides.clear()


def test_proposals_accept_or_decline(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    c, server = _client(monkeypatch, rec)
    try:
        sid = c.post("/api/research/sessions", json={}).json()["id"]
        server.store.add_event(sid, {"type": "proposal", "proposal_id": "P1", "text": "Look at the losing windows"})
        server.store.add_event(sid, {"type": "proposal", "proposal_id": "P2", "text": "Compare with Nov 8"})
        r = c.post(f"/api/research/sessions/{sid}/proposals/P2", json={"action": "decline"})
        assert r.json() == {"started": False} and rec.asked == []
        assert c.post(f"/api/research/sessions/{sid}/proposals/P2", json={"action": "accept"}).status_code == 409
        assert c.post(f"/api/research/sessions/{sid}/proposals/P1", json={"action": "accept"}).status_code == 202
        _settle(server)
        assert rec.asked[0]["text"] == "Yes, go ahead: Look at the losing windows"
    finally:
        server.app.dependency_overrides.clear()


def test_asking_about_a_trade_or_a_moment(monkeypatch: pytest.MonkeyPatch) -> None:
    from signals.research import workspace as WS

    rec = Recorder()
    c, server = _client(monkeypatch, rec)
    try:
        sid = c.post("/api/research/sessions", json={}).json()["id"]
        server.store.set_wallet(sid, W)
        fill = _wallet_fill("0xa", LATE + 12, 0.62, 10)
        server.store.add_trades(sid, [fill])
        server.store.put_window(sid, LATE_SLUG, read=_recorded_read())
        WS.build(server.store, FakeCaseReads(), sid, LATE_SLUG)
        bad = c.post(f"/api/research/sessions/{sid}/ask", json={"question": "Why?", "context": {"trade_id": "nope"}})
        assert bad.status_code == 404 and rec.asked == []
        r = c.post(f"/api/research/sessions/{sid}/ask", json={"question": "Why here?", "context": {"trade_id": fill["id"]}})
        assert r.status_code == 202
        _settle(server)
        f = rec.asked[0]["facts"]
        assert f["kind"] == "trade" and f["trade"]["tx"] == "0xa" and f["seconds_after_start"] == 12
        assert f["as_drawn"]["liquidity"] == "taker" and rec.asked[0]["context"] == {"trade_id": fill["id"]}
        c.post(f"/api/research/sessions/{sid}/ask", json={"question": "This burst?", "context": {"trade_ids": [fill["id"]]}})
        _settle(server)
        burst = rec.asked.pop()["facts"]
        assert burst["kind"] == "trades" and burst["count"] == 1 and burst["window_id"] == LATE_SLUG
        c.post(f"/api/research/sessions/{sid}/ask", json={"question": "What happened here?",
                                                          "context": {"window_id": LATE_SLUG, "t": LATE + 11}})  # fmt: skip
        _settle(server)
        m = rec.asked[1]["facts"]
        assert m["kind"] == "moment" and m["seconds_after_start"] == 11 and m["up"] == {"t": LATE + 11, "bid": 0.6, "ask": 0.62}
        assert [x["trade_id"] for x in m["fills_within_10s"]] == [fill["id"]]
    finally:
        server.app.dependency_overrides.clear()


def test_pointed_at_facts_reach_the_model() -> None:
    model = _model(_answers("Observed: 3 trades."))
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "Why here?", lambda e: None,  # type: ignore[arg-type]
                                           context={"trade_id": "abc"}, facts={"kind": "trade", "price": 0.62})
    said = model.requests[0]["messages"][-1]["content"][0]["text"]
    assert said.startswith("Why here?") and '"price": 0.62' in said


def test_the_request_through_the_real_anthropic_sdk() -> None:
    """The loop's request as the anthropic SDK sends it (body, beta headers) and a streamed reply parsed back."""
    import anthropic
    import httpx2  # the anthropic SDK's own HTTP package (2.x)

    sent: dict[str, Any] = {}

    def sse(*events: tuple[str, dict[str, Any]]) -> str:
        return "".join(f"event: {name}\ndata: {json.dumps(body)}\n\n" for name, body in events)

    def handler(req: Any) -> Any:
        body = json.loads(req.content)
        sent.setdefault("containers", []).append(body.get("container"))
        if body.get("container") == "cont_old":  # what the API answers for an expired container
            return httpx2.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "Container cont_old has expired."}})  # fmt: skip
        sent["body"], sent["beta"] = body, req.headers.get("anthropic-beta", "")
        msg = {"id": "msg_1", "type": "message", "role": "assistant", "content": [], "model": "claude-opus-5-5",
               "stop_reason": None, "stop_sequence": None,
               "container": {"id": "cont_9", "expires_at": "2026-11-10T06:00:00Z"},
               "usage": {"input_tokens": 10, "output_tokens": 0}}  # fmt: skip
        text = "Observed: 3 trades."
        body = sse(
            ("message_start", {"type": "message_start", "message": msg}),
            ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                               "usage": {"output_tokens": 5}}),
            ("message_stop", {"type": "message_stop"}),
        )  # fmt: skip
        return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = anthropic.Anthropic(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.add_message(sid, "user", [{"type": "text", "text": "Analyze it."}])
    store.add_message(sid, "assistant", [{"type": "text", "text": "Done."}])
    store.set_container(sid, "cont_old")
    events: list[dict[str, Any]] = []
    A.Agent(FakeReads(), store, client).ask(sid, "u1", "How many trades? 3?", events.append)  # type: ignore[arg-type]
    assert sent["containers"] == ["cont_old", None]  # refused, then a new container
    assert any(e["type"] == "notice" for e in events)
    b = sent["body"]
    assert b["model"] == "claude-opus-5-5" and b["thinking"] == {"type": "adaptive", "display": "updates"}
    assert b["output_config"]["task_budget"]["type"] == "tokens" and b["fallbacks"] == "default"
    assert b["tools"][0] == T.CODE_EXECUTION and b["tools"][1]["allowed_callers"] == [T.CALLER]
    assert b["stream"] is True and [m["role"] for m in b["messages"]] == ["user", "assistant", "user", "system"]
    assert all(x in sent["beta"] for x in A.BETAS)
    assert [e for e in events if e["type"] == "answer.card"][0]["text"] == "Observed: 3 trades."
    assert store.session(sid, "u1")["container"] == "cont_9"  # type: ignore[index]


# ---- runs cut off: a restart, the wall clock, a shutdown ----


class FakeTimer:
    """The watchdog's timer, fired by the test: a faked clock."""

    made: list[FakeTimer] = []

    def __init__(self, interval: float, fn: Any, args: tuple[Any, ...] = ()) -> None:
        self.interval, self.fn, self.args, self.daemon, self.cancelled = interval, fn, args, False, False
        FakeTimer.made.append(self)

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.fn(*self.args)


class BlockedModel:
    """A model request that never answers on its own: it ends only when the run closes its stream."""

    def __init__(self) -> None:
        self.entered, self.closed, self.requests = threading.Event(), threading.Event(), 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw: Any) -> Any:
        self.requests += 1
        model = self

        class Ctx:
            def __enter__(self) -> Any:
                return self

            def __exit__(self, *a: Any) -> None:
                pass

            def close(self) -> None:
                model.closed.set()

            def get_final_message(self) -> Any:
                model.entered.set()
                model.closed.wait(30)
                raise httpx.ReadError("stream closed")

        return Ctx()


def _session_with_findings() -> tuple[Store, str]:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    store.add_finding(sid, {"label": "observed", "title": "Two-sided in 93 of 94 windows", "counts": True,
                            "stat": {"text": "93 of 94 windows"}})  # fmt: skip
    store.add_finding(sid, {"label": "inferred", "title": "Seems to buy once the outcome looks settled", "counts": True})
    store.add_finding(sid, {"label": "observed", "title": "Made-up", "counts": False})
    return store, sid


def _asking(agent: A.Agent, sid: str, events: list[dict[str, Any]]) -> threading.Thread:
    t = threading.Thread(target=agent.ask, args=(sid, "u1", "Go", events.append), daemon=True)
    t.start()
    return t


def _worker(run: int) -> threading.Thread | None:
    return next((t for t in threading.enumerate() if t.name == f"research-run-{run}"), None)


def test_the_watchdog_ends_a_run_blocked_on_the_model_at_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """RESEARCH_MAX_SECONDS is a wall clock, not a check between rounds: a request that never comes back still ends
    the run at the limit, with its findings as a partial answer."""
    FakeTimer.made.clear()
    store, sid = _session_with_findings()
    model = BlockedModel()
    agent = A.Agent(FakeReads(), store, model)  # type: ignore[arg-type]
    agent.timer = FakeTimer
    events: list[dict[str, Any]] = []
    asking = _asking(agent, sid, events)
    assert model.entered.wait(5)
    timer = FakeTimer.made[-1]
    assert timer.interval == pytest.approx(A.MAX_SECONDS, abs=1)  # set for the whole budget from the start
    asking.join(0.3)
    assert asking.is_alive() and "done" not in [e["type"] for e in events]  # nothing ends it but the clock
    timer.fire()  # the limit
    asking.join(5)
    assert not asking.is_alive()
    kinds = [e["type"] for e in events]
    assert kinds[-4:] == ["answer.card", "notice", "usage", "done"] and "error" not in kinds
    card = events[kinds.index("answer.card")]
    assert card["partial"] and card["finding_ids"] == ["F1", "F2"]
    assert card["observed"] == ["Two-sided in 93 of 94 windows: 93 of 94 windows"]
    assert card["inferred"] == ["Seems to buy once the outcome looks settled"]
    assert "10-minute limit" in events[kinds.index("notice")]["text"]
    assert model.closed.is_set()  # the blocked request was closed, not left running
    run = store.runs()[0]
    assert run["error"] == "over_time" and run["ended"]
    w = _worker(events[0]["run"])
    if w:
        w.join(5)
    assert [m["role"] for m in store.messages(sid)] == ["user"]  # nothing of the stopped turn was kept
    assert len(events) == len(kinds)  # nothing after done


def test_the_watchdog_ends_a_run_blocked_on_a_read_and_the_read_returning_later_adds_nothing() -> None:
    FakeTimer.made.clear()
    store, sid = _session_with_findings()
    release, reading = threading.Event(), threading.Event()

    class SlowReads(FakeReads):
        def wallet_trades(self, *a: Any) -> dict[str, Any]:
            reading.set()
            release.wait(30)
            return super().wallet_trades(*a)

    model = _model(_calls_tool(), _answers("Observed: 3 trades."))
    agent = A.Agent(SlowReads(), store, model)  # type: ignore[arg-type]
    agent.timer = FakeTimer
    events: list[dict[str, Any]] = []
    asking = _asking(agent, sid, events)
    assert reading.wait(5)
    FakeTimer.made[-1].fire()
    asking.join(5)
    assert not asking.is_alive() and events[-1]["type"] == "done"
    n_events, n_messages = len(events), len(store.messages(sid))
    release.set()  # the read comes back after the run ended
    w = _worker(events[0]["run"])
    if w:
        w.join(5)
    assert len(events) == n_events and len(store.messages(sid)) == n_messages and len(model.requests) == 1
    # the conversation ends on the agent's call: the next question answers it as not run, then goes on
    agent.timer = threading.Timer
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "Ask again", lambda e: None)  # type: ignore[arg-type]
    last = model.requests[1]["messages"][-1]
    assert [b["type"] for b in last["content"]] == ["tool_result", "text"]
    assert last["content"][0]["tool_use_id"] == "tu_1" and last["content"][0]["is_error"]
    assert last["content"][0]["content"] == A.NOT_RUN and last["content"][1]["text"] == "Ask again"


def test_a_run_the_last_process_died_in_ends_as_interrupted_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """10 Nov ~17:00 UTC: a deploy replaced the container mid-run. At the next start the run gets its findings as a
    partial answer, the interrupted notice and done, so the page never stays "Working"."""
    from fastapi.testclient import TestClient

    from signals.research import server

    store, sid = _session_with_findings()
    run = store.start_run(sid, "u1")  # the killed process's run: never ended
    store.add_event(sid, {"type": "ask.started", "v": 2, "run": run, "ask_id": run, "text": "Go", "context": None})
    store.add_event(sid, {"type": "finding.added", "v": 2, "run": run, "finding_id": "F1"})
    other = store.new_session("u2")  # a session whose cut-off run was followed by a finished one
    old = store.start_run(other, "u2")
    newer = store.start_run(other, "u2")
    store.update_run(newer, ended=time.time())
    monkeypatch.setattr(server, "store", store)
    with TestClient(server.app):  # startup
        pass
    evs = store.events(sid)
    assert [e["type"] for e in evs] == ["ask.started", "finding.added", "answer.card", "notice", "done"]
    card, notice = evs[2], evs[3]
    assert card["partial"] and card["finding_ids"] == ["F1", "F2"] and card["run"] == run and card["v"] == A.EVENT_VERSION
    assert notice["text"] == "This breakdown was interrupted by an update. Ask again to finish it."
    assert store.events(other) == []  # a later run went on: only closed in the store
    ended = {r["id"]: r for r in store.runs()}
    assert ended[run]["error"] == "interrupted" and ended[run]["ended"] and ended[old]["error"] == "interrupted"
    assert A.recover(store) == 0  # once only
    server.app.dependency_overrides[server.auth.user_of] = lambda: "u1"
    try:
        s = TestClient(server.app).get(f"/api/research/sessions/{sid}").json()
    finally:
        server.app.dependency_overrides.clear()
    assert s["running"] is False and s["events"][-1]["type"] == "done"


def test_an_interrupted_run_without_findings_still_says_so() -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    sid = store.new_session("u1")
    run = store.start_run(sid, "u1")
    assert A.recover(store) == 1
    assert [(e["type"], e.get("text")) for e in store.events(sid)] == [("notice", A.INTERRUPTED), ("done", None)]
    assert store.events(sid)[0]["run"] == run


def test_sigterm_ends_running_breakdowns_then_hands_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """Railway's SIGTERM: running breakdowns write where they got to and end before uvicorn's own handler runs."""
    import signal

    from signals.research import server

    store, sid = _session_with_findings()
    model = BlockedModel()
    agent = A.Agent(FakeReads(), store, model)  # type: ignore[arg-type]
    monkeypatch.setattr(server, "_agent", agent)
    events: list[dict[str, Any]] = []
    asking = _asking(agent, sid, events)
    assert model.entered.wait(5)
    handed: list[int] = []
    original = signal.signal(signal.SIGTERM, lambda sig, frame: handed.append(sig))  # stands in for uvicorn's
    try:
        server._on_sigterm()
        signal.raise_signal(signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, original)
    assert handed == [signal.SIGTERM]
    asking.join(5)
    assert not asking.is_alive()
    kinds = [e["type"] for e in events]
    assert kinds[-4:] == ["answer.card", "notice", "usage", "done"]
    assert events[kinds.index("notice")]["text"] == A.INTERRUPTED
    assert store.runs()[0]["error"] == "interrupted"
    assert A.recover(store) == 0  # already closed: nothing for the next start
