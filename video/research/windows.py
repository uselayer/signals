"""Stretches where a public strategy was up on ideal paper and down with Nemi's fills: every window of orders that
starts and ends with whole markets (all of a market's orders inside), from 3 hours to the whole history."""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

d = json.loads(Path(__file__).with_name("nemi_raw.json").read_text())
won = {s["marketId"]: s["result"] for s in d["settlements"]}


def pnl(ts):
    out = {"ideal": 0.0, "real": 0.0}
    held = {"ideal": defaultdict(float), "real": defaultdict(float)}
    for t in ts:
        key, sign = (t["marketId"], t["token"]), (-1 if t["side"] == "BUY" else 1)
        qa, pa, qg, pg, fee = t["askedQty"] or 0, t["askedPrice"] or 0, t["filledQty"] or 0, t["filledAvgPrice"] or 0, t["fee"] or 0
        if pa > 0:
            out["ideal"] += sign * qa * pa
            held["ideal"][key] -= sign * qa
        out["real"] += sign * qg * pg - fee
        held["real"][key] -= sign * qg
    for k in out:
        out[k] += sum(q * (won.get(m) == tok) for (m, tok), q in held[k].items())
    return out


for sid, trades in d["trades"].items():
    ts = sorted((t for t in trades if t["marketId"] in won and (t["askedPrice"] or 0) > 0), key=lambda t: t["time"])
    # window edges at market boundaries: each market's first order
    firsts = sorted({min(t["time"] for t in ts if t["marketId"] == m) for m in {t["marketId"] for t in ts}})
    best = []
    for i, a in enumerate(firsts):
        for b in firsts[i + 1:] + ["9999"]:
            w = [t for t in ts if a <= t["time"] < b]
            if not w:
                continue
            hrs = (datetime.fromisoformat(w[-1]["time"].replace("Z", "")) - datetime.fromisoformat(w[0]["time"].replace("Z", ""))).total_seconds() / 3600
            if hrs < 3 or any(t["status"] == "refused" and t.get("code") == "insufficient_funds" for t in w):
                continue
            p = pnl(w)
            if p["ideal"] > 0 and p["real"] < 0:
                best.append((p["ideal"] - p["real"], hrs, len(w), w[0]["time"], w[-1]["time"], round(p["ideal"], 2), round(p["real"], 2)))
    best.sort(reverse=True)
    print(sid, "windows up on paper, down live:", len(best))
    for row in best[:5]:
        print("  gap %.0f | %.1f h | %d orders | %s → %s | paper %+.2f real %+.2f" % row)
