"""What the case file draws, built by the server from the data (never by the model): one window's replay
(``window.ready``), its overview tile (``window.summary``) and its coverage. The agent decides which window to show
and how to tag it; every series, trade and position here comes from the reads themselves.

Shapes are the UI-to-agent contract's (docs/research-contract.md): times in unix seconds, ``t`` on every point.
"""

from __future__ import annotations

import bisect
import threading
from datetime import datetime
from typing import Any

from signals.research import markets
from signals.research.data import OUTSIDE_FROM, UNUSABLE, complete_slugs, now, trade_id

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


def _why(raw: Any) -> str:
    """A recording gap's reason in plain words, for the chart's hatching ("connection pm0.157 reconnected" →
    "The recorder's connection dropped and reconnected")."""
    s = str(raw or "").lower()
    if "reconnect" in s:
        return "The recorder's connection dropped and reconnected"
    if "overflow" in s or "backlog" in s:
        return "The recorder fell behind and dropped data"
    if "restart" in s or "deploy" in s:
        return "The recorder restarted"
    if "crossed" in s:
        return "The book looked wrong (crossed) and was skipped"
    return "No book was recorded here" if not s else str(raw)[:80]


def _points(rows: list[list[float]] | None) -> list[dict[str, float]]:
    return [{"t": int(t), "p": float(p)} for t, p in rows or []]


