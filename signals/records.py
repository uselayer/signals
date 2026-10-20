"""Track records: what a Polymarket wallet has actually done, from a few cheap reads, for the Leaderboard.

A record is facts only, never a verdict: trading profit and dollars traded over 7, 30 and 90 days and all time
(and profit per dollar traded, the honest stand-in for ROI: Polymarket gives no deposits, and its average price is
off for about a third of traders), each of the last 12 weeks up or down, the profit line over 90 days, positions
closed in profit out of positions closed in each period (the win rate), their usual trade and how many markets they
buy into. Nothing in it says whether they're skilled or will make money next: the Leaderboard ranks what happened.

Reads, about 5 to 8 a wallet where a full score takes about 50:

- their latest trades (the evaluation's quick check, already read: ``trades``): usual trade, markets a day, last buy
- Polymarket's profit history (1 read): profit, volume and the weeks, from the same history the score reads
- their completed positions (``whales.completed_positions``: their stats, positions held, closed positions, 3 to 6
  reads): the win rate, by when each closed (a position never redeemed, by when its market ended)

The profit history has no public SDK call yet: ``_pnl_points`` reads it through the SDK's internals, the second
stopgap beside the Feed's ``_open_positions`` (AGENTS.md), until uselayer has a public one.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from uselayer import Whales
# stopgap: the score's own reading of the profit history (module docstring)
from uselayer.whale_scores import _Curve, _trading

PERIODS = (7, 30, 90)  # days: the Leaderboard's 7D, 30D and 90D
WEEKS = 12  # weeks up, of the last 12, as Recommended showed them
CLOSED_PAGES = 4  # closed positions read, 50 a page, newest first: 200, enough to cover 90 days for most traders
HELD_PAGES = 1  # positions held, 500 a page: the ones settled but never redeemed (mostly losers) count too
MERGE_S = 60  # fills of one market this close together are one trade, as the SDK's score merges them
DAY = 86400


def _pnl_points(whales: Whales, wallet: str) -> list[dict[str, Any]]:
    """Polymarket's hourly profit history for ``wallet`` (one read on the background's budget). Stopgap: see above."""
    return whales._poly.pnl_history(wallet)  # type: ignore[attr-defined, no-any-return]


def _when(v: Any) -> float | None:
    """A time as Polymarket or the SDK gives it (a datetime, seconds, or ISO text, a date alone included) in seconds."""
    if isinstance(v, datetime):
        return v.timestamp()
    if isinstance(v, int | float) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str) and v:
        try:
            t = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
        return (t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp()
    return None


def _wins(positions: list[Any], complete: bool, now: float) -> dict[int, tuple[int, int] | None]:
    """Positions closed in profit, and positions closed, in each of PERIODS: (won, closed). None for a period the
    read may not cover in full: the list was cut at the read limit and its oldest closed position is inside it."""
    done = [(t, p.pnl) for p in positions if (t := _when(p.closed_at) or _when(p.end_date)) is not None]
    oldest = min((t for t, _ in done), default=None)
    out: dict[int, tuple[int, int] | None] = {}
    for d in PERIODS:
        start = now - d * DAY
        if not complete and (oldest is None or oldest >= start):
            out[d] = None
            continue
        inside = [pnl for t, pnl in done if start <= t <= now]
        out[d] = (sum(1 for pnl in inside if pnl > 0), len(inside))
    return out


def _decisions(buys: list[tuple[float, bool, str, float | None]]) -> list[float]:
    """Dollars per trade, a trade being their buys of one market each within MERGE_S of the one before: one order
    fills in many pieces, so a single fill's dollars would make a $25K trader look like a $100 one (the SDK's
    score merges fills into decisions the same way)."""
    out: list[float] = []
    last: dict[str, tuple[float, int]] = {}  # market -> (time of its latest fill, index of its trade in out)
    for t, _, market, usd in sorted(buys):
        if usd is None:
            continue
        seen = last.get(market)
        if seen is not None and t - seen[0] <= MERGE_S:
            out[seen[1]] += usd
            last[market] = (t, seen[1])
        else:
            out.append(usd)
            last[market] = (t, len(out) - 1)
    return out


def _style(trades: list[tuple[float, bool, str, float | None]], now: float) -> dict[str, Any]:
    """From their latest trades (``(time, bought, market, dollars)``, newest first, as the quick check reads them):
    their usual trade (the middle of their buys over 30 days, in dollars), new markets a day over the days read (30,
    or fewer when a busy trader's 500 latest trades reach back less far), and their last buy."""
    month = now - 30 * DAY
    buys = [t for t in trades if t[1] and t[0] >= month]
    usds = _decisions(buys)
    reached = min((t[0] for t in trades), default=now)
    days = max(1.0, (now - max(reached, month)) / DAY) if trades else 30.0
    return {
        "typical_usd": round(statistics.median(usds), 2) if usds else None,
        "buys_30d": len({t[2] for t in buys}),
        "markets_per_day": round(len({t[2] for t in buys}) / days, 2),
        "last_buy": max((t[0] for t in trades if t[1]), default=None),
    }


def build(points: list[dict[str, Any]], positions: Any, trades: list[tuple[float, bool, str, float | None]],
          now: float) -> dict[str, Any]:  # fmt: skip
    """A record from what was read: the profit history's ``points``, ``positions`` (the SDK's PositionRecord, or
    None when it couldn't be read) and their latest ``trades``. Every figure that wasn't read is None, never 0."""
    curve, end = _Curve(points), int(now)
    periods: dict[str, dict[str, Any]] = {}
    wins = _wins(positions.positions, positions.complete, now) if positions is not None else {}
    for d in PERIODS:
        p = curve.period(end - d * DAY, end) if points else {}
        won = wins.get(d)
        periods[f"{d}d"] = {
            "trading_pnl": p.get("trading_pnl"),
            "volume": p.get("volume"),
            "return_per_dollar": p.get("return_per_dollar"),
            "won": None if won is None else won[0],
            "closed": None if won is None else won[1],
        }
    # all time: from their first trade (the history starts there, at 0)
    periods["all"] = curve.period(curve.since - 1, end) if points and curve.since is not None else {}
    weeks = curve.known_steps(end - WEEKS * 7 * DAY, end, 7 * DAY) if points else None
    daily = None
    if points:
        marks = [(datetime.fromtimestamp(t, UTC).date().isoformat(), curve.at(t, _trading))
                 for t in range(end - 90 * DAY, end + 1, DAY)]  # fmt: skip
        base = curve.at(end - 90 * DAY, _trading)
        if base is not None and all(v is not None for _, v in marks):
            daily = [[day, round(v - base, 2)] for day, v in marks]  # type: ignore[operator]
    known = [w for w in weeks or [] if w is not None]
    return {
        "read_at": now,
        "since": curve.since,
        "periods": periods,
        "pnl_weeks": weeks,
        "weeks_up": sum(1 for w in known if w > 0) if weeks is not None else None,
        "weeks_known": len(known) if weeks is not None else None,
        "pnl_daily": daily,
        "positions_complete": None if positions is None else bool(positions.complete),
        **_style(trades, now),
    }


def read(whales: Whales, wallet: str, trades: list[tuple[float, bool, str, float | None]],
         now: float | None = None) -> dict[str, Any]:  # fmt: skip
    """A wallet's record, read now on ``whales``' budget (the background's). The profit history must be read; the
    completed positions may fail on their own (Polymarket's firewall, a list that slipped), leaving the win rate
    unknown rather than the whole record."""
    now = datetime.now(UTC).timestamp() if now is None else now
    points = _pnl_points(whales, wallet)
    try:
        positions = whales.completed_positions(wallet, max_pages=CLOSED_PAGES, held_pages=HELD_PAGES)
    except Exception:  # VenueError mostly: the record goes on without a win rate
        positions = None
    return build(points, positions, trades, now)
