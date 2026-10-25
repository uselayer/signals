"""Track records: what a Polymarket wallet has actually done, from a few cheap reads, for the Leaderboard.

A record is facts only, never a verdict: trading profit and dollars traded over 7, 30 and 90 days and all time
(and profit per dollar traded, the honest stand-in for ROI: Polymarket gives no deposits, and its average price is
off for about a third of traders), each of the last 12 weeks up or down, the profit line over 90 days, positions
closed in profit out of positions closed in each period (the win rate), their usual trade and how many markets they
buy into. Nothing in it says whether they're skilled or will make money next: the Leaderboard ranks what happened.

Reads, about 5 to 8 a wallet where a full score takes about 50:

- their latest trades (the evaluation's quick check, already read: ``trades``): usual trade, markets a day, last buy,
  and the average price they paid (the market's chance for what they bought: the context a win rate needs)
- Polymarket's profit history (``whales.profit_history``, 1 read): profit, volume, the weeks, the profit line and
  the worst drop, the same history (and the same code) a score reads
- their completed positions (``whales.completed_positions``: their stats, positions held, closed positions, 3 to 6
  reads, a read more per 500 positions held past the first 500): the win rate, by when each closed (a position never
  redeemed, by when its market ended)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from uselayer import ProfitHistory, Whales

PERIODS = (7, 30, 90)  # days: the Leaderboard's 7D, 30D and 90D
WEEKS = 12  # weeks up, of the last 12, as Recommended showed them
CLOSED_PAGES = 4  # closed positions read, 50 a page, newest first: 200, enough to cover 90 days for most traders
# positions held, 500 a page, read to the end (up to 10,000): the ones settled but never redeemed (mostly losers)
# count too, and they come in no order of time, so a held list cut short would leave out losers of any age
HELD_PAGES = 20
# Positions kept between reads (``PositionHistory``, in directory.db): each read adds what closed since the last,
# so a busy trader's win rate reaches back further each time instead of only as far as one read's 200.
KEEP_DAYS = 95  # positions kept per wallet: the longest period (90 days) and a little more
FIRST_PAGES = 20  # closed positions on a wallet's first read with nothing kept: up to 1,000, to start further back
MAX_PAGES = 40  # never more than 2,000 closed positions in one read
MERGE_S = 60  # fills of one market this close together are one trade, as the SDK's score merges them
DAY = 86400


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
    read may not cover in full.

    The two lists cover different times. Closed positions (mostly wins) are read newest first and cut at
    CLOSED_PAGES; positions held (where losers never redeemed sit) are read to the end, in no order of time. So a
    cut read covers back to its oldest closed position, and no further: a period reaching back past it has no win
    rate. Its unredeemed losers can be months old, so they never say how far back the read reached (they did, and a
    busy trader's 90 days counted every loser and only the last two weeks of wins: THEHIGHLIFE 30% against 55%
    read in full, 23 Oct). An incomplete read whose closed list ended was cut in the held list instead (over
    HELD_PAGES × 500 held), or Polymarket's paging slipped: losers may be missing anywhere, so no period has one."""
    since = _covered_since(positions, complete, CLOSED_PAGES)
    if since is None:
        return {d: None for d in PERIODS}
    return _count(_done(positions), since, now)


def _covered_since(positions: list[Any], complete: bool, pages: int) -> float | None:
    """How far back a read of ``pages`` closed pages covers (``_wins``): 0 when it read everything, the oldest closed
    position read when the closed list was cut, None when the held list may have been cut (no period can be)."""
    if complete:
        return 0.0
    closed_at = [
        t for p in positions
        if getattr(p, "redeemed", p.closed_at is not None) and (t := _when(p.closed_at)) is not None
    ]  # fmt: skip
    return min(closed_at) if len(closed_at) >= pages * 50 else None


def _done(positions: list[Any]) -> dict[str, tuple[float, bool]]:
    """Each position read by market outcome: when it closed (or its market ended, for one never redeemed) and
    whether it made money."""
    return {
        getattr(p, "market", None) or f"#{i}": (t, p.pnl > 0)
        for i, p in enumerate(positions) if (t := _when(p.closed_at) or _when(p.end_date)) is not None
    }  # fmt: skip