def _spark(pts: list[dict[str, float]]) -> list[dict[str, float]]:
    """A tile's line: about one point every 15 s of the window, from a ``ready`` price series."""
    step = max(1, len(pts) // SPARK_POINTS)
    return [p for i, p in enumerate(pts) if i % step == 0][:SPARK_POINTS + 1]


def chainlink_spark(r: dict[str, Any]) -> list[dict[str, float]] | None:
    """Chainlink BTC/USD as a tile's line (the feed the price to beat is averaged from), None where it wasn't
    recorded. From the ``ready`` alone: no read."""
    return _spark(r["chainlink"]) if r.get("chainlink") else None


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
    gaps = [(_secs(x.get("from")), _secs(x.get("to"))) for x in ((window.get("coverage") or {}).get("book") or {})
            .get("lost") or []]  # fmt: skip
    out = []
    for r in sorted(trades, key=lambda r: (r["ts"], r.get("tx") or "")):
        paid = None
        side = (r.get("outcome") or "").lower()
        at = float(stream_ms[r["tx"]]) if stream_ms.get(r.get("tx")) else None
        in_gap = at is not None and any(a - 1 <= at / 1000 <= b for a, b in gaps)  # the book there isn't known
        if best and r["action"] == "buy" and side in ("up", "down") and at is not None and not in_gap:
            ask = _ask_at(best, side, at)
            paid = None if ask is None else float(r["price"]) >= float(ask) - 1e-9
        out.append({"trade_id": r.get("id") or trade_id(r.get("tx"), r.get("token"), r["action"], r["price"],
                                                        r["size"], r["ts"]),
                    "t": r["ts"], "side": r.get("outcome"), "action": r["action"], "shares": r["size"],
                    "price": r["price"], "usd": r.get("usd"), "paid_ask": paid,
                    # paying the ask took liquidity; buying below it means its resting order was filled
                    "liquidity": None if paid is None else ("taker" if paid else "maker"),
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
    # An outage is a span the recorder lost as a whole (UNUSABLE). The recording's own usable=false mostly means
    # seconds without a book: the window still counts for fills, trades and position; only book facts (paid_ask,
    # what was for sale) depend on it, per second (lost spans), never the whole window.
    outage = any(a < end and start < b for a, b in UNUSABLE)
    return {
        "window_id": window.get("slug"), "source": window.get("source") or "Polymarket API",
        "chainlink": "full" if has_chainlink else "start_and_result",
        "book": bool(recorded and (window.get("book") or {}).get("available")),
        # recorded (built), not_processed (recorded, its window file not built yet) or not_recorded (before 2 Nov)
        "book_status": "recorded" if recorded and (window.get("book") or {}).get("available")
        else (window.get("book") or {}).get("status") or "not_recorded",
        "chainlink_source": window.get("chainlink_source") or ("Layer window file" if recorded else None),
        "missing_seconds": [[round(_secs(x.get("from"))), round(_secs(x.get("to")) - _secs(x.get("from")), 1)]
                            for x in book.get("lost") or []] if recorded else None,
        "lost": [{"from": round(_secs(x.get("from")), 1), "to": round(_secs(x.get("to")), 1), "why": _why(x.get("why"))}
                 for x in book.get("lost") or []] if recorded else None,
        "seconds_without_book": book.get("secondsWithoutBook"),
        "market_trades": {"recorded": trades.get("onStream"), "polymarket": trades.get("dataApi"),
                          "pct": trades.get("pct")} if recorded
        else {"read": (window.get("coverage") or {}).get("trades_read"), "complete": (window.get("coverage") or {})
              .get("trades_complete")},
        "outage": bool(outage), "book_usable": rec.get("usable") if recorded else None,
        "reasons": rec.get("reasons") or [] if recorded else [],
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
        "binance_at_start": next((p["p"] for p in _points(window.get("binance") or binance) if p["t"] >= start), None),
        "chainlink": _points(window["chainlink"]) if window.get("chainlink") and start >= OUTSIDE_FROM else None,
        # Binance is BTC in Tether, Chainlink and the price to beat in US dollars: about 0.1% apart, never compared.
        "units": {"binance": "USDT", "chainlink": "USD", "price_to_beat": "USD, Chainlink's 60-second average"},
        "up": _per_second(best, "up", a, b) if has_book else [],
        "down": _per_second(best, "down", a, b) if has_book else [],
        "minute_fallback": None if has_book else {"up": _points((window.get("prices") or {}).get("Up")),
                                                  "down": _points((window.get("prices") or {}).get("Down"))},
        "trades": fs, "position": position(fs), "tags": tags or {}, "coverage": cov,
    }  # fmt: skip


def summary(r: dict[str, Any]) -> dict[str, Any]:
    """``window.summary``: a tile for the overview, from a ``ready`` window. Profit counts fills and the payout
    of shares still held at the end ($1 each on the winning side); merges and redemptions aren't in the fills. A
    market's replay has its own tile (``market_summary``)."""
    if r.get("kind") == "market":
        return market_summary(r)
    fs = r["trades"]
    buys = [f for f in fs if f["action"] == "buy"]

    def paid(f: dict[str, Any]) -> float:  # what Polymarket says changed hands; its price is rounded
        return float(f["usd"]) if f.get("usd") is not None else f["shares"] * f["price"]

    cost = sum(paid(f) for f in buys)
    back = sum(paid(f) for f in fs if f["action"] == "sell")
    held = r["position"][-1] if r["position"] else {"up": 0.0, "down": 0.0}
    payout = None
    if r.get("result") in ("Up", "Down"):
        payout = max(0.0, held["up" if r["result"] == "Up" else "down"])
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
        "spark": _spark(r["binance"]),
        # Chainlink BTC/USD, the feed the price to beat is averaged from: how far BTC was from it at each buy.
        "chainlink_spark": chainlink_spark(r),
        "coverage": {k: r["coverage"][k] for k in ("chainlink", "book", "outage")},
    }  # fmt: skip


def build(store: Any, reads: Any, sid: str, slug: str, tags: dict[str, Any] | None = None) -> dict[str, Any]:
    """One window's replay for the investigation's wallet, from what it already read where it can: the window
    (``window`` tool), the wallet's fills (``wallet_trades``), Binance. Reads only what's missing, keeps the
    ``ready`` and its ``summary``, and returns the ``ready``. A slug that isn't a crypto Up/Down window is a market
    (a long-dated BTC market, later politics or sports): its own replay, ``build_market``."""
    if not markets.is_window(slug):
        return build_market(store, reads, sid, slug, tags)
    kept = store.window(sid, slug)
    read = kept["read"]
    if read is None:  # the replay needs the window's facts and prices, not everyone's trades
        read = reads.window(slug, with_trades=False)
        store.put_window(sid, slug, read=read)
    start, end = int(read["start"]), int(read["end"])
    trades = store.trades(sid, slug)
    wallet = (store.session_any(sid) or {}).get("wallet")
    if not kept.get("complete") and wallet:
        # Not read for this window yet, or only by a range that cut through it (a tile from those would count part
        # of the window as all of it): its own read, from a day before (listed a day ahead) to just after it ends.
        lo, hi = start - 86_400, end + 60
        got = reads.wallet_trades(wallet, lo, hi, slug)
        store.add_trades(sid, got["trades"])
        store.mark_complete(sid, complete_slugs(got, lo, hi, also=(slug,)) & {slug})
        trades = store.trades(sid, slug)
    a, b = axis(start, end, trades)
    if not read.get("chainlink") and b >= OUTSIDE_FROM and read.get("_chainlink_span") != [a, b]:
        # No window file yet: Chainlink from Layer's raw recording of the live feed, for the whole axis, once.
        family = str(read.get("slug") or slug).split("-")[0]
        pts = getattr(reads, "chainlink", lambda *x: None)(f"{family}/usd", a, b)
        read["_chainlink_span"] = [a, b]
        if pts:
            read["chainlink"], read["chainlink_source"] = pts, "Layer raw recording (live feed)"
        store.put_window(sid, slug, read=read)
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
    """Per source, how many of the investigation's windows each covers in full (and for markets, how many have every
    fill read, the price step and the outside line)."""
    n = len(coverages)
    mk = [c for c in coverages if c.get("kind") == "market"]
    if mk and len(mk) == n:
        steps = sorted({c["price_step_s"] for c in mk if c.get("price_step_s")})
        return {"windows": n, "kind": "market", "markets": n,
                "fills_complete": {"complete": sum(bool(c.get("fills_complete")) for c in mk), "total": n},
                "price_steps_s": steps,
                "outside": {"name": next((c["outside"] for c in mk if c.get("outside")), None),
                            "markets": sum(bool(c.get("outside")) for c in mk)},
                "chainlink": {"complete": 0, "total": n}, "book": {"complete": 0, "total": n},
                "outage": {"windows": []}}  # fmt: skip
    return {
        "windows": n,
        "chainlink": {"complete": sum(c["chainlink"] == "full" for c in coverages), "total": n},
        "book": {"complete": sum(bool(c["book"]) for c in coverages), "total": n},
        "outage": {"windows": [c["window_id"] for c in coverages if c["outage"]]},
    }


# ---- a market's replay: one market's life for the wallet (long-dated BTC; later politics, sports) ----

MARKET_PAD_S = 86_400  # the replay starts this long before the wallet's first fill (or at the listing)
MARKET_FRESH_S = 900  # an open market's kept read is used again for this long, then read again up to now
MARKET_SPARK = 80  # points on a market tile's lines
DUST = 0.01  # shares: less than this left over counts as sold out
_building: dict[tuple[str, str], threading.Lock] = {}
_building_lock = threading.Lock()


def _thin(pts: list[dict[str, Any]], n: int = MARKET_SPARK) -> list[dict[str, Any]]:
    step = max(1, -(-len(pts) // n))
    out = pts[::step]
    if pts and out[-1] is not pts[-1]:
        out.append(pts[-1])
    return out


def _value_at(pts: list[dict[str, Any]], t: float) -> float | None:
    """The last point's value at or before ``t`` (``pts`` sorted by t), else None."""
    i = bisect.bisect_right([p["t"] for p in pts], t) - 1
    return pts[i]["p"] if i >= 0 else None


def market_fills(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The wallet's fills in one market, as the market replay draws them (side = the outcome, e.g. Yes or No)."""
    return [{"trade_id": r.get("id") or trade_id(r.get("tx"), r.get("token"), r["action"], r["price"], r["size"],
                                                   r["ts"]),
             "t": int(r["ts"]), "side": r.get("outcome"), "action": r["action"], "shares": float(r["size"]),
             "price": float(r["price"]), "usd": r.get("usd")}
            for r in sorted(trades, key=lambda r: (r["ts"], r.get("tx") or ""))]  # fmt: skip


def market_position(fs: list[dict[str, Any]], outcomes: list[str]) -> list[dict[str, Any]]:
    """Shares held of each outcome after each fill: [{t, held: {Yes: x, No: y}}]."""
    held = {o: 0.0 for o in outcomes}
    out: list[dict[str, Any]] = []
    for f in fs:
        held[f["side"]] = held.get(f["side"], 0.0) + (f["shares"] if f["action"] == "buy" else -f["shares"])
        if out and out[-1]["t"] == f["t"]:
            out.pop()
        out.append({"t": f["t"], "held": {k: round(v, 6) for k, v in held.items()}})
    return out


def market_ready(read: dict[str, Any], trades: list[dict[str, Any]], outside: dict[str, Any] | None,
                 fills_complete: bool, tags: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    """``window.ready`` for a market (``kind`` "market"): the market's prices over the replay's span, the outside
    line (Binance BTCUSDT for BTC price markets: closes, and each candle's high and low), the wallet's fills over
    the market's whole life, its position after each, and what it paid, got back and holds (an open market valued
    at its latest price, said so in ``value.profit_kind``)."""
    outcomes = list(read.get("outcomes") or [])
    fs = market_fills(trades)
    pos = market_position(fs, outcomes)
    held = pos[-1]["held"] if pos else {o: 0.0 for o in outcomes}
    prices = {o: _points(read.get("prices", {}).get(o)) for o in outcomes}
    last = {o: (prices[o][-1]["p"] if prices[o] else None) for o in outcomes}
    lows = {o: min((p["held"].get(o, 0.0) for p in pos), default=0.0) for o in outcomes}
    before = any(v < -DUST for v in lows.values())  # sold more than its fills bought: shares came another way (a split)

    def paid(f: dict[str, Any]) -> float:
        return float(f["usd"]) if f.get("usd") is not None else f["shares"] * f["price"]

    cost = sum(paid(f) for f in fs if f["action"] == "buy")
    back = sum(paid(f) for f in fs if f["action"] == "sell")
    holding = {o: v for o, v in held.items() if v >= DUST}  # a few hundredths of a share is dust, not a position
    result = read.get("result")
    payout = value_now = None
    if result is not None:
        kind, payout = "resolved", max(0.0, held.get(result, 0.0))
    elif not holding:
        kind, payout = "closed", 0.0
    else:
        kind = "open"
        value_now = sum(v * last[o] for o, v in holding.items()) if all(last[o] is not None for o in holding) else None
    end_value = payout if payout is not None else value_now
    profit = None if before or end_value is None or not fills_complete else round(end_value + back - cost, 2)
    market_end = read.get("closed_at") or read.get("end")
    first = fs[0]["t"] if fs else None
    if kind == "closed":
        hold_to = next((p["t"] for p in reversed(pos) if all(v < DUST for v in p["held"].values())), fs[-1]["t"])
    elif kind == "resolved":
        hold_to = max(int(read.get("closed_at") or market_end or fs[-1]["t"]), fs[-1]["t"]) if fs else None
    else:
        hold_to = int(read.get("price_to") or now())
    span_from, span_to = int(read.get("price_from") or (first or 0)), int(read.get("price_to") or now())
    out_pts = out_ranges = None
    if outside and outside.get("available"):
        out_pts = _points(outside.get("points"))
        out_ranges = [{"t": int(t), "h": float(h), "l": float(lo)} for t, h, lo in outside.get("ranges") or []]
    for f in fs:  # each fill with the outside line's price then (the last close at or before it)
        f["outside"] = _value_at(out_pts, f["t"]) if out_pts else None
    rule = read.get("rule") or {}
    notes = []
    if read.get("coverage", {}).get("price_note"):
        notes.append(read["coverage"]["price_note"])
    if not fills_complete:
        notes.append("Polymarket listed more of its fills in this market than one read holds: the oldest weren't read.")
    if before:
        notes.append("It sold more shares here than its fills show it buying: the rest came some way fills don't show "
                     "(splitting dollars into both outcomes, or a conversion), so this market's profit isn't counted.")  # fmt: skip
    coverage = {"window_id": read.get("slug"), "kind": "market", "source": "Polymarket API (uselayer)",
                "price_step_s": (read.get("coverage") or {}).get("price_step_s"),
                "price_points": (read.get("coverage") or {}).get("price_points"),
                "fills_complete": bool(fills_complete and not before), "bought_before_read": before,
                "outside": f"Binance {outside.get('symbol')}" if outside and outside.get("available") else None,
                "outside_step": (outside or {}).get("step") if outside and outside.get("available") else None,
                "outside_why": (outside or {}).get("why") if outside and not outside.get("available") else None,
                "chainlink": "none", "book": False, "outage": False, "notes": notes}  # fmt: skip
    return {
        "kind": "market", "window_id": read.get("slug"), "market_type": read.get("market_type"),
        "market_label": read.get("market_label"), "title": read.get("question"), "condition_id": read.get("condition_id"),
        "event_slug": read.get("event_slug"), "event_title": read.get("event_title"),
        "start": span_from, "end": span_to, "axis": {"from": span_from, "to": span_to},
        "market_start": read.get("start"), "market_end": read.get("end"), "closed": read.get("closed"),
        "closed_at": read.get("closed_at"), "result": result, "rule": rule, "rules": read.get("description"),
        "outcomes": outcomes, "prices": prices,
        "outside": None if out_pts is None else {
            "name": f"Binance {(outside or {}).get('symbol')}", "unit": (outside or {}).get("unit"),
            "step": (outside or {}).get("step"), "points": out_pts, "ranges": out_ranges,
            "highest": (outside or {}).get("highest"), "lowest": (outside or {}).get("lowest")},
        "trades": fs, "position": pos,
        "hold": {"from": first, "to": hold_to, "days": None if first is None or hold_to is None
                 else round((hold_to - first) / 86_400, 1), "still_held": kind == "open"},
        "value": {"cost": round(cost, 2), "sold_for": round(back, 2), "held": {o: round(v, 6) for o, v in held.items()},
                  "payout": None if payout is None else round(payout, 2),
                  "value_now": None if value_now is None else round(value_now, 2), "last_prices": last,
                  "profit": profit, "profit_kind": kind},
        "tags": tags or {}, "coverage": coverage,
    }  # fmt: skip


PROFIT_NOTES = {
    "resolved": "From fills and the payout of shares held at the resolution; merges and redemptions aren't counted.",
    "closed": "It sold out before the end: from what it paid and what its sells brought in.",
    "open": "Still held: valued at the market's latest price, not a result. Merges and redemptions aren't counted.",
}


def market_summary(r: dict[str, Any]) -> dict[str, Any]:
    """``window.summary`` for a market: a tile. Profit: resolved (the payout), closed (it sold out) or open (its
    shares at today's price, labelled so on the page)."""
    fs, v = r["trades"], r["value"]
    buys = [f for f in fs if f["action"] == "buy"]
    bought = {o: round(sum(f["shares"] for f in buys if f["side"] == o), 6) for o in r["outcomes"]}
    # the tile's line: the outcome it bought most, so the line is the price of what it held
    side = max(bought, key=lambda o: bought[o]) if bought and any(bought.values()) else (r["outcomes"] or [None])[0]
    line = r["prices"].get(side) or [] if side else []
    return {
        "kind": "market", "window_id": r["window_id"], "market_type": r.get("market_type"), "title": r["title"],
        "event_slug": r.get("event_slug"), "event_title": r.get("event_title"),
        "start": r["hold"]["from"] or r["start"], "end": r["hold"]["to"] or r["end"],
        "market_end": r.get("closed_at") or r.get("market_end"), "closed": r.get("closed"), "result": r.get("result"),
        "rule": r.get("rule"), "outcomes": r["outcomes"],
        "entries": [{"t": f["t"], "side": f["side"], "action": f["action"], "price": f["price"], "shares": f["shares"],
                     "usd": f.get("usd"), "outside": f.get("outside")} for f in fs],
        "first_entry_s": None, "shares": bought, "held": v["held"],
        "cost": v["cost"], "sold_for": v["sold_for"], "payout": v["payout"], "value_now": v["value_now"],
        "profit": v["profit"], "profit_kind": v["profit_kind"], "open": v["profit_kind"] == "open",
        "profit_note": PROFIT_NOTES[v["profit_kind"]], "held_days": r["hold"]["days"],
        "spark_side": side, "spark": _thin(line),
        "outside_spark": _thin((r.get("outside") or {}).get("points") or []),
        "coverage": {k: r["coverage"][k] for k in ("kind", "fills_complete", "bought_before_read", "price_step_s",
                                                   "outside", "chainlink", "book", "outage")},
    }  # fmt: skip


def build_market(store: Any, reads: Any, sid: str, slug: str, tags: dict[str, Any] | None = None) -> dict[str, Any]:
    """One market's replay for the investigation's wallet: the market's facts and rule, the wallet's fills over the
    market's whole life (read once, ``Reads.market_fills``), the market's prices from a day before its first fill
    to its end or now (``Reads.market``, at a step for the span), and the outside line its type draws. A read is
    kept; an open market's is read again after MARKET_FRESH_S. One build per market at a time (Start's tiles and the
    agent's code ask for the same ones)."""
    with _building_lock:
        lock = _building.setdefault((sid, slug), threading.Lock())
    with lock:
        return _build_market(store, reads, sid, slug, tags)


def _build_market(store: Any, reads: Any, sid: str, slug: str, tags: dict[str, Any] | None) -> dict[str, Any]:
    kept = store.window(sid, slug)
    read = kept["read"] if (kept["read"] or {}).get("kind") == "market" else None
    fresh = read is not None and (read.get("closed") or now() - float(read.get("_read_at") or 0) < MARKET_FRESH_S)
    wallet = (store.session_any(sid) or {}).get("wallet")
    facts = {k: v for k, v in read.items() if not k.startswith("_") and k not in ("prices", "coverage")} if read else \
        reads.market_facts(slug)  # fmt: skip
    mt = markets.of_market(facts.get("slug") or slug, facts)
    complete = bool(kept.get("complete"))
    if not complete and wallet and facts.get("condition_id"):
        got = reads.market_fills(wallet, facts["condition_id"])
        for t in got["trades"]:
            t["slug"] = t.get("slug") or facts.get("slug") or slug
        store.add_trades(sid, got["trades"])
        if got["complete"]:
            store.mark_complete(sid, [slug])
        complete = got["complete"]
    trades = store.trades(sid, slug)
    if not fresh:
        end_at = facts.get("closed_at") or facts.get("end") or now()
        hi = int(max(min(end_at, now()), max((t["ts"] for t in trades), default=0)))
        first = min((t["ts"] for t in trades), default=hi - 30 * 86_400)
        lo = int(max(first - MARKET_PAD_S, min(facts.get("start") or first, first)))
        got = reads.market(slug, start=lo, end=hi, facts=facts)
        read = {**got, "kind": "market", "market_type": mt.id if mt else None, "market_label": mt.label if mt else None,
                "rule": mt.rule(facts) if mt else None, "_read_at": now()}  # fmt: skip
        read["_outside"] = None
        if mt and mt.outside and mt.outside.get("source") == "binance":
            read["_outside"] = reads.outside_prices("binance", lo, hi, mt.outside.get("symbol") or "BTC")
        store.put_window(sid, slug, read=read)
    r = market_ready(read, trades, read.get("_outside"), complete,
                     tags if tags is not None else (kept["ready"] or {}).get("tags"))  # fmt: skip
    store.put_window(sid, slug, ready=r, summary=market_summary(r))
    return r
