"""The agent's data tools (wallet_trades, wallet_profile, window, market, wallet_markets, outside_prices, and
make_chart). Each is called from the agent's code in Anthropic's code-execution sandbox
(programmatic tool calling: ``allowed_callers``), so thousands of trades go to its code, never into the chat. In
the sandbox each tool is an async function taking one dict and returning a JSON string.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from signals.research.data import ReadError, Reads, complete_slugs, unix
from signals.research.markets import is_window

CALLER = "code_execution_20260120"
CODE_EXECUTION = {"type": CALLER, "name": "code_execution"}
MAX_CHART_BYTES = 1_500_000
TIME = {"type": ["integer", "string"], "description": "Unix seconds (UTC) or an ISO time like 2026-11-09T14:00:00Z."}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "wallet_trades",
        "description": (
            "A Polymarket wallet's trades between start and end, oldest first. Returns JSON: {wallet, start, end, "
            "slug_prefix, count, windows (distinct markets), complete (false = partial: it stopped at 30,000 trades "
            "of every market and read nothing after read_to; tell the user and read on from read_to if needed), "
            "read_to (unix s), source, note, trades: [{id (stable: cite it for the trades a finding rests on), "
            "ts (unix s, block time), slug (e.g. btc-updown-15m-1794285000, "
            "whose last part is the window's start in unix s), condition_id, outcome ('Up'/'Down'), outcome_index, "
            "token, action ('buy'/'sell'), price (0-1, dollars per contract), size (contracts), usd, tx}]}. "
            "slug_prefix keeps only matching markets (default 'btc-updown-15m-'; null for every market, e.g. "
            "long-dated markets, whose outcomes are 'Yes'/'No'). A busy wallet can have thousands of trades a day: "
            "read a day or a few days at a time. For a market type's markets ranked by money, use wallet_markets; "
            "for one market's every fill over its whole life, use market."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wallet": {"type": "string", "description": "0x address, 40 hex characters."},
                "start": TIME, "end": TIME,
                "slug_prefix": {"type": ["string", "null"], "default": "btc-updown-15m-"},
            },  # fmt: skip
            "required": ["wallet", "start", "end"],
        },
    },
    {
        "name": "wallet_profile",
        "description": (
            "A wallet's record from Signals: JSON {wallet, source, record: {name, joined, stats: {trading_pnl, "
            "realized_pnl, unrealized_pnl, volume_usd, trades, markets_traded, biggest_win, pnl_as_of}, open, "
            "categories}, account: {positions_usd, cash_usd, total_usd, complete}, missing: [what couldn't be read]}. "
            "All-time and across every market, not only BTC 15m: Polymarket's own figures."
        ),
        "input_schema": {"type": "object", "properties": {"wallet": {"type": "string"}}, "required": ["wallet"]},
    },
    {
        "name": "window",
        "description": (
            "One crypto Up/Down window (market), by slug or condition_id. JSON: {slug, condition_id, title, start, end "
            "(unix s), start_iso, end_iso, price_to_beat (Chainlink BTC/USD at the start: the price to beat), "
            "final_price (Chainlink at the end), result ('Up'/'Down', null while open), closed, resolution_source, "
            "tokens: {Up: id, Down: id}, prices: {Up: [[ts, price]], Down: [[ts, price]]} (Polymarket's price "
            "history, about 1 point a minute), trades: [{ts, wallet, outcome, action, price, size, tx}] (everyone's "
            "trades in this market), book: {available, why}, coverage: {source, price_step_s, price_points, "
            "largest_price_gap_s, trades_read, trades_complete, note}}. When Layer recorded the window (source "
            "starts 'Layer recording') it has more: prices at every change (the middle of best bid and ask), "
            "best_prices [{receive_ms, up_bid, up_ask, down_bid, down_ask}], book {available: true, rows: [{unix_s, "
            "up_bids, up_asks, down_bids, down_asks}] top 10 [[price, size]]}, chainlink and binance [[unix_s, "
            "price]], chainlink_at_start/at_end, result_from_chainlink, trades with stream_ms, and the recording's "
            "coverage {usable, reasons, book: {secondsWithoutBook, of, largestSilenceS, lost}, trades: {pct, ...}} "
            "plus recording_notes. Say so when coverage isn't usable or has gaps. Prefer its chainlink and binance "
            "over outside_prices for that window."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "condition_id": {"type": "string"}},
        },
    },
    {
        "name": "wallet_markets",
        "description": (
            "A wallet's markets of one market type (e.g. 'btc-long': long-dated BTC price markets) traded between "
            "start and end, the most money traded first: the same list Start's tiles are built from. JSON: {wallet, "
            "start, end, market_type, label, min_days (only markets that run at least this long, listing to end "
            "date), top, trades_read, trades_complete (false: read newest first, it stopped at 30,000 trades, so only "
            "start onward was read, later than you asked: say so), start (how far back it read), asked_from, read_to, markets_traded, markets_looked_at, matched, markets: [{slug, condition_id, question, "
            "event_slug, event_title (strikes of one event share it), start_iso, end_iso, runs_days, closed, result, "
            "rule {kind, strike, source, says}, usd_in_range, fills_in_range, first_fill_in_range, "
            "last_fill_in_range}], note}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wallet": {"type": "string"}, "start": TIME, "end": TIME,
                "market_type": {"type": "string", "description": "A market type id, e.g. 'btc-long'."},
                "min_days": {"type": "number"}, "top": {"type": "integer"},
            },  # fmt: skip
            "required": ["wallet", "start", "end", "market_type"],
        },
    },
    {
        "name": "market",
        "description": (
            "One market that isn't a 15-minute window (e.g. 'Will Bitcoin reach $100,000 by December 31, 2026?'), "
            "for the breakdown's wallet, by slug: the replay the page draws, built from the data. JSON: {kind "
            "'market', window_id (the slug), market_type, title (the question), event_slug, event_title, "
            "market_start, market_end, closed, closed_at, result ('Yes'/'No', null while open), rule {kind "
            "(touch_high | touch_low | close_above | close_below | all_time_high | other), strike, source, says}, "
            "rules (the market's own resolution text: quote it rather than assume), outcomes, prices {Yes: [{t, p}], "
            "No: [...]} (p 0-1, one point per coverage.price_step_s), outside {name 'Binance BTCUSDT', unit, step, "
            "points [{t, p}] (closes), ranges [{t, h, l}] (each candle's high and low), highest {t, high}, lowest "
            "{t, low}} or null, trades [{trade_id, t, side (the outcome), action, shares, price, usd, outside (the "
            "outside line's close at or before the fill)}] (every fill over the market's whole life), position "
            "[{t, held: {Yes, No}}], hold {from, to, days, still_held}, value {cost, sold_for, held, payout, "
            "value_now, last_prices, profit, profit_kind: resolved | closed (sold out before the end) | open (valued "
            "at the latest price, not a result)}, coverage {price_step_s, fills_complete, bought_before_read, "
            "outside, outside_step, notes}}. Times are unix seconds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "outside_prices",
        "description": (
            "Prices outside Polymarket between start and end. source 'binance': BTC priced in USDT (Tether) on "
            "Binance spot, candle close, 1-second steps for up to an hour, 1-minute steps up to 2 days, hourly candles up to "
            "120 days and daily beyond, those with ranges [[ts, high, low]] and the span's highest and lowest (exact "
            "for 'did BTC touch $X': a candle's high covers every minute in it). source "
            "'chainlink': Chainlink BTC/USD (US dollars: what windows settle on, and the price to beat is its "
            "60-second average) where Layer recorded it, from 10 Nov 2026 05:27 UTC. JSON: {source, symbol, unit, "
            "start, end, available, why (when not available), step, points: [[ts unix s, price]]}. Different units: "
            "Binance usually sits about 0.1% from Chainlink, so never compare a Binance price to the price to beat. "
            "To judge 'BTC above the start', use Chainlink where recorded; otherwise measure Binance against its own "
            "value at the window's start, and say so."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["binance", "chainlink"]},
                "start": TIME, "end": TIME, "symbol": {"type": "string", "default": "BTC"},
            },  # fmt: skip
            "required": ["source", "start", "end"],
        },
    },
    {
        "name": "make_chart",
        "description": (
            "Shows a chart to the user beside your answer. spec is a Vega-Lite v5 spec with its data inline "
            "(data.values; no data.url, no images or links). Use temporal x fields as ISO strings or ms. Layer or "
            "vconcat panels that share an x axis (e.g. BTC prices with the price to beat and entry markers, then "
            "Up/Down prices, then the position as a step line). Returns JSON {chart_id, title, rows}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "spec": {"type": "object", "description": "Vega-Lite v5 spec with inline data."},
                "caption": {"type": "string", "description": "One plain sentence: what the chart shows."},
            },
            "required": ["title", "spec"],
        },
    },
]
for _t in TOOLS:
    _t["allowed_callers"] = [CALLER]


def _forbidden(node: Any, path: str = "spec") -> str | None:
    """Where a spec would load or link to something outside itself, or None."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("url", "href", "image") and isinstance(v, str):
                return f"{path}.{k}"
            if (bad := _forbidden(v, f"{path}.{k}")) is not None:
                return bad
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if (bad := _forbidden(v, f"{path}[{i}]")) is not None:
                return bad
    return None


