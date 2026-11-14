"""Analysis for pumpfun-copy-preregistered.md, from pumpfun-copy-trades.jsonl.gz (written by pumpfun_copy_collect.py).
Prints the results; nothing is fetched.

    uv run python research/pumpfun_copy_analyze.py [copy-trades.jsonl.gz] > research/pumpfun-copy-results.txt
"""

from __future__ import annotations

import gzip
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

here = Path(__file__).parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "pumpfun-copy-trades.jsonl.gz"
DELAYS = ("0", "1", "3", "5", "10")
SECONDS = {"0": "same block", "1": "≈0.4 s", "3": "≈1.2 s", "5": "≈2 s", "10": "≈4 s"}
FEES = (0.0, 0.01, 0.02)

NOT_MEMECOINS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
}

with gzip.open(DATA, "rt") as f:
    wallets = [json.loads(line) for line in f]
for w in wallets:
    w["coins"] = [c for c in w["coins"] if c["mint"] not in NOT_MEMECOINS]


def replay(coin: dict, delay: str | None) -> tuple[float, float, float, int]:
    """(money in, money out before costs, value left at the end, legs with no copy price). delay None = leader."""
    held_leader = held = cost = out = 0.0
    missing = 0
    last_seen = coin["last"]
    for leg in coin["legs"]:
        if delay is None:
            price = leg["price"]
        else:
            price = leg["copy"][delay]
            if price is None:
                missing += 1
                price = coin["last"]
        if not price:
            continue
        if leg["buy"]:
            held += leg["usd"] / price if delay is not None else leg["tokens"]
            cost += leg["usd"]
            held_leader += leg["tokens"]
        else:
            share = min(1.0, leg["tokens"] / held_leader) if held_leader > 0 else 1.0
            sold = held * share
            out += leg["usd"] if delay is None else sold * price
            held -= sold
            held_leader = max(0.0, held_leader - leg["tokens"])
    return cost, out, held * (last_seen or 0.0), missing


def net(cost: float, out: float, left: float, fee: float) -> float:
    return (out + left) * (1 - fee) - cost * (1 + fee)


groups: dict[str, list[dict]] = defaultdict(list)
for w in wallets:
    groups[w["group"]].append(w)

print(f"{len(wallets)} wallets replayed; trades from the 72 hours before each wallet was read\n")
for group in ("bot", "person"):
    ws = groups[group]
    coins = [c for w in ws for c in w["coins"]]
    legs = sum(len(c["legs"]) for c in coins)
    print(f"=== {group}s: {len(ws)} wallets, {len(coins)} coins, {legs} trades "
          f"(median {st.median(w['tradesIn72h'] for w in ws):.0f} trades per wallet in 72 h)")
    lc = sum(replay(c, None)[0] for c in coins)
    lo = sum(replay(c, None)[1] + replay(c, None)[2] for c in coins)
    print(f"  Leader on these coins, own prices: money in ${lc:,.0f}, return {100 * (lo / lc - 1):+.1f}% before costs")
    c1 = [replay(c, "1") for c in coins]
    sold, left = sum(x[1] for x in c1), sum(x[2] for x in c1)
    print(f"  Copier at ≈0.4 s: {100 * left / max(1e-9, sold + left):.0f}% of its end value is still unsold "
          f"(valued at the coin's latest price)")
    for fee in FEES:
        print(f"  Copier, {100 * fee:.0f}% cost per side:")
        for d in DELAYS:
            per_wallet = []
            tc = tn = 0.0
            miss = 0
            for w in ws:
                wc = wn = 0.0
                for c in w["coins"]:
                    cost, out, left, m = replay(c, d)
                    wc += cost
                    wn += net(cost, out, left, fee)
                    miss += m
                if wc > 0:
                    per_wallet.append(wn / wc)
                tc += wc
                tn += wn
            up = sum(1 for r in per_wallet if r > 0)
            print(f"    {SECONDS[d]:>10}: pooled return {100 * tn / tc:+6.1f}%, wallets whose copy made money "
                  f"{up}/{len(per_wallet)}, median wallet {100 * st.median(per_wallet):+6.1f}%"
                  + (f", trades with no later price {miss}" if miss and fee == 0 else ""))
    if group == "bot":
        cost = out = left = 0.0
        per_wallet = []
        for w in ws:
            wc = wn = 0.0
            for c in w["coins"]:
                a, b, l, _ = replay(c, "1")
                wc += a
                wn += net(a, b, l, 0.01)
            if wc:
                per_wallet.append(wn / wc)
            cost += wc
            out += wn
        ok = out / cost > 0 and sum(1 for r in per_wallet if r > 0) >= len(per_wallet) / 2
        print(f"  Verdict (pre-registered: bots, 1 block, 1% per side): {'COPYING WORKS' if ok else 'COPYING DOES NOT WORK'}")
    print()
