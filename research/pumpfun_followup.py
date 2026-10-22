"""Follow-up to pumpfun-results.txt, NOT pre-registered: the monthly board's skill-like record came with thousands of
positions per wallet, so the boards are split by trading pace (distinct coins per day in the window). A person
rarely trades 20 different coins a day for a month; a bot does. Same rules as pumpfun_analyze.py otherwise.

    uv run python research/pumpfun_followup.py [positions.jsonl.gz] > research/pumpfun-followup.txt
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
with gzip.open(POSITIONS, "rt") as f:
    records = {r["wallet"]: r for r in map(json.loads, f)}


def ts(p: dict) -> float:
    return datetime.fromisoformat(p["updatedAt"].replace("Z", "+00:00")).timestamp() if p.get("updatedAt") else 0.0


def usd(x: float) -> str:
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def counted(r: dict) -> list[dict]:
    return [p for p in r["positions"] if not p.get("potentialSpam") and (p.get("amountBoughtUsd") or 0) >= MIN_IN]


PACES = (("under 5 coins/day", 0, 5), ("5–20 coins/day", 5, 20), ("20+ coins/day", 20, float("inf")))

for period in PERIODS:
    b = boards[period]
    W, end = b["windowStartSec"], boards["readAt"]
    days = (end - W) / 86400
    print(f"=== {period} board ({b['periodLabel']})")
    groups: dict[str, list[dict]] = {name: [] for name, _, _ in PACES}
    for e in b["entries"]:
        r = records.get(e["walletAddress"])
        if not r:
            continue
        ps = counted(r)
        pace = sum(1 for p in ps if ts(p) >= W) / days
        if r["capped"] and pace < 20:
            pace = 20  # 5,000 positions and still counting: at least bot pace
        closed = [p for p in ps if p.get("isExited") and ts(p) < W]
        prof = [p["realizedPnlUsd"] or 0 for p in closed]
        for name, lo, hi in PACES:
            if lo <= pace < hi:
                groups[name].append({"e": e, "n": len(closed), "prof": prof,
                                     "size": st.median(p["amountBoughtUsd"] for p in ps) if ps else 0})
    for name, rows in groups.items():
        if not rows:
            continue
        paper = sum(r["e"]["unrealizedPnlUsd"] for r in rows) / max(1, sum(r["e"]["pnlUsd"] for r in rows))
        board_profit = sum(r["e"]["pnlUsd"] for r in rows)
        rec = [r for r in rows if r["n"] >= MIN_CLOSED]
        line = (f"  {name}: {len(rows)} traders, {usd(board_profit)} of board profit ({100 * paper:.0f}% unsold), "
                f"median position {usd(st.median(r['size'] for r in rows))}")
        print(line)
        if rec:
            trim = [sum(r["prof"]) - max(r["prof"]) for r in rec]
            win = [sum(1 for x in r["prof"] if x > 0) / len(r["prof"]) for r in rec]
            print(f"     before the window (≥ {MIN_CLOSED} closed): positive without best coin "
                  f"{pct(sum(1 for t in trim if t > 0), len(rec))}, median {usd(st.median(trim))}, "
                  f"median win rate {100 * st.median(win):.0f}%")
    print()