def _rows(node: Any) -> int:
    if isinstance(node, dict):
        return sum((len(v) if k == "values" and isinstance(v, list) else _rows(v)) for k, v in node.items())
    if isinstance(node, list):
        return sum(_rows(v) for v in node)
    return 0


def chart(inp: dict[str, Any], save: Callable[[str, dict[str, Any], str | None], str]) -> dict[str, Any]:
    spec, title = inp.get("spec"), str(inp.get("title") or "").strip()
    if not isinstance(spec, dict) or not title:
        raise ReadError("make_chart needs a title and a Vega-Lite spec (an object).")
    if (bad := _forbidden(spec)) is not None:
        raise ReadError(f"Charts must hold their own data: remove {bad}.")
    if len(json.dumps(spec)) > MAX_CHART_BYTES:
        raise ReadError("That chart's data is too big (over 1.5 MB): downsample it (e.g. one point per second).")
    rows = _rows(spec)
    if not rows:
        raise ReadError("The spec has no inline data (data.values).")
    spec = {"$schema": "https://vega.github.io/schema/vega-lite/v5.json", **spec}
    return {"chart_id": save(title, spec, inp.get("caption")), "title": title, "rows": rows}


def run(name: str, inp: dict[str, Any], reads: Reads,
        save_chart: Callable[[str, dict[str, Any], str | None], str], *,
        store: Any = None, sid: str | None = None) -> tuple[str, bool, dict[str, Any]]:  # fmt: skip
    """Runs one tool: (the text the agent's code gets, whether it failed, a short summary for the event stream).
    With ``store``/``sid``, what it reads is kept on the investigation, so the case file draws from the same rows."""
    t0 = time.monotonic()
    keep = store is not None and sid is not None
    try:
        if name == "wallet_trades":
            out = reads.wallet_trades(inp.get("wallet", ""), inp.get("start"), inp.get("end"),
                                      inp.get("slug_prefix", "btc-updown-15m-"))  # fmt: skip
            summary = {"rows": out["count"], "windows": out["windows"], "complete": out["complete"],
                       "limit_hit": not out["complete"]}  # fmt: skip
            if keep:
                store.set_wallet(sid, out["wallet"])
                store.add_trades(sid, out["trades"])
                # windows this range covered whole; one it cut through is read again before it gets a tile
                store.mark_complete(sid, complete_slugs(out, unix(inp.get("start")), unix(inp.get("end"))))
        elif name == "wallet_profile":
            out = reads.wallet_profile(inp.get("wallet", ""))
            summary = {"name": (out.get("record") or {}).get("name"), "missing": out.get("missing")}
        elif name == "window":
            out = reads.window(inp.get("slug"), inp.get("condition_id"))
            summary = {"slug": out.get("slug"), "result": out.get("result"), "coverage": out.get("coverage")}
            if keep and out.get("slug"):
                store.put_window(sid, out["slug"], read=out)
        elif name == "wallet_markets":
            out = reads.wallet_markets(inp.get("wallet", ""), inp.get("start"), inp.get("end"),
                                       inp.get("market_type", ""), inp.get("min_days"), inp.get("top"))  # fmt: skip
            if keep:
                store.set_wallet(sid, out["wallet"])
            summary = {"rows": len(out["markets"]), "matched": out["matched"], "complete": out["trades_complete"],
                       "limit_hit": not out["trades_complete"]}  # fmt: skip
        elif name == "market":
            slug = str(inp.get("slug") or "").strip()
            if not slug:
                raise ReadError("Give the market's slug.")
            if is_window(slug):
                raise ReadError("That's a 15-minute window: use the window tool for it.")
            if not keep or not (store.session_any(sid) or {}).get("wallet"):
                raise ReadError("Read the wallet's trades first (wallet_trades or wallet_markets), so the market's "
                                "replay has a wallet.")  # fmt: skip
            from signals.research import workspace

            out = workspace.build(store, reads, sid, slug)
            summary = {"slug": slug, "result": out.get("result"), "fills": len(out["trades"]),
                       "profit_kind": out["value"]["profit_kind"]}  # fmt: skip
        elif name == "outside_prices":
            out = reads.outside_prices(inp.get("source", ""), inp.get("start"), inp.get("end"), inp.get("symbol") or "BTC")
            summary = {"source": out.get("source"), "available": out.get("available"), "points": len(out.get("points") or [])}
        elif name == "make_chart":
            out = chart(inp, save_chart)
            summary = out
        else:
            raise ReadError(f"There's no tool called {name}.")
    except ReadError as e:
        return f"Error: {e}", True, {"error": str(e)}
    except Exception as e:  # a venue or network failure: tell the agent's code, which can retry or say so
        return f"Error: {type(e).__name__}: {e}"[:600], True, {"error": type(e).__name__}
    summary["ms"] = round((time.monotonic() - t0) * 1000)
    return json.dumps(out, separators=(",", ":"), default=str), False, summary
