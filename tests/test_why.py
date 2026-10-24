"""The sentence under a change on a watch page (signals/why.py): which facts the model gets, and what the page may show
of what it writes (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from signals import why

NOW = datetime(2026, 10, 23, 18, tzinfo=UTC)


def move(market: str = "0xa:0", action: str = "buy", kind: str = "new", usd: float = 3000, price: float = 0.5,
         ago: timedelta = timedelta(0), outcome: str = "Yes", url: str = "https://polymarket.com/event/a", **k: Any) -> dict[str, Any]:  # fmt: skip
    return {"market": market, "action": action, "kind": kind, "usd": usd, "size": usd / price, "price": price,
            "at": (NOW - ago).isoformat(), "url": url, "outcome": outcome, "paid": k.pop("paid", None), **k}  # fmt: skip


def view(*moves: dict[str, Any], holdings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    hs = holdings or []
    return {"moves": list(moves), "holdings": hs, "put_in": sum(h["put_in"] for h in hs)}


def test_the_model_gets_the_two_facts_that_stand_out_worked_out_here() -> None:
    m = move()
    v = view(m, holdings=[{"market": "0xa:0", "put_in": 3000, "value": 1500, "paid": 0.5},
                          {"market": "0xb:0", "put_in": 7000, "value": 7000, "paid": 0.4}])  # fmt: skip
    f = why.facts(m, v, {"typical_usd": 1000})
    assert f == {"already_said": "Opened a new position", "outcome": "Yes",
                 "facts": ["this trade was 3.0x their usual trade of $1,000",
                           "the whole position, $3,000 put in, is worth $1,500 now, down $1,500"]}  # fmt: skip
    # the third (30% of their open money, their #2 biggest) waits for a move with less to say
    small = move(usd=900)
    f = why.facts(small, view(small, holdings=[{"market": "0xa:0", "put_in": 3000, "value": 3100, "paid": 0.5},
                                               {"market": "0xb:0", "put_in": 7000, "value": 7000, "paid": 0.4}]), {"typical_usd": 1000})  # fmt: skip
    assert f is not None and f["facts"] == ["this position is 30% of the $10.0K they have in open positions, their #2 biggest"]


def test_nothing_standing_out_means_no_sentence_and_no_call() -> None:
    m = move(usd=900)  # about their usual trade, a position barely moved, a small share of their money, nothing else
    v = view(m, holdings=[{"market": "0xa:0", "put_in": 900, "value": 950, "paid": 0.5},
                          {"market": "0xb:0", "put_in": 90_000, "value": 90_000, "paid": 0.4}])  # fmt: skip
    assert why.facts(m, v, {"typical_usd": 1000}) is None
    assert why.facts(m, v, None) is None  # no record: no size against their usual


def test_a_sale_is_against_what_they_paid_and_other_trades_say_which_side() -> None:
    sale = move(action="sell", kind="sold_some", usd=600, price=0.6, paid=0.5)
    other = move(market="0xa:1", outcome="No", usd=1200, price=0.3, ago=timedelta(minutes=40))  # the other side
    same = move(usd=500, price=0.5, ago=timedelta(hours=3))  # the same outcome
    dust = move(market="0xa:1", outcome="No", usd=40, price=0.3, ago=timedelta(minutes=5))  # a stray fill: left out
    old = move(usd=5000, ago=timedelta(days=2))  # over a day before: not part of this
    f = why.facts(sale, view(sale, other, same, dust, old), None)
    assert f is not None and f["facts"] == [
        "they sold at 60¢ against 50¢ paid, about $100 gained on what they sold",
        "they also bought $1,200 of No (the other side) 40 minutes before this and bought $500 of Yes (the same outcome) "
        "3 hours before this"]  # fmt: skip
    assert f["already_said"] == "Sold some and kept the rest, above what they paid"


def test_the_page_shows_a_sentence_only_when_every_number_and_comparison_is_in_its_facts() -> None:
    f = {"already_said": "Opened a new position", "outcome": "Yes",
         "facts": ["this trade was 3.0x their usual trade of $1,000", "this position is 30% of the $10,000 they have in "
                   "open positions, their #2 biggest"]}  # fmt: skip
    ok = "This trade was 3.0x their usual trade of $1,000, and the position is 30% of their $10,000 in open positions."
    assert why.checked(f"  {ok}\n", f) == ok
    assert why.checked("This was their #2 biggest position, 30% of their $10,000.", f) is not None
    for wrong in ("This trade was 3.5x their usual trade of $1,000.",  # a number it worked out
                  "This was their largest trade, 3.0x their usual trade.",  # a comparison its facts don't make
                  "This trade was 3.0x their usual, more than they have ever put in.",
                  "They bet 3.0x their usual trade.", "They will likely add more.", "They should hold it.",
                  "NONE", "", "They " + "really " * 40 + "did."):  # fmt: skip
        assert why.checked(wrong, f) is None, wrong


def test_the_same_facts_are_kept_as_one_sentence() -> None:
    f = {"already_said": "Bought", "outcome": "Yes", "facts": ["this trade was 3.0x their usual trade of $1,000"]}
    assert why.key_of(f, "m") == why.key_of(dict(f), "m") != why.key_of(f, "other")
    assert why.key_of(f | {"facts": ["this trade was 2.0x their usual trade of $1,000"]}, "m") != why.key_of(f, "m")


def test_the_headline_is_the_page_s() -> None:
    m = move(kind="added", buy_count=3, opened_at=(NOW - timedelta(days=12)).isoformat(), rising=True)
    assert why.headline(m) == "Their 3rd buy of this in 12 days, each at a higher price"
    assert why.headline(move(action="sell", kind="closed", price=0.51, paid=0.54)) == "Sold all of it, below what they paid"
    assert why.headline(move(kind="bought")) == "Bought"
