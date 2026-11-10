"""The agent's five tools. Each is called from the agent's code in Anthropic's code-execution sandbox
(programmatic tool calling: ``allowed_callers``), so thousands of trades go to its code, never into the chat. In
the sandbox each tool is an async function taking one dict and returning a JSON string.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from signals.research.data import ReadError, Reads

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
            "slug_prefix keeps only matching markets (default 'btc-updown-15m-'; null for every market). A busy "
            "wallet can have thousands of trades a day: read a day or a few days at a time."
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
            "trades in this market), book: {available, why} (order books: not connected yet), coverage: {source, "
            "price_step_s, price_points, largest_price_gap_s, trades_read, trades_complete, note}}. When read from "
            "Layer's recordings it also has recording_notes: say so when coverage shows gaps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "condition_id": {"type": "string"}},
        },
    },
    {
        "name": "outside_prices",
        "description": (
            "Prices outside Polymarket between start and end. source 'binance': Binance spot candles' close "
            "(BTCUSDT), 1-second steps for up to an hour, 1-minute steps up to 2 days. source 'chainlink': Chainlink "
            "BTC/USD (what windows settle on) where Layer recorded it. JSON: {source, symbol, start, end, available, "
            "why (when not available), step, points: [[ts unix s, price]]}. Binance is a different market from "
            "Chainlink: never call one the other."
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
        save_chart: Callable[[str, dict[str, Any], str | None], str]) -> tuple[str, bool, dict[str, Any]]:  # fmt: skip
    """Runs one tool: (the text the agent's code gets, whether it failed, a short summary for the event stream)."""
    t0 = time.monotonic()
    try:
        if name == "wallet_trades":
            out = reads.wallet_trades(inp.get("wallet", ""), inp.get("start"), inp.get("end"),
                                      inp.get("slug_prefix", "btc-updown-15m-"))  # fmt: skip
            summary = {k: out[k] for k in ("count", "windows", "complete")}
        elif name == "wallet_profile":
            out = reads.wallet_profile(inp.get("wallet", ""))
            summary = {"name": (out.get("record") or {}).get("name"), "missing": out.get("missing")}
        elif name == "window":
            out = reads.window(inp.get("slug"), inp.get("condition_id"))
            summary = {"slug": out.get("slug"), "result": out.get("result"), "coverage": out.get("coverage")}
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
