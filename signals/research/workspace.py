"""What the case file draws, built by the server from the data (never by the model): one window's replay
(``window.ready``), its overview tile (``window.summary``) and its coverage. The agent decides which window to show
and how to tag it; every series, trade and position here comes from the reads themselves.

Shapes are the UI-to-agent contract's (docs/research-contract.md): times in unix seconds, ``t`` on every point.
"""

from __future__ import annotations

import bisect
from datetime import datetime
from typing import Any

from signals.research.data import OUTSIDE_FROM, UNUSABLE, trade_id

SPARK_POINTS = 60  # a tile's line: one Binance point every 15 s of a 15-minute window
PAD_S = 30  # the time axis starts this long before the earlier of the window's start and the first fill
AFTER_S = 60  # and ends this long after the window's end
PRE_OPEN_MAX_S = 1_800  # at most this long before the start: earlier fills count in the position, off the axis


def axis(start: int, end: int, trades: list[dict[str, Any]]) -> tuple[int, int]:
    """The replay's time span: from just before the window opens, or before the wallet's first fill when it
    traded earlier (windows are listed about a day ahead; at most PRE_OPEN_MAX_S before), to a minute after."""
    first = max(min((int(t["ts"]) for t in trades), default=start), start - PRE_OPEN_MAX_S)
    return min(start, first) - PAD_S, end + AFTER_S


def _secs(x: Any) -> float:
    """Unix seconds from what Layer's recording writes: an ISO time ("2026-11-09T04:45:14.181Z"), ms or s."""
    if isinstance(x, str) and not x.replace(".", "", 1).isdigit():
        return datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
    v = float(x or 0)
    return v / 1000 if v > 1e11 else v


def _points(rows: list[list[float]] | None) -> list[dict[str, float]]:
    return [{"t": int(t), "p": float(p)} for t, p in rows or []]


def _per_second(best: list[dict[str, Any]], side: str, start: int, end: int) -> list[dict[str, Any]]:
    """One side's best bid and ask at every second from ``start`` to ``end``, carried forward from each change
    (the recording keeps a row per change). Seconds before the first change are left out."""
    rows = sorted(((int(r.get("receive_ms") or 0) / 1000, r) for r in best), key=lambda x: x[0])
    out, i, last = [], 0, None
    for t in range(start, end + 1):
        while i < len(rows) and rows[i][0] <= t:
            last = rows[i][1]
            i += 1
        if last is not None:
            out.append({"t": t, "bid": last.get(f"{side}_bid"), "ask": last.get(f"{side}_ask")})
    return out


def _ask_at(best: list[dict[str, Any]], side: str, ms: float) -> float | None:
    """The best ask on ``side`` just before ``ms`` (receive time), or None."""
    times = [float(r.get("receive_ms") or 0) for r in best]
    i = bisect.bisect_left(times, ms) - 1
    return best[i].get(f"{side}_ask") if i >= 0 else None


def fills(trades: list[dict[str, Any]], window: dict[str, Any]) -> list[dict[str, Any]]:
    """The wallet's own fills in this window (from ``wallet_trades``, never matched off the market tape, where a
    maker's fills show under the taker's wallet), as the replay draws them. ``paid_ask``: a buy at or above the
    recorded best ask just before the trade reached the stream (its time from the tape, matched by transaction);
    null when there's no recorded book or the trade isn't on the tape, and for sells."""
    best = sorted(window.get("best_prices") or [], key=lambda r: float(r.get("receive_ms") or 0))
    stream_ms = {r.get("tx"): r.get("stream_ms") for r in window.get("trades") or [] if r.get("stream_ms")}
    out = []
    for r in sorted(trades, key=lambda r: (r["ts"], r.get("tx") or "")):
        paid = None
        side = (r.get("outcome") or "").lower()
        if best and r["action"] == "buy" and side in ("up", "down") and stream_ms.get(r.get("tx")):
            ask = _ask_at(best, side, float(stream_ms[r["tx"]]))
            paid = None if ask is None else float(r["price"]) >= float(ask) - 1e-9
        out.append({"trade_id": r.get("id") or trade_id(r.get("tx"), r.get("token"), r["action"], r["price"],
                                                        r["size"], r["ts"]),
                    "t": r["ts"], "side": r.get("outcome"), "action": r["action"], "shares": r["size"],
                    "price": r["price"], "usd": r.get("usd"), "paid_ask": paid,
                    "pre_open": int(r["ts"]) < int(window["start"])})  # fmt: skip
    return out


