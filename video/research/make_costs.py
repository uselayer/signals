"""The numbers in the NemiCosts video, from nemi_raw.json (the live engine's API, fetched by paper_vs_live.py fetch).

vwap-rider's orders from its first until CUT: ideal paper (every order filled in full at the price it asked, no fee)
against Nemi's fills (what it really paid, fee included), both settled on Polymarket's results. CUT (owner, 10-30: show
a strategy that won on paper) is its first 366 orders, up on paper and down live (windows.py lists such stretches);
its last 16 orders before its money ran out (17:25 UTC) lost on both. Writes ../src/nemi-costs.json."""

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
d = json.loads((HERE / "nemi_raw.json").read_text())
won = {s["marketId"]: s["result"] for s in d["settlements"]}
SID, EXAMPLE = "vwap-rider", "239"
CUT = sys.argv[1] if len(sys.argv) > 1 else "2026-10-27T16:40:41"
ts = sorted((t for t in d["trades"][SID] if t["time"] < CUT), key=lambda t: t["time"])

pnl = {"ideal": 0.0, "real": 0.0}
held = {"ideal": defaultdict(float), "real": defaultdict(float)}
fees = slip = 0.0
for t in ts:
    key, sign = (t["marketId"], t["token"]), (-1 if t["side"] == "BUY" else 1)
    qa, pa, qg, pg, fee = t["askedQty"] or 0, t["askedPrice"] or 0, t["filledQty"] or 0, t["filledAvgPrice"] or 0, t["fee"] or 0
    if pa > 0:
        pnl["ideal"] += sign * qa * pa
        held["ideal"][key] -= sign * qa
    pnl["real"] += sign * qg * pg - fee
    held["real"][key] -= sign * qg
    fees += fee
    slip += qg * (pg - pa) * -sign
for name in pnl:
    pnl[name] += sum(q * (won[m] == tok) for (m, tok), q in held[name].items())

ex = next(t for t in d["trades"][SID] if t["id"] == EXAMPLE)
out = {
    "strategy": SID, "orders": len(ts), "from": ts[0]["time"], "to": ts[-1]["time"],
    "paper": round(pnl["ideal"], 2), "real": round(pnl["real"], 2),
    "fees": round(fees, 2), "slippage": round(slip, 2),
    "other": round(pnl["ideal"] - pnl["real"] - fees - slip, 2),  # partial and refused fills
    "example": {"id": ex["id"], "time": ex["time"], "token": ex["token"], "qty": ex["askedQty"], "asked": ex["askedPrice"],
                "paid": ex["filledAvgPrice"], "fee": round(ex["fee"], 2),
                "levels": [[b["price"], b["taken"]] for b in ex["bookAtFill"] if b["taken"] > 0]},
}
(HERE.parent / "src" / "nemi-costs.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps(out))
