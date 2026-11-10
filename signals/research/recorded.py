"""Layer's recorded BTC 15-minute windows (Layer's window reader, layer#642, docs/windows.md there): one gzipped
JSON per resolved window in R2, ``layer-history/derived/windows/btc-15m/YYYY/MM/DD/<slug>.json.gz`` (the start's
UTC date), schema ``btc-15m-window-v1``: best prices at every change, top-10 books, everyone's trades, Chainlink and
Binance by the second, and the recording's own coverage.

Read with a read-only R2 token (``R2_ACCOUNT_ID``, ``R2_ACCESS_KEY_ID``, ``R2_SECRET_ACCESS_KEY``, ``R2_BUCKET``
default layer-history), set by the owner. Without them, or for a window not cached yet, ``window`` reads
Polymarket's API instead and says so. A plain signed GET (S3 SigV4), so no AWS library is needed.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

PREFIX = "derived/windows/btc-15m"
SCHEMA = "btc-15m-window-v1"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


class R2:
    def __init__(self, account: str, key_id: str, secret: str, bucket: str = "layer-history",
                 web: httpx.Client | None = None, now: Any = None) -> None:  # fmt: skip
        self.host = f"{account}.r2.cloudflarestorage.com"
        self.key_id, self.secret, self.bucket = key_id, secret, bucket
        self.web = web or httpx.Client(timeout=20.0)
        self._now = now or (lambda: datetime.now(UTC))

    @classmethod
    def from_env(cls) -> R2 | None:
        env = os.environ
        if not all(env.get(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")):
            return None
        return cls(env["R2_ACCOUNT_ID"], env["R2_ACCESS_KEY_ID"], env["R2_SECRET_ACCESS_KEY"],
                   env.get("R2_BUCKET", "layer-history"))  # fmt: skip

    def get(self, key: str) -> bytes | None:
        """The object's bytes, or None when it doesn't exist."""
        t = self._now()
        amz, date = t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y%m%d")
        path = "/" + quote(f"{self.bucket}/{key}")
        payload = hashlib.sha256(b"").hexdigest()
        headers = {"host": self.host, "x-amz-content-sha256": payload, "x-amz-date": amz}
        signed = ";".join(sorted(headers))
        canonical = "\n".join(["GET", path, "", *(f"{k}:{headers[k]}" for k in sorted(headers)), "", signed, payload])
        scope = f"{date}/auto/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        k = _sign(_sign(_sign(_sign(("AWS4" + self.secret).encode(), date), "auto"), "s3"), "aws4_request")
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        auth = f"AWS4-HMAC-SHA256 Credential={self.key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"
        r = self.web.get(f"https://{self.host}{path}", headers={**headers, "authorization": auth})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content


def key_of(slug: str, start: int) -> str:
    return f"{PREFIX}/{datetime.fromtimestamp(start, UTC):%Y/%m/%d}/{slug}.json.gz"


def _rows(j: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """An array of the recording as dicts, by its ``columns`` names."""
    cols = (j.get("columns") or {}).get(name) or []
    return [dict(zip(cols, r, strict=False)) for r in j.get(name) or []]


def shaped(j: dict[str, Any]) -> dict[str, Any]:
    """A recorded window in ``Reads.window``'s shape (unix seconds, Up/Down keys), plus what only it has."""
    best = _rows(j, "prices")
    prices: dict[str, list[list[float]]] = {"Up": [], "Down": []}
    for r in best:  # the price of each side as the middle of its best bid and ask, at each change
        t = int(r.get("receive_ms", 0)) // 1000
        for side in ("up", "down"):
            bid, ask = r.get(f"{side}_bid"), r.get(f"{side}_ask")
            if bid is not None and ask is not None:
                prices[side.capitalize()].append([t, round((float(bid) + float(ask)) / 2, 4)])
    trades = [
        {"ts": int(r.get("venue_unix_s") or 0), "wallet": r.get("taker_wallet"), "outcome": r.get("outcome"),
         "action": str(r.get("side") or "").lower(), "price": r.get("price"), "size": r.get("size"),
         "tx": r.get("transaction_hash"), "stream_ms": r.get("stream_receive_ms")}
        for r in _rows(j, "trades")
    ]  # fmt: skip
    start, end, result = j.get("startPrice") or {}, j.get("endPrice") or {}, j.get("result") or {}
    return {
        "source": f"Layer recording ({j.get('schema') or SCHEMA})",
        "price_to_beat": start.get("polymarket"), "final_price": end.get("polymarket"),
        "chainlink_at_start": start.get("chainlinkAtStart"), "chainlink_at_end": end.get("chainlinkAtEnd"),
        "result": result.get("polymarket"), "result_from_chainlink": result.get("fromChainlink"),
        "prices": prices, "prices_are": "middle of the best bid and ask, at every change",
        "best_prices": best, "trades": sorted(trades, key=lambda r: r["ts"]),
        "book": {"available": True, "levels": 10, "rows": _rows(j, "book"),
                 "note": "Top 10 bids and asks per side, a row only for seconds that changed."},
        "chainlink": j.get("chainlink") or [], "binance": j.get("binance") or [],
        "coverage": j.get("coverage") or {},
    }  # fmt: skip


def reader(r2: R2 | None) -> Any:
    """``Reads``' ``recorded_window(slug)``: the shaped recording, or None (no token, not cached, unreadable)."""
    from signals.research.data import window_of

    def read(slug: str) -> dict[str, Any] | None:
        span = window_of(slug)
        if r2 is None or not span or not slug.startswith("btc-updown-15m-"):
            return None
        try:
            body = r2.get(key_of(slug, span["start"]))
        except httpx.HTTPError as e:
            print(f"research: recorded window {slug} unreadable: {type(e).__name__}", flush=True)
            return None
        return shaped(json.loads(gzip.decompress(body))) if body else None

    return read
