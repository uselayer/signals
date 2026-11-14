"""Analysis for pumpfun-preregistered.md, from pumpfun-boards.json and pumpfun-positions.jsonl.gz (written by
pumpfun_collect.py). Prints the results; nothing is fetched. The 2026-10-21 positions (39 MB) are kept out of git,
in ~/dev/research-data/pumpfun-2026-10-21/; pass their path.

    uv run python research/pumpfun_analyze.py [positions.jsonl.gz] > research/pumpfun-results.txt
"""

from __future__ import annotations

import gzip
import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

here = Path(__file__).parent
POSITIONS = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "pumpfun-positions.jsonl.gz"
PERIODS = ("daily", "weekly", "monthly")
MIN_IN = 10.0
MIN_CLOSED = 20

boards = json.loads((here / "pumpfun-boards.json").read_text())
records: dict[str, dict] = {}
with gzip.open(POSITIONS, "rt") as f:
    for line in f:
        r = json.loads(line)
        records[r["wallet"]] = r


def ts(p: dict) -> float:
    return datetime.fromisoformat(p["updatedAt"].replace("Z", "+00:00")).timestamp() if p.get("updatedAt") else 0.0


def usd(x: float) -> str:
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def counted(r: dict) -> list[dict]:
    return [p for p in r["positions"] if not p.get("potentialSpam") and (p.get("amountBoughtUsd") or 0) >= MIN_IN]


print(f"Boards read {datetime.fromtimestamp(boards['readAt']):%Y-%m-%d %H:%M} local; "
      f"{len(records)} wallets pulled\n")

for period in PERIODS:
    b = boards[period]
    W = b["windowStartSec"]
    entries = b["entries"]
    print(f"=== {period} board ({b['periodLabel']}, window from "
          f"{datetime.fromtimestamp(W):%Y-%m-%d %H:%M} local), {len(entries)} traders")

    # 1. Paper vs closed, from the board's own fields.
    total = sum(e["pnlUsd"] for e in entries)
    unreal = sum(e["unrealizedPnlUsd"] for e in entries)
    neg_real = sum(1 for e in entries if e["realizedPnlUsd"] < 0)
    mostly_paper = sum(1 for e in entries if e["pnlUsd"] > 0 and e["unrealizedPnlUsd"] > 0.5 * e["pnlUsd"])
    print(f"1. Board profit {usd(total)}, of which unrealized {usd(unreal)} ({100 * unreal / total:.0f}%)")
    print(f"   Closed trades in the window lost money: {pct(neg_real, len(entries))}")
    print(f"   More than half the profit unsold: {pct(mostly_paper, len(entries))}")

    # 2. One coin, 3. record before the window, 4. warning signs.
    shares, tiny, transfers, capped = [], 0, [], 0
    rec = []
    for e in entries:
        r = records.get(e["walletAddress"])
        if not r:
            continue
        capped += r["capped"]
        ps = counted(r)
        if len(ps) < 5:
            tiny += 1
        if ps:
            transfers.append(sum(1 for p in ps if p.get("hasTransfers")) / len(ps))
        inside = [p["pnlUsd"] or 0 for p in ps if ts(p) >= W]
        gains = sum(x for x in inside if x > 0)
        if gains > 0:
            shares.append(max(inside) / gains)
        closed = [p for p in ps if p.get("isExited") and ts(p) < W]
        if len(closed) >= MIN_CLOSED:
            prof = [p["realizedPnlUsd"] or 0 for p in closed]
            money = sum(p["amountBoughtUsd"] for p in closed)
            rec.append({
                "total": sum(prof),
                "trimmed": sum(prof) - max(prof),
                "win": sum(1 for x in prof if x > 0) / len(prof),
                "money_win": sum(p["amountBoughtUsd"] for p in closed if (p["realizedPnlUsd"] or 0) > 0) / money,
                "n": len(closed),
                "best_share": max(prof) / sum(x for x in prof if x > 0) if any(x > 0 for x in prof) else 0,
            })
    big = sum(1 for s in shares if s >= 0.5)
    print(f"2. Biggest single coin is ≥ 50% of their gains in the window: {pct(big, len(shares))}; "
          f"median share {100 * st.median(shares):.0f}%" if shares else "2. no positions in the window")
    n = len(rec)
    print(f"3. Wallets with ≥ {MIN_CLOSED} closed positions before the window: {pct(n, len(entries))}")
    if rec:
        pos_total = sum(1 for x in rec if x["total"] > 0)
        pos_trim = sum(1 for x in rec if x["trimmed"] > 0)
        print(f"   Made money before the window: {pct(pos_total, n)}; "
              f"still positive without their best coin: {pct(pos_trim, n)}")
        print(f"   Median total {usd(st.median(x['total'] for x in rec))}, "
              f"median without best coin {usd(st.median(x['trimmed'] for x in rec))}")
        print(f"   Median win rate {100 * st.median(x['win'] for x in rec):.0f}%; "
              f"median share of money in winners {100 * st.median(x['money_win'] for x in rec):.0f}%; "
              f"median best coin = {100 * st.median(x['best_share'] for x in rec):.0f}% of all gains")
        print(f"   Median closed positions {st.median(x['n'] for x in rec):.0f}")
        if period == "monthly":
            share = pos_trim / n
            med = st.median(x["trimmed"] for x in rec)
            verdict = "SKILL-LIKE" if share >= 0.6 and med > 0 else "LUCK-LIKE" if share <= 0.4 else "MIXED"
            print(f"   Verdict (pre-registered lines): {verdict}")
    print(f"4. Fewer than 5 positions in all: {pct(tiny, len(entries))}; median share of positions with "
          f"tokens that arrived without a buy {100 * st.median(transfers):.0f}%" if transfers else "")
    if capped:
        print(f"   Capped at 5,000 positions: {capped}")
    print()
