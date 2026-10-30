"""Ideal paper P&L computed directly, cash flow by cash flow, beside the real one, to check paper_vs_live.run."""

import json
import sys
from collections import defaultdict
from pathlib import Path

d = json.loads(Path(__file__).with_name("nemi_raw.json").read_text())
won = {s["marketId"]: s["result"] for s in d["settlements"]}
sid = sys.argv[1]
cut = sys.argv[2] if len(sys.argv) > 2 else "2099"
ts = sorted((t for t in d["trades"][sid] if t["time"] < cut), key=lambda t: t["time"])
flows = {"ideal": 0.0, "real": 0.0}
held = {"ideal": defaultdict(float), "real": defaultdict(float)}
unknown = set()
for t in ts:
    key = (t["marketId"], t["token"])
    qa, pa, qg, pg, fee = t["askedQty"] or 0, t["askedPrice"] or 0, t["filledQty"] or 0, t["filledAvgPrice"] or 0, t["fee"] or 0
    sign = -1 if t["side"] == "BUY" else 1
    if pa > 0:
        flows["ideal"] += sign * qa * pa
        held["ideal"][key] -= sign * qa
    flows["real"] += sign * qg * pg - fee
    held["real"][key] -= sign * qg
for name in flows:
    pay = 0.0
    for (m, tok), q in held[name].items():
        if abs(q) > 1e-9:
            if m not in won:
                unknown.add(m)
            pay += q * (won.get(m) == tok)
    print(f"{name}: cash flows {flows[name]:,.2f} + payouts {pay:,.2f} = P&L {flows[name] + pay:,.2f}")
print("markets with no result:", len(unknown), "| results known:", len(won), "| orders:", len(ts))
print("winner values seen:", sorted({v for v in won.values()})[:6], "| tokens seen:", sorted({t["token"] for t in ts}))
