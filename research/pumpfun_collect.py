"""Collection for pumpfun-preregistered.md: pump.fun's daily, weekly and monthly profit boards (top 100 each) and
every position of every wallet on them. Read-only: pump.fun's public API, no keys. Resumable: wallets already in
--out are skipped; the boards are read once and reused. The analysis is pumpfun_analyze.py.

    uv run python research/pumpfun_collect.py
"""

from __future__ import annotations

import argparse
import gzip
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

API = "https://frontend-api-v3.pump.fun"
PERIODS = ("daily", "weekly", "monthly")
MAX_PAGES = 50
KEEP = (
    "coinMint", "isExited", "amountHeld", "pnlUsd", "pnlPercentage", "realizedPnlUsd", "amountBoughtUsd",
    "valueUsd", "hasTransfers", "likelyLost", "potentialSpam", "hasUntrustedUsdBasis", "updatedAt",
)

ap = argparse.ArgumentParser()
here = Path(__file__).parent
ap.add_argument("--boards", default=str(here / "pumpfun-boards.json"))
ap.add_argument("--out", default=str(here / "pumpfun-positions.jsonl.gz"))
ap.add_argument("--threads", type=int, default=3)
args = ap.parse_args()

http = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30)


def get(path: str, params: dict) -> dict:
    for attempt in range(6):
        r = http.get(API + path, params=params)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
    r.raise_for_status()
    return {}


boards_path = Path(args.boards)
if boards_path.exists():
    boards = json.loads(boards_path.read_text())
else:
    boards = {p: get("/pnl-leaderboard", {"period": p, "limit": 100}) for p in PERIODS}
    boards["readAt"] = int(time.time())
    boards_path.write_text(json.dumps(boards, indent=1))

wallets = sorted({e["walletAddress"] for p in PERIODS for e in boards[p]["entries"]})
out = Path(args.out)
done: set[str] = set()
if out.exists():
    with gzip.open(out, "rt") as f:
        done = {json.loads(line)["wallet"] for line in f}
todo = [w for w in wallets if w not in done]
print(f"{len(wallets)} wallets, {len(done)} already pulled, {len(todo)} to go", flush=True)

lock = threading.Lock()


def pull(wallet: str) -> None:
    positions, pages, count = [], 0, None
    while pages < MAX_PAGES:
        d = get(f"/user-portfolio/{wallet}", {"filter": "all", "page": pages, "pageSize": 100})
        count = (d.get("summary") or {}).get("positionCount", count)
        rows = d.get("positions") or []
        positions += [{k: p.get(k) for k in KEEP} for p in rows]
        pages += 1
        if len(rows) < 100:
            break
    row = {"wallet": wallet, "positionCount": count, "capped": pages >= MAX_PAGES, "positions": positions}
    with lock, gzip.open(out, "at") as f:
        f.write(json.dumps(row) + "\n")
        done.add(wallet)
        print(f"{len(done)}/{len(wallets)} {wallet[:6]} {len(positions)} positions", flush=True)


with ThreadPoolExecutor(args.threads) as pool:
    list(pool.map(pull, todo))
