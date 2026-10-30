"""Baskets (the Watchlist): where a group of traders you follow agree, worked out from what each of them holds now. No
reads here: the engine reads (``app._basket_view``), this only works it out, so it can be tested on its own.

A trader *holds a side* of a market when they hold one of its outcomes, at least MIN_USD put in, while its price is
still open (above 2¢, below 98¢: past those it has settled, or as good as, and there's nothing left to decide). A
trader holding both outcomes of one market counts once, on the side they put more into. Where most of the basket's
holders of a market hold one side (2 or more of them, more than hold every other side together), the basket *agrees*
on it; where two or more sides are held and none has that, it's *split*. Counts are facts, never a verdict: agreement
says what they hold, not that it will win.

Each holder has what their position is worth now (their contracts at the price now: what they have at stake, not
what they once put in), their share of the side's worth, and where it ranks among their own open positions by worth
(so a $100 trader's biggest position and a whale's smallest read as what they are). Where they agree, ``add_history``
adds each holder's story in that market from their trades in it (the engine reads them by market, so a busy trader's
whole history is there however much else they trade): their last buy or sell of that outcome and when, and, when
every trade of theirs in it was read, when they opened it and what they bought and sold in all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from signals import watch

MIN_USD = 10.0  # put in: less than this held (a stray fill, dust left after a sale) isn't holding a side
AGREE_SHOWN = 30
SPLIT_SHOWN = 15
MOSTLY = 0.7  # one trader with this share of a side's money or more: it's mostly their money
EVEN = 1.25  # the biggest no more than this many times the next: the money is shared evenly between them
_APOSTROPHES = {ord(a): None for a in "'’"}  # Polymarket's trade rows drop them from outcome names


def _put_in(p: Any) -> float:
    return float(p.size or 0) * float(p.avg_price if p.avg_price is not None else p.current_price or 0)


def _worth(p: Any) -> float:
    return float(p.value if p.value is not None else (p.size or 0) * (p.current_price or 0))


def view(
    held: dict[str, list[Any]],
    names: dict[str, str | None],
    *,
    settled: tuple[float, float],
    cut: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """What a basket shows. ``held``: each trader's open positions now (the SDK's WhalePosition), only for the traders
    whose read worked; ``names``: their display names; ``settled``: the prices at or past which a market has settled;
    ``cut``: traders whose positions read was full, so they hold more open positions than were read (the biggest by
    worth come first).

    ``agree``: markets most of their holders hold one side of, most holders first, then most money; each with who
    holds it (biggest worth now first: what they put in and paid, worth now, share of the side's worth, rank among
    their open positions), what they put in, the average price they paid (by contracts) and the price now, and how
    many hold another side. ``split``: markets held on two or more sides with no side ahead, each side's holders."""
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
                                    **_rank(p, positions, wallet in cut)})  # fmt: skip

    agree, split = [], []
    for cond, sides in by_market.items():
        ranked = sorted(sides.values(), key=lambda s: (-len(s["holders"]), -sum(h["put_in"] for h in s["holders"])))
        top, rest = ranked[0], ranked[1:]
        others = sum(len(s["holders"]) for s in rest)
        if len(top["holders"]) >= 2 and len(top["holders"]) > others:
            side = _side(top)
            agree.append(side | {"condition": cond, "others": others, "lead": _lead(side["holders"]),
                                 "other_outcomes": [s["outcome"] for s in rest]})  # fmt: skip
        elif rest:
            split.append({"condition": cond, "title": top["title"], "sides": [_side(s) for s in ranked]})
    agree.sort(key=lambda r: (-r["count"], -r["worth"]))
    split.sort(key=lambda r: (-sum(s["count"] for s in r["sides"]), -sum(s["worth"] for s in r["sides"])))
    return {"agree": agree[:AGREE_SHOWN], "split": split[:SPLIT_SHOWN], "agree_count": len(agree), "split_count": len(split)}


def _side(s: dict[str, Any]) -> dict[str, Any]:
    holders = sorted(s["holders"], key=lambda h: (-h["worth"], -h["put_in"]))
    size = sum(h["size"] for h in holders if h["paid"] is not None)
    paid = sum(h["size"] * h["paid"] for h in holders if h["paid"] is not None) / size if size else None
    worth = sum(h["worth"] for h in holders)
    keep = ("wallet", "name", "put_in", "paid", "worth", "rank", "of", "of_more")
    return {"market": s["market"], "title": s["title"], "outcome": s["outcome"], "now": s["now"], "count": len(holders),
            "put_in": round(sum(h["put_in"] for h in holders), 2), "paid": paid, "worth": round(worth, 2),
            "holders": [{k: h[k] for k in keep} | {"share": round(h["worth"] / worth, 4) if worth else None}
                        for h in holders]}  # fmt: skip


