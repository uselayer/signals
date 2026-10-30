"""Baskets (the Watchlist): where a group of traders you follow agree, worked out from what each of them holds now. No
reads here: the engine reads (``app._basket_view``), this only works it out, so it can be tested on its own.

A trader *holds a side* of a market when they hold one of its outcomes, at least MIN_USD put in, while its price is
still open (above 2¢, below 98¢: past those it has settled, or as good as, and there's nothing left to decide). A
trader holding both outcomes of one market counts once, on the side they put more into. Where most of the basket's
holders of a market hold one side (2 or more of them, more than hold every other side together), the basket *agrees*
on it; where two or more sides are held and none has that, it's *split*. Counts are facts, never a verdict: agreement
says what they hold, not that it will win.

Each holder of a side also has what their position is worth now (their contracts at the price now: what they have at
stake, not what they once put in), their share of the basket's worth on that side, where it ranks among their own open
positions by worth (so a $100 trader's biggest position and a whale's smallest read as what they are), and what their
trades did to it over the last RECENT_S. That change walks back from what they hold now, as a watch page does
(``signals.watch``): the contracts they hold, less what they bought since, plus what they sold, is what they held then.
It's only told when the trades the poller keeps reach back that far. Otherwise it's *not known*, never "no trades":
also when a trade in that market can't be placed on a side, or when the walk back doesn't add up (they hold fewer
contracts than their buys since: merged, converted or redeemed, none of which is a trade).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from signals import watch

MIN_USD = 10.0  # put in: less than this held (a stray fill, dust left after a sale) isn't holding a side
AGREE_SHOWN = 30
SPLIT_SHOWN = 15
RECENT_S = 7 * 86400  # what their trades did to a position over this long


def _put_in(p: Any) -> float:
    return float(p.size or 0) * float(p.avg_price if p.avg_price is not None else p.current_price or 0)


def _worth(p: Any) -> float:
    return float(p.value if p.value is not None else (p.size or 0) * (p.current_price or 0))


def view(
    held: dict[str, list[Any]],
    names: dict[str, str | None],
    *,
    settled: tuple[float, float],
    trades: dict[str, tuple[list[Any], float]] | None = None,
    cut: frozenset[str] = frozenset(),
    at: float | None = None,
) -> dict[str, Any]:
    """What a basket shows. ``held``: each trader's open positions now (the SDK's WhalePosition), only for the traders
    whose read worked; ``names``: their display names; ``settled``: the prices at or past which a market has settled.
    ``trades``: each trader's trades the poller keeps (the SDK's WhaleTrade) and the time (unix seconds) from which
    all their trades are there; a trader missing has no recent change told. ``cut``: traders whose positions read was
    full, so they hold more open positions than were read (the biggest by worth come first). ``at``: now.

    ``agree``: markets most of their holders hold one side of, most holders first, then most money; each with who
    holds it (biggest worth now first: what they put in and paid, worth now, share of the side's worth, rank among
    their open positions, recent change), what they put in, the average price they paid (by contracts) and the price
    now, and how many hold another side. ``split``: markets held on two or more sides with no side ahead, each side's
    holders."""
    at = time.time() if at is None else at
    low, high = settled
    by_market: dict[str, dict[str, dict[str, Any]]] = {}  # condition -> outcome market -> holder rows
    for wallet, positions in held.items():
        mine: dict[str, Any] = {}  # condition -> their biggest outcome in it
        for p in positions:
            now = p.current_price
            if (p.size or 0) <= 0 or _put_in(p) < MIN_USD or now is None or now <= low or now >= high:
                continue
            cond = p.market.partition(":")[0]
            if cond not in mine or _put_in(p) > _put_in(mine[cond]):
                mine[cond] = p
        for cond, p in mine.items():
            side = by_market.setdefault(cond, {}).setdefault(
                p.market, {"market": p.market, "title": p.title, "outcome": p.outcome, "now": p.current_price, "holders": []}
            )
            side["holders"].append({"wallet": wallet, "name": names.get(wallet), "put_in": round(_put_in(p), 2),
                                    "size": float(p.size), "paid": p.avg_price, "worth": round(_worth(p), 2),
                                    **_rank(p, positions, wallet in cut),
                                    "recent": _recent(p, (trades or {}).get(wallet), at)})  # fmt: skip

    agree, split = [], []
    for cond, sides in by_market.items():
        ranked = sorted(sides.values(), key=lambda s: (-len(s["holders"]), -sum(h["put_in"] for h in s["holders"])))
        top, rest = ranked[0], ranked[1:]
        others = sum(len(s["holders"]) for s in rest)
        if len(top["holders"]) >= 2 and len(top["holders"]) > others:
            agree.append(_side(top) | {"condition": cond, "others": others,
                                       "other_outcomes": [s["outcome"] for s in rest]})  # fmt: skip
        elif rest:
            split.append({"condition": cond, "title": top["title"], "sides": [_side(s) for s in ranked]})
    agree.sort(key=lambda r: (-r["count"], -r["put_in"]))
    split.sort(key=lambda r: (-sum(s["count"] for s in r["sides"]), -sum(s["put_in"] for s in r["sides"])))
    return {"agree": agree[:AGREE_SHOWN], "split": split[:SPLIT_SHOWN], "agree_count": len(agree), "split_count": len(split)}


def _side(s: dict[str, Any]) -> dict[str, Any]:
    holders = sorted(s["holders"], key=lambda h: (-h["worth"], -h["put_in"]))
    size = sum(h["size"] for h in holders if h["paid"] is not None)
    paid = sum(h["size"] * h["paid"] for h in holders if h["paid"] is not None) / size if size else None
    worth = sum(h["worth"] for h in holders)
    keep = ("wallet", "name", "put_in", "paid", "worth", "rank", "of", "of_more", "recent")
    return {"market": s["market"], "title": s["title"], "outcome": s["outcome"], "now": s["now"], "count": len(holders),
            "put_in": round(sum(h["put_in"] for h in holders), 2), "paid": paid, "worth": round(worth, 2),
            "holders": [{k: h[k] for k in keep} | {"share": round(h["worth"] / worth, 4) if worth else None}
                        for h in holders]}  # fmt: skip


def _rank(p: Any, positions: list[Any], more: bool) -> dict[str, Any]:
    """Where ``p`` ranks among the trader's open positions read (``positions``) by worth now: ``rank`` 1 is their
    biggest, ``of`` how many were read, ``of_more`` when they hold more than were read (the biggest are read first, so
    the rank still holds; only ``of`` is a floor)."""
    open_ = [x for x in positions if (x.size or 0) > 0]
    return {"rank": 1 + sum(1 for x in open_ if x is not p and _worth(x) > _worth(p)), "of": len(open_), "of_more": more}


def _recent(p: Any, kept: tuple[list[Any], float] | None, at: float) -> dict[str, Any]:
    """What their trades did to position ``p`` over the last RECENT_S, walked back from what they hold now (as
    ``watch._walk_back``). ``kind``: "new" (they held none of it before), "added", "reduced", "same" (traded, and hold
    what they held), "none" (no trade in it, and the trades kept reach back far enough to say so) or "unknown", with
    ``why``: "unread" (no trades kept for them), "short" (the trades kept reach back only to ``from``), "unplaced" (a
    trade in this market whose side can't be told) or "outside" (they hold fewer contracts than the walk back allows:
    merged, converted or redeemed). ``ratio``: the contracts they hold now over what they held RECENT_S ago."""
    since = at - RECENT_S
    if kept is None:
        return {"kind": "unknown", "why": "unread"}
    ts, complete_from = kept
    if complete_from > since:
        return {"kind": "unknown", "why": "short", "from": datetime.fromtimestamp(complete_from, UTC).isoformat()}
    cond, _, idx = p.market.partition(":")
    mine = []
    for t in ts:
        if t.at.timestamp() < since or t.market.partition(":")[0] != cond:
            continue
        side = _same_side(t, p, idx)
        if side is None:
            return {"kind": "unknown", "why": "unplaced"}
        if side:
            mine.append(t)
    if not mine:
        return {"kind": "none"}
    size = float(p.size or 0)
    net = sum(t.size if t.action == "buy" else -t.size for t in mine)
    dust = max(watch.DUST, watch.DUST_SHARE * sum(t.size for t in mine))
    before = size - net
    if before < -dust:
        return {"kind": "unknown", "why": "outside"}
    if before <= dust:
        return {"kind": "new"}
    kind = "same" if abs(net) <= dust else "added" if net > 0 else "reduced"
    return {"kind": kind, "ratio": round(size / before, 4)}


def _same_side(t: Any, p: Any, idx: str) -> bool | None:
    """Whether trade ``t`` (in the market of position ``p``) is of ``p``'s outcome: by the outcome's name, else by its
    index when it's one a two-outcome market has (Polymarket's feed sometimes sends a junk one). None when neither
    says."""
    if t.outcome and p.outcome:
        return bool(t.outcome == p.outcome)
    t_idx = t.market.partition(":")[2]
    return t_idx == idx if t_idx in ("0", "1") else None
