"""Watching a trader (the Watchlist): what changed in what they hold, worked out from their trades and their open
positions now. No reads here: the engine reads (``app._watch``), this only works it out, so it can be tested on its own.

A *move* is their fills of one outcome, one way (buys or sells), each within MOVE_S of the one before: an order filled
in pieces, a resting order filled over hours, or a run of orders reads as one change (6 hours, as a grouped alert's). What a move did to their position
comes from walking back from what they hold now: the contracts they hold of an outcome, less each move's contracts,
newest first, is what they held before it. So a buy with nothing held before it is a new position, one with something
held is an add, and a sell that leaves nothing is a close. Where what they hold now isn't known (an outcome they no
longer hold whose last move was a buy: it settled, or they redeemed or merged it, none of which is a trade), the move
is only "bought" or "sold", never guessed.

Polymarket also changes a position without a trade (splits, merges, conversions, redeeming), so a walk back can come
out below zero: it's taken as zero, never a negative position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any

MOVE_S = 6 * 3600  # fills of one outcome, one way, within this long of the one before make one move
DUST = 1.0  # contracts: less than this held is nothing held (Polymarket lists positions from 1 contract)
DUST_SHARE = 0.01  # ...or less than this share of the move's own contracts

KINDS = ("new", "added", "sold_some", "closed", "bought", "sold")


@dataclass
class Move:
    market: str
    action: str  # "buy" or "sell"
    fills: list[Any] = field(default_factory=list)  # WhaleTrade, oldest first
    before: float | None = None  # contracts held before it (None: not known)
    after: float | None = None

    @property
    def size(self) -> float:
        return sum(t.size for t in self.fills)

    @property
    def usd(self) -> float:
        return sum(t.usd for t in self.fills)

    @property
    def price(self) -> float | None:
        return self.usd / self.size if self.size else None

    @property
    def at(self) -> datetime:
        return self.fills[-1].at

    @property
    def kind(self) -> str:
        if self.action == "buy":
            return "bought" if self.before is None else "new" if self.before <= self._dust() else "added"
        return "sold" if self.after is None else "closed" if self.after <= self._dust() else "sold_some"

    def _dust(self) -> float:
        return max(DUST, DUST_SHARE * self.size)


def _moves(trades: list[Any]) -> dict[str, list[Move]]:
    """Each outcome's moves, oldest first."""
    out: dict[str, list[Move]] = {}
    for t in sorted(trades, key=lambda t: (t.at, t.trade_id)):
        ms = out.setdefault(t.market, [])
        last = ms[-1] if ms else None
        if last is not None and last.action == t.action and (t.at - last.fills[-1].at).total_seconds() <= MOVE_S:
            last.fills.append(t)
        else:
            ms.append(Move(t.market, t.action, [t]))
    return out


def _walk_back(ms: list[Move], held_now: float | None) -> None:
    """Fill in what each move did to the position, newest first, from what they hold now (None: not known)."""
    after = held_now
    for m in reversed(ms):
        if after is None:
            return
        m.after = after
        before = after - m.size if m.action == "buy" else after + m.size
        m.before = max(0.0, before)
        after = m.before


def view(trades: list[Any], positions: list[Any] | None, *, since: float) -> dict[str, Any]:
    """What a watch page shows. ``trades``: the SDK's WhaleTrade, any order; ``positions``: their open positions now
    (WhalePosition), or None when they weren't read (then every move is only "bought" or "sold"). ``since``: the oldest
    time shown (unix seconds).

    ``moves``: newest first, each with what it did (``kind``: KINDS), its dollars, contracts and average price, when,
    and the facts its explanation needs. ``holdings``: what they hold now, biggest first."""
    held = {p.market: p for p in positions or []}
    by_market = _moves(trades)
    for market, ms in by_market.items():
        p = held.get(market)
        if p is not None:
            _walk_back(ms, p.size or 0.0)
        elif positions is not None:
            _walk_back(ms, _not_held(ms))

    out = []
    for market, ms in by_market.items():
        p = held.get(market)
        buys: list[Move] = []
        for m in ms:
            if m.action == "buy":
                buys.append(m)
            if m.at.timestamp() >= since:
                out.append(_move_view(m, p, list(buys), ms))
    out.sort(key=lambda m: m["at"], reverse=True)

    holdings = sorted((_holding(p) for p in held.values() if (p.size or 0) > 0), key=lambda h: -(h["put_in"] or 0))
    return {"moves": out, "holdings": holdings,
            "put_in": round(sum(h["put_in"] or 0 for h in holdings), 2) if positions is not None else None,
            "worth": round(sum(h["value"] or 0 for h in holdings), 2) if positions is not None else None}  # fmt: skip


def _not_held(ms: list[Move]) -> float | None:
    """An outcome read as not held now: 0 if their last move sold (the sale left nothing), else not known (it settled,
    or they redeemed or merged it: not trades)."""
    return 0.0 if ms and ms[-1].action == "sell" else None


def _move_view(m: Move, p: Any, buys: list[Move], ms: list[Move]) -> dict[str, Any]:
    """One move, with the facts its explanation needs. ``buys``: their buys of this outcome up to it, oldest first.
    ``buy_count``, ``rising`` and ``falling``: their buys of it since they opened the position (``opened_at``, when we
    read its opening; else since the oldest trade we read), this one last. ``paid``: the average price they paid for
    what they held (Polymarket's for a position still open, else from their buys we read, when we read its opening)."""
    first = m.fills[0]
    # the start of the position this move is part of, when we read it: their last new position at or before it
    opened = next((x for x in reversed(ms) if x.action == "buy" and x.kind == "new" and x.at <= m.at), None)
    since = [b for b in buys if b.at <= m.at and (opened is None or b.at >= opened.at)]
    run = since if m.action == "buy" else []
    prices = [b.price or 0.0 for b in run]
    rising = len(run) >= 2 and all(b > a for a, b in pairwise(prices))
    falling = len(run) >= 2 and all(b < a for a, b in pairwise(prices))
    paid = p.avg_price if p is not None and p.avg_price else None
    if paid is None and m.action == "sell" and opened is not None:
        size = sum(b.size for b in since)
        paid = sum(b.usd for b in since) / size if size else None
    return {
        "market": m.market, "title": first.title, "outcome": first.outcome, "url": first.url, "token": first.token,
        "action": m.action, "kind": m.kind, "usd": round(m.usd, 2), "size": round(m.size, 2),
        "price": round(m.price, 4) if m.price is not None else None, "fills": len(m.fills),
        "at": m.at.isoformat(), "first_at": first.at.isoformat(),
        "before": None if m.before is None else round(m.before, 2), "after": None if m.after is None else round(m.after, 2),
        "buy_count": len(run), "opened_at": opened.at.isoformat() if opened is not None else None,
        "rising": rising, "falling": falling, "paid": None if paid is None else round(paid, 4),
        "held_now": p is not None and (p.size or 0) > 0,
        "now": None if p is None or p.current_price is None else round(p.current_price, 4),
    }  # fmt: skip


def _holding(p: Any) -> dict[str, Any]:
    put_in = p.size * p.avg_price if p.size is not None and p.avg_price is not None else None
    return {"market": p.market, "title": p.title, "outcome": p.outcome, "size": p.size, "paid": p.avg_price,
            "now": p.current_price, "value": p.value, "pnl": p.pnl,
            "put_in": None if put_in is None else round(put_in, 2)}  # fmt: skip