def _lead(holders: list[dict[str, Any]]) -> dict[str, Any]:
    """Whose money a side is (``holders`` biggest worth first): ``kind`` "mostly" (one trader has MOSTLY of it or
    more), "shared" (the biggest has no more than EVEN times the next: ``wallets``, everyone that close to the
    biggest) or "led" (the biggest has the most, but not most of it). The page says it in words."""
    top, nxt = holders[0], holders[1]
    if (top["share"] or 0) >= MOSTLY:
        return {"kind": "mostly", "wallets": [top["wallet"]]}
    if top["worth"] <= EVEN * nxt["worth"]:
        return {"kind": "shared", "wallets": [h["wallet"] for h in holders if top["worth"] <= EVEN * h["worth"]]}
    return {"kind": "led", "wallets": [top["wallet"]]}


def _rank(p: Any, positions: list[Any], more: bool) -> dict[str, Any]:
    """Where ``p`` ranks among the trader's open positions read (``positions``) by worth now: ``rank`` 1 is their
    biggest, ``of`` how many were read, ``of_more`` when they hold more than were read (the biggest are read first, so
    the rank still holds; only ``of`` is a floor)."""
    open_ = [x for x in positions if (x.size or 0) > 0]
    return {"rank": 1 + sum(1 for x in open_ if x is not p and _worth(x) > _worth(p)), "of": len(open_), "of_more": more}


def add_history(out: dict[str, Any], history: dict[str, tuple[list[dict[str, Any]], bool]]) -> None:
    """Each holder of a side where they agree gets ``story`` (``_story``) from ``history``: per trader, their trade
    rows in those markets as Polymarket's activity read gives them, and whether that's all of them. A trader missing
    (their read failed) gets none: their row shows only what they hold, never a guessed "no trades"."""
    for r in out["agree"]:
        cond, _, idx = r["market"].partition(":")
        for h in r["holders"]:
            got = history.get(h["wallet"])
            if got is None:
                h["story"] = None
                continue
            placed = [(t, _of_side(t, idx, r["outcome"])) for t in got[0] if t.get("conditionId") == cond]
            # a trade in this market that can't be placed on a side leaves their totals unknown, not short
            h["story"] = _story([t for t, mine in placed if mine], got[1] and all(m is not None for _, m in placed))


def _story(rows: list[dict[str, Any]], complete: bool) -> dict[str, Any]:
    """A holder's trades of one outcome, as facts: ``last``, their latest move in it (``action``; ``usd``, its
    trades' dollars together; ``from`` and ``at``, its first and last trade), and, when ``complete`` (every trade of
    theirs in it was read), ``opened`` (their first trade in it) and ``bought`` and ``sold`` (dollars, in all).
    Without every trade those totals would be guesses: they're None. A move is their trades one way, each within
    ``watch.MOVE_S`` of the one before, as a watch page groups them: an order filled in pieces reads as one."""
    rows = sorted(rows, key=lambda t: int(t.get("timestamp") or 0))
    usd = lambda t: float(t.get("usdcSize") or 0)  # noqa: E731
    ts = lambda t: int(t.get("timestamp") or 0)  # noqa: E731
    at = lambda t: datetime.fromtimestamp(ts(t), UTC).isoformat()  # noqa: E731
    sell = lambda t: str(t.get("side")).upper() == "SELL"  # noqa: E731
    sells = [t for t in rows if sell(t)]
    move = rows[-1:]
    for t in reversed(rows[:-1]):
        if sell(t) != sell(move[0]) or ts(move[0]) - ts(t) > watch.MOVE_S:
            break
        move.insert(0, t)
    return {
        "last": None if not move else {"action": "sell" if sell(move[0]) else "buy", "usd": round(sum(map(usd, move)), 2),
                                       "from": at(move[0]), "at": at(move[-1])},  # fmt: skip
        "opened": at(rows[0]) if complete and rows else None,
        "bought": round(sum(usd(t) for t in rows if t not in sells), 2) if complete else None,
        "sold": round(sum(usd(t) for t in sells), 2) if complete else None,
    }


def _of_side(t: dict[str, Any], idx: str, outcome: str | None) -> bool | None:
    """Whether trade row ``t`` (in the market) is of outcome ``idx``, named ``outcome``: by the outcome's name
    (apostrophes aside), else by its index when it's one a two-outcome market has. None when neither says (the feed
    sometimes sends a junk index)."""
    if t.get("outcome") and outcome:
        return str(t["outcome"]).translate(_APOSTROPHES) == outcome.translate(_APOSTROPHES)
    i = str(t.get("outcomeIndex"))
    return i == idx if i in ("0", "1") else None
