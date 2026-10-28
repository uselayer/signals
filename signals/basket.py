"""Baskets (the Watchlist): where a group of traders you follow agree, worked out from what each of them holds now. No
reads here: the engine reads (``app._basket_view``), this only works it out, so it can be tested on its own.

A trader *holds a side* of a market when they hold one of its outcomes, at least MIN_USD put in, while its price is
still open (above 2¢, below 98¢: past those it has settled, or as good as, and there's nothing left to decide). A
trader holding both outcomes of one market counts once, on the side they put more into. Where most of the basket's
holders of a market hold one side (2 or more of them, more than hold every other side together), the basket *agrees*
on it; where two or more sides are held and none has that, it's *split*. Counts are facts, never a verdict: agreement
says what they hold, not that it will win.
"""

from __future__ import annotations

from typing import Any

MIN_USD = 10.0  # put in: less than this held (a stray fill, dust left after a sale) isn't holding a side
AGREE_SHOWN = 30
SPLIT_SHOWN = 15


def _put_in(p: Any) -> float:
    return float(p.size or 0) * float(p.avg_price if p.avg_price is not None else p.current_price or 0)


def view(held: dict[str, list[Any]], names: dict[str, str | None], *, settled: tuple[float, float]) -> dict[str, Any]:
    """What a basket shows. ``held``: each trader's open positions now (the SDK's WhalePosition), only for the traders
    whose read worked; ``names``: their display names; ``settled``: the prices at or past which a market has settled.

    ``agree``: markets most of their holders hold one side of, most holders first, then most money; each with who
    holds it, what they put in, the average price they paid (by contracts) and the price now, and how many hold
    another side. ``split``: markets held on two or more sides with no side ahead, each side's holders."""
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
                                    "size": float(p.size), "paid": p.avg_price})  # fmt: skip

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
    holders = sorted(s["holders"], key=lambda h: -h["put_in"])
    size = sum(h["size"] for h in holders if h["paid"] is not None)
    paid = sum(h["size"] * h["paid"] for h in holders if h["paid"] is not None) / size if size else None
    return {"market": s["market"], "title": s["title"], "outcome": s["outcome"], "now": s["now"], "count": len(holders),
            "put_in": round(sum(h["put_in"] for h in holders), 2), "paid": paid,
            "holders": [{k: h[k] for k in ("wallet", "name", "put_in", "paid")} for h in holders]}  # fmt: skip
