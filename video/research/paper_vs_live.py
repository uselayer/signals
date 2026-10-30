"""Fetches what the NemiCosts video is made from: the public example strategies, their trades and every settlement,
from the live engine's own API, into nemi_raw.json (not in git; run this to make it again). Then
`python3 reconcile.py <strategy> [before ISO time]` checks ideal paper against Nemi's fills, and make_costs.py writes
the video's numbers."""

import json
import urllib.request
from pathlib import Path

E = "https://engine-production-fcc0.up.railway.app/api"
RAW = Path(__file__).with_name("nemi_raw.json")
STRATEGIES = ("entry-bands", "vwap-rider")


def get(path: str):
    with urllib.request.urlopen(E + path, timeout=60) as r:
        return json.load(r)


def pages(path: str):
    items, nxt = [], None
    while True:
        sep = "&" if "?" in path else "?"
        d = get(path + (f"{sep}before={nxt}" if nxt is not None else ""))
        items += d["items"]
        nxt = d.get("next")
        if nxt is None:
            return items


if __name__ == "__main__":
    RAW.write_text(json.dumps({
        "strategies": {s["id"]: s for s in get("/strategies") if s["id"] in STRATEGIES},
        "settlements": pages("/settlements?limit=50"),
        "trades": {sid: pages(f"/strategies/{sid}/trades?limit=50") for sid in STRATEGIES},
    }))
    print("saved", RAW)