def position(fs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shares held of each side after each fill (a step line)."""
    up = down = 0.0
    out = []
    for f in fs:
        d = f["shares"] if f["action"] == "buy" else -f["shares"]
        if f["side"] == "Up":
            up += d
        elif f["side"] == "Down":
            down += d
        if out and out[-1]["t"] == f["t"]:
            out.pop()
        out.append({"t": f["t"], "up": round(up, 6), "down": round(down, 6)})
    return out


def coverage(window: dict[str, Any]) -> dict[str, Any]:
    """What this window's data covers, for hatching and "left out of counts"."""
    start, end = int(window["start"]), int(window["end"])
    rec = window.get("coverage") or {}
    recorded = str(window.get("source") or "").startswith("Layer recording")
    book = (rec.get("book") or {}) if recorded else {}
    trades = (rec.get("trades") or {}) if recorded else {}
    has_chainlink = bool(window.get("chainlink")) and start >= OUTSIDE_FROM
    outage = any(a < end and start < b for a, b in UNUSABLE) or (recorded and rec.get("usable") is False)
    return {
        "window_id": window.get("slug"), "source": window.get("source") or "Polymarket API",
        "chainlink": "full" if has_chainlink else "start_and_result",
        "book": bool(recorded and (window.get("book") or {}).get("available")),
        "missing_seconds": [[round(_secs(x.get("from"))), round(_secs(x.get("to")) - _secs(x.get("from")), 1)]
                            for x in book.get("lost") or []] if recorded else None,
        "lost": [{"from": round(_secs(x.get("from")), 1), "to": round(_secs(x.get("to")), 1), "why": x.get("why")}
                 for x in book.get("lost") or []] if recorded else None,
        "seconds_without_book": book.get("secondsWithoutBook"),
        "market_trades": {"recorded": trades.get("onStream"), "polymarket": trades.get("dataApi"),
                          "pct": trades.get("pct")} if recorded
        else {"read": (window.get("coverage") or {}).get("trades_read"), "complete": (window.get("coverage") or {})
              .get("trades_complete")},
        "outage": bool(outage), "reasons": rec.get("reasons") or [] if recorded else [],
        "notes": window.get("recording_notes") or [],
    }  # fmt: skip


def ready(window: dict[str, Any], trades: list[dict[str, Any]], binance: list[list[float]] | None,
          tags: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """``window.ready``: the synchronized replay of one window for one wallet. ``window`` is a ``Reads.window``
    answer, ``trades`` the wallet's fills in it, ``binance`` [[t, price]] when the window has none of its own."""
    start, end = int(window["start"]), int(window["end"])
    best = window.get("best_prices") or []
    fs = fills(trades, window)
    has_book = bool(best)
    a, b = axis(start, end, trades)
    cov = coverage(window)
    pre = [f for f in fs if f["pre_open"]]
    cov["pre_open_entries"] = {"fills": len(pre), "first_s_before": (start - pre[0]["t"]) if pre else None,
                               "before_axis": sum(f["t"] < a for f in pre)}  # fmt: skip
    if pre and best:
        first_book = min(float(r.get("receive_ms") or 0) for r in best) / 1000
        if first_book > pre[0]["t"]:
            cov["notes"] = [*cov["notes"], f"Its first fill came {round(first_book - pre[0]['t'])} s before the "
                            "recording of this window's book begins."]  # fmt: skip
    return {
        "window_id": window.get("slug"), "start": start, "end": end, "axis": {"from": a, "to": b},
        "title": window.get("title"),
        "price_to_beat": window.get("price_to_beat"), "final_price": window.get("final_price"),
        "result": window.get("result"),
        "binance": _points(window.get("binance") or binance),
        "chainlink": _points(window["chainlink"]) if window.get("chainlink") and start >= OUTSIDE_FROM else None,
        "up": _per_second(best, "up", a, b) if has_book else [],
        "down": _per_second(best, "down", a, b) if has_book else [],
        "minute_fallback": None if has_book else {"up": _points((window.get("prices") or {}).get("Up")),
                                                  "down": _points((window.get("prices") or {}).get("Down"))},
        "trades": fs, "position": position(fs), "tags": tags or {}, "coverage": cov,
    }  # fmt: skip


def summary(r: dict[str, Any]) -> dict[str, Any]:
    """``window.summary``: a tile for the overview, from a ``ready`` window. Profit counts fills and the payout
    of shares still held at the end ($1 each on the winning side); merges and redemptions aren't in the fills."""
    fs = r["trades"]
    buys = [f for f in fs if f["action"] == "buy"]
    cost = sum(f["shares"] * f["price"] for f in buys)
    back = sum(f["shares"] * f["price"] for f in fs if f["action"] == "sell")
    held = r["position"][-1] if r["position"] else {"up": 0.0, "down": 0.0}
    payout = None
    if r.get("result") in ("Up", "Down"):
        payout = max(0.0, held["up" if r["result"] == "Up" else "down"])
    pts = r["binance"]
    step = max(1, len(pts) // SPARK_POINTS)
    return {
        "window_id": r["window_id"], "start": r["start"], "end": r["end"], "result": r.get("result"),
        "price_to_beat": r.get("price_to_beat"),
        "entries": [{"t": f["t"], "side": f["side"], "action": f["action"]} for f in fs],
        "first_entry_s": (buys[0]["t"] - r["start"]) if buys else None,
        "shares": {"up": round(sum(f["shares"] for f in buys if f["side"] == "Up"), 6),
                   "down": round(sum(f["shares"] for f in buys if f["side"] == "Down"), 6)},
        "cost": round(cost, 2), "sold_for": round(back, 2), "payout": None if payout is None else round(payout, 2),
        "profit": None if payout is None else round(payout + back - cost, 2),
        "profit_note": "From fills and the payout of shares held at the end; merges and redemptions aren't counted.",
        "spark": [p for i, p in enumerate(pts) if i % step == 0][:SPARK_POINTS + 1],
        "coverage": {k: r["coverage"][k] for k in ("chainlink", "book", "outage")},
    }  # fmt: skip


def build(store: Any, reads: Any, sid: str, slug: str, tags: dict[str, Any] | None = None) -> dict[str, Any]:
    """One window's replay for the investigation's wallet, from what it already read where it can: the window
    (``window`` tool), the wallet's fills (``wallet_trades``), Binance. Reads only what's missing, keeps the
    ``ready`` and its ``summary``, and returns the ``ready``."""
    kept = store.window(sid, slug)
    read = kept["read"]
    if read is None:
        read = reads.window(slug)
        store.put_window(sid, slug, read=read)
    start, end = int(read["start"]), int(read["end"])
    trades = store.trades(sid, slug)
    wallet = (store.session_any(sid) or {}).get("wallet")
    if not trades and wallet:  # not read for this window yet: its own read, from a day before (listed a day ahead)
        got = reads.wallet_trades(wallet, start - 86_400, end + 60, slug)
        store.add_trades(sid, got["trades"])
        trades = [t for t in got["trades"] if t.get("slug") == slug]
    a, b = axis(start, end, trades)
    binance = None
    recorded_from = min((p[0] for p in read.get("binance") or []), default=None)
    if not read.get("binance") or (recorded_from is not None and recorded_from > a):
        span = read.get("_binance_span")
        if span is None or span[0] > a or span[1] < b:  # Binance for the whole axis, read once per span
            got = reads.outside_prices("binance", a, b)
            read["_binance"], read["_binance_span"] = (got.get("points") if got.get("available") else []), [a, b]
            store.put_window(sid, slug, read=read)
        binance = read["_binance"]
        if read.get("binance"):  # the recording's own seconds win where it has them
            rec = {int(t) for t, _ in read["binance"]}
            binance = sorted([p for p in binance if int(p[0]) not in rec] + read["binance"])
            read = {**read, "binance": None}
    r = ready(read, trades, binance, tags if tags is not None else (kept["ready"] or {}).get("tags"))
    store.put_window(sid, slug, ready=r, summary=summary(r))
    return r


def totals(coverages: list[dict[str, Any]]) -> dict[str, Any]:
    """Per source, how many of the investigation's windows each covers in full."""
    n = len(coverages)
    return {
        "windows": n,
        "chainlink": {"complete": sum(c["chainlink"] == "full" for c in coverages), "total": n},
        "book": {"complete": sum(bool(c["book"]) for c in coverages), "total": n},
        "outage": {"windows": [c["window_id"] for c in coverages if c["outage"]]},
    }