def _count(done: dict[str, tuple[float, bool]], since: float, now: float) -> dict[int, tuple[int, int] | None]:
    """(won, closed) in each of PERIODS from positions read in full back to ``since``; None for a period before it."""
    out: dict[int, tuple[int, int] | None] = {}
    for d in PERIODS:
        start = now - d * DAY
        if since > start:
            out[d] = None
            continue
        inside = [won for t, won in done.values() if start <= t <= now]
        out[d] = (sum(inside), len(inside))
    return out


@dataclass
class PositionHistory:
    """A wallet's positions kept between reads (directory.db's ``positions_kept``): every position closed or
    settled from ``since`` up to ``read_at`` is in ``rows`` (by market outcome: when, and whether it made money),
    none older than KEEP_DAYS. A read that reaches back to the last one's ``read_at`` extends it; one that doesn't
    starts it again from what it read."""

    since: float
    read_at: float
    rows: dict[str, tuple[float, bool]]


def merge(kept: PositionHistory | None, positions: list[Any], complete: bool, pages: int,
          now: float) -> PositionHistory | None:  # fmt: skip
    """``kept`` with a new read of ``pages`` closed pages added. None when the read can't be trusted (its held list may
    have been cut): nothing kept changes then, and no period has a win rate."""
    since = _covered_since(positions, complete, pages)
    if since is None:
        return None
    rows = _done(positions)
    if kept is not None and since <= kept.read_at:  # nothing closed between the two reads was missed
        rows = kept.rows | rows  # a position read again (one since redeemed) is the new read's
        since = min(since, kept.since)
    start = now - KEEP_DAYS * DAY
    return PositionHistory(max(since, start), now, {m: r for m, r in rows.items() if r[0] >= start})


def pages_for(kept: PositionHistory | None, now: float) -> int:
    """Closed pages to read so this read reaches back to the last one: from how many positions they closed a day
    over the last week kept, half again for safety. FIRST_PAGES with nothing kept; between CLOSED_PAGES and
    MAX_PAGES."""
    if kept is None:
        return FIRST_PAGES
    week = max(kept.since, kept.read_at - 7 * DAY)
    per_day = sum(1 for t, _ in kept.rows.values() if t >= week) / max((kept.read_at - week) / DAY, 1.0)
    need = per_day * max(now - kept.read_at, 0.0) / DAY * 1.5
    return min(MAX_PAGES, max(CLOSED_PAGES, math.ceil(need / 50) + 1))


def _decisions(buys: list[tuple[Any, ...]]) -> list[float]:
    """Dollars per trade, a trade being their buys of one market each within MERGE_S of the one before: one order
    fills in many pieces, so a single fill's dollars would make a $25K trader look like a $100 one (the SDK's
    score merges fills into decisions the same way)."""
    out: list[float] = []
    last: dict[str, tuple[float, int]] = {}  # market -> (time of its latest fill, index of its trade in out)
    for b in sorted(buys, key=lambda b: b[0]):
        t, market, usd = b[0], b[2], b[3]
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


def _usual(usds: list[float]) -> float | None:
    """Their usual trade: the size half their money went in, at or above (the middle of their trades weighted by
    dollars). A plain middle counts a $5 trade as much as a $50K one, so a trader with many scraps and a few big bets
    showed $22 against $1.3M profit (the owner, 19 Oct); here the scraps only count for the money in them."""
    usds = sorted(u for u in usds if u > 0)
    half, seen = sum(usds) / 2, 0.0
    for u in usds:
        seen += u
        if seen >= half:
            return round(u, 2)
    return None


def _paid(buys: list[tuple[Any, ...]]) -> float | None:
    """The average price they paid, each outcome bought once (its fills' dollars over its contracts), from buys
    that carry their price and outcome (``(…, price, outcome)``). A price is the market's chance for that outcome,
    so this is about the win rate their prices implied: someone who buys at 97¢ wins about 97% of the time by
    buying alone. None when no buy carries a price."""
    usd: dict[str, float] = {}
    contracts: dict[str, float] = {}
    for t in buys:
        if len(t) > 5 and t[3] and t[4]:
            usd[t[5]] = usd.get(t[5], 0.0) + t[3]
            contracts[t[5]] = contracts.get(t[5], 0.0) + t[3] / t[4]
    prices = [usd[k] / contracts[k] for k in usd if contracts[k]]
    return round(statistics.fmean(prices), 4) if prices else None


