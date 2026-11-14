"""Do pump.fun's leaderboard traders also trade on Hyperliquid or Polymarket? For each wallet in pumpfun-boards.json,
pump.fun's public profile gives its Ethereum-style wallet and X username; that wallet is then looked up on Hyperliquid
(public info API) and Polymarket (public data API). Not pre-registered: a descriptive count. Read-only, no keys.

    uv run python research/pumpfun_crossvenue.py > research/pumpfun-crossvenue.txt
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

here = Path(__file__).parent
PUMP = "https://frontend-api-v3.pump.fun"
HL = "https://api.hyperliquid.xyz/info"
PM = "https://data-api.polymarket.com"
# FOMO's top 9 on 2026-10-21 (The_Solstice didn't resolve); EVM wallets from OpenSea's public /fomo/<handle> pages.
FOMO = ("pointfarmcap", "unipcs", "kv4rl", "tvmx", "DumbCrayonEater", "motiyawerey", "SolSwizzle", "leo")

http = httpx.Client(headers={"User-Agent": "Mozilla/5.0 (Macintosh)"}, timeout=30)


def fomo_evm(handle: str) -> str | None:
    import re

    try:
        page = http.get(f"https://opensea.io/fomo/{handle}").text.replace('\\"', '"')
    except httpx.TransportError:
        return None
    m = re.search(r'"chainArch":"EVM","address":"(0x[0-9a-fA-F]{40})"', page)
    return m.group(1) if m else None


FOMO_EVM = {h: e for h in FOMO if (e := fomo_evm(h))}


def call(method: str, url: str, **kw) -> dict | list | None:
    for attempt in range(6):
        try:
            r = http.request(method, url, **kw)
        except httpx.TransportError:
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        return None
    return None


def hyperliquid(evm: str) -> dict:
    state = call("POST", HL, json={"type": "clearinghouseState", "user": evm}) or {}
    fills = call("POST", HL, json={"type": "userFills", "user": evm}) or []
    spot = call("POST", HL, json={"type": "spotClearinghouseState", "user": evm}) or {}
    value = float((state.get("marginSummary") or {}).get("accountValue") or 0)
    spot_usd = sum(float(b.get("total") or 0) for b in spot.get("balances", []) if b.get("coin") == "USDC")
    return {"hlValue": value, "hlSpotUsdc": spot_usd, "hlFills": len(fills),
            "hlLastFill": max((f["time"] for f in fills), default=None)}


def polymarket(evm: str) -> dict:
    acts = call("GET", f"{PM}/activity", params={"user": evm, "limit": 1}) or []
    value = call("GET", f"{PM}/value", params={"user": evm}) or []
    return {"pmActivity": len(acts), "pmValue": (value[0].get("value") if value else 0) or 0}


def one(wallet: str) -> dict:
    u = call("GET", f"{PUMP}/users/{wallet}/overview") or {}
    p = u.get("profile") or {}
    evm = p.get("canonical_evm_wallet")
    row = {"wallet": wallet, "username": p.get("username"), "x": p.get("x_username"), "evm": evm}
    if evm:
        row |= hyperliquid(evm) | polymarket(evm)
    return row


boards = json.loads((here / "pumpfun-boards.json").read_text())
wallets = sorted({e["walletAddress"] for p in ("daily", "weekly", "monthly") for e in boards[p]["entries"]})
with ThreadPoolExecutor(4) as pool:
    rows = list(pool.map(one, wallets))
for handle, evm in FOMO_EVM.items():
    rows.append({"wallet": None, "username": f"fomo:{handle}", "x": None, "evm": evm} | hyperliquid(evm) | polymarket(evm))
(here / "pumpfun-crossvenue.json").write_text(json.dumps(rows, indent=1))

pump = [r for r in rows if r["wallet"]]
with_evm = [r for r in pump if r.get("evm")]
hl_any = [r for r in with_evm if r["hlFills"] or r["hlValue"] > 1 or r["hlSpotUsdc"] > 1]
hl_active = [r for r in with_evm if r["hlFills"] >= 10]
pm_any = [r for r in with_evm if r["pmActivity"] or float(r["pmValue"] or 0) > 1]
print(f"pump.fun leaderboard wallets: {len(pump)}; with an X username: {sum(1 for r in pump if r['x'])}; "
      f"with an Ethereum-style wallet on their pump.fun account: {len(with_evm)}")
print(f"Hyperliquid, that wallet: any fills or balance {len(hl_any)}; 10+ recent fills {len(hl_active)}")
print(f"Polymarket, that wallet: any activity or holdings {len(pm_any)}")
for r in hl_any + pm_any:
    print(f"  {r['username']}: HL value ${r['hlValue']:,.0f}, spot USDC ${r['hlSpotUsdc']:,.0f}, fills {r['hlFills']}; "
          f"PM activity {r['pmActivity']}, PM value ${float(r['pmValue'] or 0):,.0f}")
for r in rows:
    if not r["wallet"]:
        print(f"{r['username']}: HL value ${r['hlValue']:,.0f}, fills {r['hlFills']}; PM activity {r['pmActivity']}")
