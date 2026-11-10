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
import re
import threading
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import brotli
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

    def request(self, method: str, key: str = "", query: dict[str, str] | None = None, body: bytes = b"") -> httpx.Response:
        """A signed request (S3 SigV4, region "auto") on the bucket, or on ``key`` in it."""
        t = self._now()
        amz, date = t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y%m%d")
        path = "/" + quote(f"{self.bucket}/{key}" if key else self.bucket)
        q = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted((query or {}).items()))
        payload = hashlib.sha256(body).hexdigest()
        headers = {"host": self.host, "x-amz-content-sha256": payload, "x-amz-date": amz}
        signed = ";".join(sorted(headers))
        canonical = "\n".join([method, path, q, *(f"{k}:{headers[k]}" for k in sorted(headers)), "", signed, payload])
        scope = f"{date}/auto/s3/aws4_request"
        to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        k = _sign(_sign(_sign(_sign(("AWS4" + self.secret).encode(), date), "auto"), "s3"), "aws4_request")
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        auth = f"AWS4-HMAC-SHA256 Credential={self.key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"
        url = f"https://{self.host}{path}" + (f"?{q}" if q else "")
        return self.web.request(method, url, headers={**headers, "authorization": auth}, content=body or None)

    def get(self, key: str) -> bytes | None:
        """The object's bytes, or None when it doesn't exist."""
        r = self.request("GET", key)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def keys(self, prefix: str, limit: int = 100) -> list[str]:
        """Up to ``limit`` object keys under ``prefix``."""
        r = self.request("GET", query={"list-type": "2", "prefix": prefix, "max-keys": str(limit)})
        r.raise_for_status()
        return re.findall(r"<Key>([^<]+)</Key>", r.text)


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


RAW_PREFIX = "raw/ticks/crypto"
RAW_FILE = re.compile(r"polymarket-rtds-\d{4}-\d{2}-\d{2}T\d{2}-(\d{13})\.jsonl\.br$")
RAW_FILE_S = 600  # the recorder starts a file about every 10 minutes (and on each restart)
RAW_KEPT = 64  # decoded files kept in memory (windows next to each other share them)


class RawCrypto:
    """Chainlink (and Binance) prices by the second from Layer's raw recording of Polymarket's live-data feed
    (layer#641: raw/ticks/crypto/YYYY/MM/DD/polymarket-rtds-<hour>-<start ms>.jsonl.br, brotli JSONL), for windows
    whose derived file isn't built yet. A line is {"t", "c": "rt<n>" (live) | "rh<n>" (history), "m": the feed's
    message}; a price is m.payload {symbol, timestamp (the price's own ms), value}, or for history m.payload {symbol,
    data: [{timestamp, value}]}. Chainlink symbols have a "/" ("btc/usd"), Binance's don't ("btcusdt"). Keyed on the
    price's own second; live wins over history for the same second."""

    def __init__(self, r2: R2) -> None:
        self.r2 = r2
        self._files: dict[str, dict[str, dict[int, float]]] = {}  # key -> symbol -> second -> price
        self._keys: dict[str, list[str]] = {}  # day prefix -> its file keys
        self._lock = threading.Lock()

    def _day_keys(self, day: str, fresh: bool) -> list[str]:
        with self._lock:
            if not fresh and day in self._keys:
                return self._keys[day]
        keys = self.r2.keys(f"{RAW_PREFIX}/{day}/", 1000)
        with self._lock:
            self._keys[day] = keys
        return keys

    def _file(self, key: str) -> dict[str, dict[int, float]]:
        with self._lock:
            if key in self._files:
                return self._files[key]
        live: dict[str, dict[int, float]] = {}
        hist: dict[str, dict[int, float]] = {}
        body = self.r2.get(key) or b""
        for line in brotli.decompress(body).decode().splitlines() if body else []:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            p = ((e.get("m") or {}).get("payload")) or {}
            sym = p.get("symbol")
            if not sym:
                continue
            if str(e.get("c", "")).startswith("rh"):
                for d in p.get("data") or []:
                    if d.get("timestamp") is not None and d.get("value") is not None:
                        hist.setdefault(sym, {})[int(d["timestamp"]) // 1000] = float(d["value"])
            elif p.get("timestamp") is not None and p.get("value") is not None:
                live.setdefault(sym, {})[int(p["timestamp"]) // 1000] = float(p["value"])
        out = {s: {**hist.get(s, {}), **live.get(s, {})} for s in set(hist) | set(live)}  # live wins
        with self._lock:
            self._files[key] = out
            while len(self._files) > RAW_KEPT:
                self._files.pop(next(iter(self._files)))
        return out

    def prices(self, symbol: str, start: int, end: int) -> list[list[float]] | None:
        """[[unix s, price]] for ``symbol`` ("btc/usd", "btcusdt") from ``start`` to ``end``, or None before the
        recording began (OUTSIDE_FROM). Files are picked by the start time in their names."""
        from signals.research.data import OUTSIDE_FROM

        if end < OUTSIDE_FROM:
            return None
        days = sorted({datetime.fromtimestamp(t, UTC).strftime("%Y/%m/%d") for t in (start - RAW_FILE_S, end)})
        recent = end > datetime.now(UTC).timestamp() - 2 * RAW_FILE_S  # new files may have landed since the last list
        merged: dict[int, float] = {}
        for day in days:
            for key in self._day_keys(day, recent):
                m = RAW_FILE.search(key)
                if not m:
                    continue
                file_start = int(m.group(1)) // 1000
                if file_start > end or file_start < start - 2 * RAW_FILE_S:
                    continue
                for t, p in self._file(key).get(symbol, {}).items():
                    if start <= t <= end:
                        merged[t] = p
        return [[t, merged[t]] for t in sorted(merged)]


def raw_crypto(r2: R2 | None) -> Any:
    """``Reads``' ``chainlink(symbol, start, end)``: Layer's raw recording, or None without a token."""
    if r2 is None:
        return lambda symbol, start, end: None
    raw = RawCrypto(r2)

    def read(symbol: str, start: int, end: int) -> list[list[float]] | None:
        try:
            return raw.prices(symbol, start, end)
        except httpx.HTTPError as e:
            print(f"research: raw crypto prices {symbol} unreadable: {type(e).__name__}", flush=True)
            return None

    return read


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
