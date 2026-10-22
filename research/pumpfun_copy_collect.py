"""Collection for pumpfun-copy-preregistered.md: for sampled bot-paced and people-paced wallets from the leaderboard
study, 72 hours of trades, and for each trade the first other trade on that coin's tape 0, 1, 3, 5 and 10 blocks
later, plus each coin's latest price. Read-only: pump.fun's public API, no keys. Resumable: wallets already in --out
are skipped. The analysis is pumpfun_copy_analyze.py.

    uv run python research/pumpfun_copy_collect.py --positions ~/dev/research-data/pumpfun-2026-10-21/pumpfun-positions.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx

API = "https://frontend-api-v3.pump.fun"
SOL = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
SOL_ID = 1399811149
DELAYS = (0, 1, 3, 5, 10)
PER_GROUP, PER_WALLET, PER_COIN, MAX_TRADES = 30, 40, 30, 3000
HOURS = 72
SEED = 21
# Wrapped SOL and dollar coins: not memecoins, and their tapes are too busy to page.
NOT_MEMECOINS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB",
}

here = Path(__file__).parent
ap = argparse.ArgumentParser()
ap.add_argument("--positions", required=True)
ap.add_argument("--out", default=str(here / "pumpfun-copy-trades.jsonl.gz"))
ap.add_argument("--threads", type=int, default=6)
ap.add_argument("--since", type=int, help="forward run: trades after this unix time instead of the last 72 hours "
                "(e.g. the boards' readAt, 1792618459)")
args = ap.parse_args()

http = httpx.Client(headers={"User-Agent": "Mozilla/5.0"}, timeout=30)


def get(path: str, params: dict) -> dict:
    status = None
    for attempt in range(9):
        try:
            r = http.get(API + path, params=params)
        except httpx.TransportError:
            time.sleep(min(60, 2 ** attempt))
            continue
        status = r.status_code
        if status == 200:
            return r.json()
        if status in (429, 500, 502, 503, 504):
            time.sleep(min(60, 2 ** attempt))
            continue
        r.raise_for_status()
    raise RuntimeError(f"gave up on {path} (last status {status})")


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


# Pace per wallet, as in pumpfun_followup.py: distinct coins per day in a board's window, fastest board counting.
boards = json.loads((here / "pumpfun-boards.json").read_text())
with gzip.open(Path(args.positions).expanduser(), "rt") as f:
    records = {r["wallet"]: r for r in map(json.loads, f)}
pace: dict[str, float] = defaultdict(float)
for period in ("daily", "weekly", "monthly"):
    W = boards[period]["windowStartSec"]
    days = (boards["readAt"] - W) / 86400
    for e in boards[period]["entries"]:
        r = records.get(e["walletAddress"])
        if not r:
            continue
        ps = [p for p in r["positions"] if not p.get("potentialSpam") and (p.get("amountBoughtUsd") or 0) >= 10]
        p = sum(1 for x in ps if x.get("updatedAt") and ts(x["updatedAt"]) >= W) / days
        if r["capped"]:
            p = max(p, 20)
        pace[e["walletAddress"]] = max(pace[e["walletAddress"]], p)

rng = random.Random(SEED)
bots = sorted(w for w, p in pace.items() if p >= 20)
people = sorted(w for w, p in pace.items() if p < 5)
rng.shuffle(bots)
rng.shuffle(people)
sample = [(w, "bot") for w in bots[:PER_GROUP]] + [(w, "person") for w in people[:PER_GROUP]]

out = Path(args.out)
done: set[str] = set()
if out.exists():
    with gzip.open(out, "rt") as f:
        done = {json.loads(line)["wallet"] for line in f}
todo = [(w, g) for w, g in sample if w not in done]
print(f"{len(bots)} bots, {len(people)} people; sampling {len(sample)}, {len(todo)} to go", flush=True)
lock = threading.Lock()


def leader_trades(wallet: str, since: float) -> list[dict]:
    trades, cursor = [], None
    while len(trades) < MAX_TRADES:
        q = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        d = get(f"/user-trades/{wallet}", q)
        page = d.get("trades") or []
        trades += [t for t in page if t.get("chainId") == SOL_ID and t.get("slotIndexId") and ts(t["timestamp"]) >= since]
        cursor = d.get("nextCursor")
        if not page or not cursor or ts(page[-1]["timestamp"]) < since:
            break
    return trades


def copy_prices(t: dict, wallet: str) -> dict[str, float | None]:
    sid = t["slotIndexId"]
    slot, txi, ev = int(sid[:12]), int(sid[12:18]), int(sid[18:])
    ms = int(ts(t["timestamp"]) * 1000)
    found: dict[str, float | None] = {str(k): None for k in DELAYS}
    q: dict = {"after": f"{slot}-{txi}-{ev}-{ms}", "limit": 100}
    for _ in range(5):
        d = get(f"/trades/{SOL}/{t['mint']}", q)
        page = d.get("trades") or []
        for x in page:
            if x["trader"]["address"] == wallet or x["txId"] == t["tx"] or not x.get("priceUsd"):
                continue
            for k in DELAYS:
                if found[str(k)] is None and int(x["blockId"]) >= slot + k:
                    found[str(k)] = float(x["priceUsd"])
        if all(v is not None for v in found.values()) or not page or not d.get("cursor"):
            break
        q = {"cursor": d["cursor"], "limit": 100}
    return found


def pull(item: tuple[str, str]) -> None:
    wallet, group = item
    now = time.time()
    trades = leader_trades(wallet, args.since or now - HOURS * 3600)
    by_coin: dict[str, list[dict]] = defaultdict(list)
    for t in sorted(trades, key=lambda t: t["slotIndexId"]):
        by_coin[t["mint"]].append(t)
    coins = sorted(m for m, ts_ in by_coin.items() if ts_[0]["isBuy"] and m not in NOT_MEMECOINS)
    random.Random(f"{SEED}:{wallet}").shuffle(coins)
    rows = []
    skipped = 0
    for mint in coins[:PER_WALLET]:
        try:
            legs = [{
                "buy": t["isBuy"], "usd": t["amountUsd"], "tokens": t["baseAmount"], "price": t["priceUsd"],
                "slotIndexId": t["slotIndexId"], "time": t["timestamp"], "copy": copy_prices(t, wallet),
            } for t in by_coin[mint][:PER_COIN]]
            last = [x for x in get(f"/trades/{SOL}/{mint}", {"limit": 20}).get("trades") or [] if x.get("priceUsd")]
        except RuntimeError:
            skipped += 1
            continue
        rows.append({"mint": mint, "legs": legs, "last": float(last[0]["priceUsd"]) if last else None,
                     "truncated": len(by_coin[mint]) > PER_COIN})
    row = {"wallet": wallet, "group": group, "pace": pace[wallet], "readAt": int(now), "tradesIn72h": len(trades),
           "coinsWithBuyFirst": len(coins), "coinsSkipped": skipped, "coins": rows}
    with lock, gzip.open(out, "at") as f:
        f.write(json.dumps(row) + "\n")
        done.add(wallet)
        print(f"{len(done)}/{len(sample)} {group} {wallet[:6]} {len(trades)} trades, {len(rows)} coins", flush=True)


def safe_pull(item: tuple[str, str]) -> None:
    try:
        pull(item)
    except Exception as e:  # one wallet's failure is logged and retried on the next run, not fatal
        print(f"FAILED {item[1]} {item[0][:6]}: {e!r}", flush=True)


with ThreadPoolExecutor(args.threads) as pool:
    for _ in pool.map(safe_pull, todo):
        pass