def _style(trades: list[tuple[Any, ...]], now: float) -> dict[str, Any]:
    """From their latest trades (``(time, bought, market, dollars)``, newest first, as the quick check reads them,
    optionally with each one's price and outcome after): their usual trade (``_usual``, over 30 days, in dollars),
    new markets a day over the days read (30, or fewer when a busy trader's 500 latest trades reach
    back less far), the average price they paid over 30 days (``_paid``) and their last buy."""
    month = now - 30 * DAY
    buys = [t for t in trades if t[1] and t[0] >= month]
    usds = _decisions(buys)
    reached = min((t[0] for t in trades), default=now)
    days = max(1.0, (now - max(reached, month)) / DAY) if trades else 30.0
    return {
        "typical_usd": _usual(usds),
        "buys_30d": len({t[2] for t in buys}),
        "markets_per_day": round(len({t[2] for t in buys}) / days, 2),
        "paid_30d": _paid(buys),
        "last_buy": max((t[0] for t in trades if t[1]), default=None),
    }


def build(history: ProfitHistory, positions: Any, trades: list[tuple[Any, ...]], now: float,
          kept: PositionHistory | None = None) -> dict[str, Any]:  # fmt: skip
    """A record from what was read: their profit ``history`` (the SDK's ProfitHistory), ``positions`` (the SDK's
    PositionRecord, or None when it couldn't be read) and their latest ``trades``. Every figure that wasn't read is
    None, never 0 (an empty history gives None for each). With ``kept`` (the positions kept, this read added:
    ``merge``) the win rate is from those instead, back as far as they reach."""
    end, since = int(now), history.since
    periods: dict[str, dict[str, Any]] = {}
    if kept is not None:
        wins = _count(kept.rows, kept.since, now)
    else:
        wins = _wins(positions.positions, positions.complete, now) if positions is not None else {}
    for d in PERIODS:
        p = history.period(end - d * DAY, end)
        won = wins.get(d)
        periods[f"{d}d"] = {
            "trading_pnl": p.get("trading_pnl"),
            "realized": p.get("realized"),  # profit taken: a trader's page's headline
            "volume": p.get("volume"),
            "return_per_dollar": p.get("return_per_dollar"),
            "won": None if won is None else won[0],
            "closed": None if won is None else won[1],
        }
    # all time: from their first trade (the history starts there, at 0)
    periods["all"] = history.period(since - 1, end) if since is not None else {}
    weeks = history.weekly(end - WEEKS * 7 * DAY, end)
    daily = history.daily(end - 90 * DAY, end)
    known = [w for w in weeks or [] if w is not None]
    return {
        "read_at": now,
        "since": since,
        "periods": periods,
        # the biggest fall from a high, hour by hour, as a score gives it (a trader's page shows it)
        "worst_drop": {f"{d}d": history.worst_drop(end - d * DAY, end) for d in PERIODS} if since is not None else None,
        "pnl_weeks": weeks,
        "weeks_up": sum(1 for w in known if w > 0) if weeks is not None else None,
        "weeks_known": len(known) if weeks is not None else None,
        "pnl_daily": [list(x) for x in daily] if daily is not None else None,
        "positions_complete": None if positions is None else bool(positions.complete),
        **_style(trades, now),
    }


def read(whales: Whales, wallet: str, trades: list[tuple[Any, ...]], kept: PositionHistory | None = None,
         now: float | None = None) -> tuple[dict[str, Any], PositionHistory | None]:  # fmt: skip
    """A wallet's record, read now on ``whales``' budget (the background's), and their positions kept with this read
    added (``merge``: to keep for the next one; None when there's nothing new to keep). The profit history must be
    read; the completed positions may fail on their own (Polymarket's firewall, a list that slipped), leaving the
    win rate unknown rather than the whole record, and what's kept as it was."""
    now = datetime.now(UTC).timestamp() if now is None else now
    history = whales.profit_history(wallet)
    pages = pages_for(kept, now)
    try:
        positions = whales.completed_positions(wallet, max_pages=pages, held_pages=HELD_PAGES)
    except Exception:  # VenueError mostly: the record goes on without a win rate
        positions = None
    merged = None if positions is None else merge(kept, positions.positions, positions.complete, pages, now)
    return build(history, positions, trades, now, kept=merged), merged
