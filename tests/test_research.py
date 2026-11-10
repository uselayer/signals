"""The research agent (signals/research): its reads, its number check, its loop (with a scripted model), the server."""

from __future__ import annotations

import copy
import json
import os
import tempfile
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
    assert row.pop("id") == D.trade_id(row)
    assert row == {"ts": 100, "slug": SLUG, "condition_id": "0xc", "outcome": "Down", "outcome_index": 1,
                   "token": "7", "action": "sell", "price": 0.6, "size": 10.0, "usd": 6.0, "tx": "0xt"}  # fmt: skip


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
    "coverage": {"usable": True, "reasons": [], "book": {"secondsWithoutBook": 3, "of": 900}},
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


def test_chainlink_says_it_isnt_readable_yet() -> None:
    out = D.Reads(None, _web(lambda r: httpx.Response(500))).outside_prices("chainlink", 0, 900)
    assert not out["available"] and "price_to_beat" in out["why"]


def test_times_parse() -> None:
    assert D.unix("2026-11-10T04:30:00Z") == D.unix("2026-11-10T04:30:00") == D.unix("1794285000") == 1794285000
    with pytest.raises(D.ReadError):
        D.unix("yesterday")


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
        return {"count": 3, "windows": 2, "complete": True, "trades": [{"price": 0.42}]}


class Model:
    """A scripted Claude: each request gets the next response; requests are kept."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses, self.requests = list(responses), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw: Any) -> Any:
        self.requests.append(copy.deepcopy(kw))
        return Model._Ctx(self.responses.pop(0))

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


def _calls_tool() -> dict[str, Any]:
    return {"stop_reason": "tool_use", "usage": USAGE, "container": {"id": "cont_1"}, "content": [
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
    assert kinds == ["start", "progress", "code", "tool_call", "tool_result", "code_result", "check", "answer", "usage", "done"]
    second = model.requests[1]
    assert second["container"] == "cont_1"  # the paused code's container
    assert [b["type"] for b in second["messages"][-1]["content"]] == ["tool_result"]  # only tool results
    assert json.loads(second["messages"][-1]["content"][0]["content"])["count"] == 3
    assert model.requests[0]["tools"][0] == T.CODE_EXECUTION and model.requests[0]["fallbacks"] == "default"
    answer = events[kinds.index("answer")]
    assert answer["unverified"] == [] and events[kinds.index("check")]["ok"]
    run = store.runs()[0]
    assert run["check_ok"] == 1 and run["rounds"] == 2 and run["tool_calls"] == 1
    assert run["cost_usd"] == pytest.approx(2 * (1000 * 4 + 500 * 20) / 1e6)
    assert store.session(sid, "u1")["container"] == "cont_1"  # type: ignore[index]
    assert all(e["v"] == A.EVENT_VERSION and e["run"] == run["id"] for e in events)


def test_a_follow_up_replays_the_conversation_and_container() -> None:
    model = _model(_calls_tool(), _answers("Observed: 3 trades."), _answers("Observed: 2 windows.", stdout="2"))
    _, store, sid = _ask(model)
    A.Agent(FakeReads(), store, model).ask(sid, "u1", "And windows?", lambda e: None)  # type: ignore[arg-type]
    third = model.requests[2]
    assert third["container"] == "cont_1" and third["messages"][0]["content"][0]["text"] == "Analyze it"
    assert third["messages"][-1]["content"][0]["text"] == "And windows?"


def test_an_untraced_number_gets_one_retry() -> None:
    model = _model(_calls_tool(), _answers("It made $99.99."), _answers("Observed: 3 trades."))
    events, _, _ = _ask(model)
    checks = [e for e in events if e["type"] == "check"]
    assert checks[0]["unmatched"] == ["$99.99"] and checks[0]["retrying"] and checks[1]["ok"]
    assert "$99.99" in model.requests[2]["messages"][-1]["content"][0]["text"]
    assert [e for e in events if e["type"] == "answer"][0]["text"] == "Observed: 3 trades."


def test_still_untraced_after_the_retry_is_shown_flagged() -> None:
    model = _model(_calls_tool(), _answers("It made $99.99."), _answers("It made $98.00."))
    events, store, _ = _ask(model)
    answer = [e for e in events if e["type"] == "answer"][0]
    assert answer["unverified"] == ["$98.00"] and store.runs()[0]["check_ok"] == 0


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


def test_a_refusal_ends_with_a_sentence() -> None:
    events, _, _ = _ask(_model({"stop_reason": "refusal", "usage": USAGE, "content": []}))
    assert [e["message"] for e in events if e["type"] == "error"] == ["The model declined this request."]


# ---- the server ----


def test_server_sessions_are_their_owners(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from signals.research import server

    monkeypatch.setattr(server, "store", Store(os.path.join(tempfile.mkdtemp(), "s.db")))

    class Fake:
        def ask(self, sid: str, user: str, q: str, emit: Any) -> None:
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


def test_the_request_through_the_real_anthropic_sdk() -> None:
    """The loop's request as the anthropic SDK sends it (body, beta headers) and a streamed reply parsed back."""
    import anthropic
    import httpx2  # the anthropic SDK's own HTTP package (2.x)

    sent: dict[str, Any] = {}

    def sse(*events: tuple[str, dict[str, Any]]) -> str:
        return "".join(f"event: {name}\ndata: {json.dumps(body)}\n\n" for name, body in events)

    def handler(req: Any) -> Any:
        sent["body"], sent["beta"] = json.loads(req.content), req.headers.get("anthropic-beta", "")
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
    events: list[dict[str, Any]] = []
    A.Agent(FakeReads(), store, client).ask(sid, "u1", "How many trades? 3?", events.append)  # type: ignore[arg-type]
    b = sent["body"]
    assert b["model"] == "claude-opus-5-5" and b["thinking"] == {"type": "adaptive", "display": "updates"}
    assert b["output_config"]["task_budget"]["type"] == "tokens" and b["fallbacks"] == "default"
    assert b["tools"][0] == T.CODE_EXECUTION and b["tools"][1]["allowed_callers"] == [T.CALLER]
    assert b["stream"] is True and len(b["messages"]) == 3
    assert all(x in sent["beta"] for x in A.BETAS)
    assert [e for e in events if e["type"] == "answer"][0]["text"] == "Observed: 3 trades."
    assert store.session(sid, "u1")["container"] == "cont_9"  # type: ignore[index]
