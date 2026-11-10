"""Every read the research agent makes, in one place, each answer a plain dict the agent's code can use.

Venue reads go through the uselayer SDK (AGENTS.md: venue calls live in the SDK), on the research service's own
budget (``Budget``/``BackgroundHttp`` from ``signals/budget.py``, lane "research"), so an investigation never takes
the engine's share: ``whales.trades_between`` (a wallet's trades by time, with ``slug``) and ``whales.price_history``
(about 1 point a minute), both uselayer 0.19. A window's facts and market trades still use the SDK's Polymarket
reader (``whales._poly``: ``markets``, ``market_trades``, Gamma by slug) until it has public reads for them.

Not venues, so read here: Binance's public market-data mirror (spot candles) and the Signals engine's own public
API (a wallet's record and account). Chainlink is only what Layer's recorder kept (not readable yet: see
``outside_prices``).

Every answer says where it came from (``source``) and what it doesn't cover (``complete``, ``note``), so the agent
can say when data is partial instead of treating a gap as "nothing happened".
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

WALLET = re.compile(r"0x[0-9a-f]{40}")
WINDOW_SLUG = re.compile(r"(?P<family>[a-z0-9]+-updown-(?P<len>\d+)m)-(?P<start>\d{9,11})")
BTC_15M = "btc-updown-15m-"
PAGE = 10_000  # trades per SDK read (``trades_between``'s default limit)
MAX_TRADES = 30_000  # a wallet's trades read for one call, every market; more and it says so (``complete`` false)
MARKET_TRADES = 3_000  # a window's trades by everyone read for one call
BINANCE = "https://data-api.binance.vision/api/v3/klines"  # market data only; api.binance.com refuses the US (451)
BINANCE_MAX_S = 2 * 86_400
ENGINE = os.environ.get("SIGNALS_ENGINE_URL", "https://usesignals.app").rstrip("/")
# Layer's recordings, for the notes a recorded window carries (supervisor brief, 10 Nov; docs/tick-recorder.md in Layer).
BOOKS_FROM = 1_793_638_800  # 2026-11-02 17:00 UTC: up/down windows recorded by default from here
UNUSABLE = [(1_794_074_400, 1_794_089_400)]  # 2026-11-07 18:00–22:10 UTC: the recorder was overloaded
RECONNECT_FIX = 1_794_284_160  # 2026-11-10 04:16 UTC: Layer #640 live; weekday windows before often have big gaps
OUTSIDE_FROM = 1_794_288_420  # 2026-11-10 05:27 UTC: Layer records Chainlink and Binance from here on (#641)


class ReadError(Exception):
    """A read that failed in a way the agent should be told about in words (bad input, a venue refusing)."""


@contextlib.contextmanager
def _sdk_warnings() -> Iterator[list[str]]:
    """The warnings the uselayer SDK logs while the block runs, as text (this thread's only)."""
    caught: list[str] = []
    me = threading.get_ident()

    class Catch(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.thread == me and record.levelno >= logging.WARNING:
                caught.append(record.getMessage())

    log, h = logging.getLogger("uselayer"), Catch()
    log.addHandler(h)
    try:
        yield caught
    finally:
        log.removeHandler(h)


def unix(x: Any) -> int:
    """Unix seconds from unix seconds (int, float or digits) or an ISO 8601 time (naive = UTC)."""
    if isinstance(x, bool):
        raise ReadError(f"Not a time: {x!r}")
    if isinstance(x, int | float):
        return int(x)
    s = str(x).strip()
    if re.fullmatch(r"\d{9,11}(\.\d+)?", s):
        return int(float(s))
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise ReadError(f"Not a time: {x!r}. Give unix seconds or an ISO time like 2026-11-09T14:00:00Z.") from e
    return int((d if d.tzinfo else d.replace(tzinfo=UTC)).timestamp())


def iso(t: int | float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def window_of(slug: str) -> dict[str, Any] | None:
    """A crypto Up/Down window's family, length and start from its slug (``btc-updown-15m-1794285000``)."""
    m = WINDOW_SLUG.fullmatch(slug or "")
    if not m:
        return None
    start = int(m["start"])
    return {"family": m["family"], "start": start, "end": start + 60 * int(m["len"])}


def recording_notes(start: int, end: int) -> list[str]:
    """What's known about Layer's recording of this span, for a window read from the recordings."""
    notes = []
    if end <= BOOKS_FROM:
        notes.append("Before 2 Nov 17:00 UTC Layer didn't record Up/Down windows: no order book exists for it.")
    if any(a < end and start < b for a, b in UNUSABLE):
        notes.append("7 Nov 18:00–22:10 UTC: the recorder was overloaded and this span is marked unusable.")
    if end <= RECONNECT_FIX and datetime.fromtimestamp(start, UTC).weekday() < 5:
        notes.append("Weekday windows before 10 Nov 04:16 UTC often have large gaps (a reconnect bug, since fixed).")
    return notes


def trade_id(tx: Any, asset: Any, action: Any, price: Any, size: Any, ts: Any) -> str:
    """A fill's id, the same everywhere (docs/research-contract.md; Layer's window reader computes it too): the
    first 12 hex characters of sha1("tx|asset|action|price to 4 dp|size to 6 dp|unix seconds")."""
    key = f"{tx}|{asset}|{action}|{float(price or 0):.4f}|{float(size or 0):.6f}|{int(ts or 0)}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _row(t: Any) -> dict[str, Any]:
    """One trade (a uselayer ``WhaleTrade``) as the agent sees it."""
    cid, _, idx = (t.market or "").partition(":")
    return {
        "ts": int(t.at.timestamp()), "slug": getattr(t, "slug", None), "condition_id": cid,
        "outcome": t.outcome, "outcome_index": int(idx) if idx.isdigit() else None, "token": t.token,
        "action": t.action, "price": t.price, "size": round(t.size, 6), "usd": t.usd, "tx": t.trade_id,
    }  # fmt: skip


class Reads:
    """The research service's reads. ``whales`` is the SDK's ``Whales`` on the research budget (``reads()``);
    ``web`` reads non-venue hosts (Binance, the engine). Both are injected in tests."""

    def __init__(self, whales: Any, web: httpx.Client | None = None, *, engine: str = ENGINE,
                 recorded_window: Callable[[str], dict[str, Any] | None] | None = None,
                 chainlink: Callable[[str, int, int], list[list[float]] | None] | None = None) -> None:  # fmt: skip
        self.whales = whales
        self.web = web or httpx.Client(timeout=15.0, headers={"user-agent": "signals-research"})
        self.engine = engine
        # Layer's window reader and Chainlink recordings, once readable (the recorder session's PRs): None = not yet.
        self.recorded_window = recorded_window or (lambda slug: None)
        self.chainlink = chainlink or (lambda symbol, start, end: None)

    # ---- a wallet ----

    def wallet_trades(self, wallet: str, start: Any, end: Any, slug_prefix: str | None = BTC_15M) -> dict[str, Any]:
        w = str(wallet).strip().lower()
        if not WALLET.fullmatch(w):
            raise ReadError("That isn't a Polymarket wallet address (0x and 40 hex characters).")
        a, b = unix(start), unix(end)
        if b < a:
            raise ReadError("The range ends before it starts.")
        sdk_warnings: list[str] = []

        def page(at: int) -> list[dict[str, Any]]:
            # The SDK warns on its "uselayer" logger when Polymarket couldn't list everything (0.19.0: over 5,000
            # trades in one second; 0.19.1: stopped at the limit with more listed): kept, and the read is partial.
            with _sdk_warnings() as caught:
                rows = [_row(t) for t in self.whales.trades_between(w, at, b, limit=PAGE)]
            sdk_warnings.extend(caught)
            return rows

        source = "Polymarket activity via uselayer whales.trades_between"
        # A full page (exactly PAGE) may mean more: read on from its last second, dropping the overlap, until a short
        # page or MAX_TRADES. A second can't be split, so a page ending on a second already started from stops.
        rows, seen, at, complete = [], set(), a, True
        while True:
            got = page(at)
            for r in got:
                key = (r["tx"], r["token"], r["ts"], r["action"], r["price"], r["size"])
                if key not in seen:
                    seen.add(key)
                    rows.append(r)
            if len(got) < PAGE:
                break
            nxt = max(r["ts"] for r in got)
            if len(rows) >= MAX_TRADES or nxt <= at:
                complete = False
                break
            at = nxt
        read_to = max((r["ts"] for r in rows), default=b) if not complete else b
        if slug_prefix:
            rows = [r for r in rows if (r["slug"] or "").startswith(slug_prefix)]
        rows.sort(key=lambda r: (r["ts"], r["tx"] or ""))
        for r in rows:
            r["id"] = trade_id(r["tx"], r["token"], r["action"], r["price"], r["size"], r["ts"])
        out: dict[str, Any] = {
            "wallet": w, "start": a, "end": b, "slug_prefix": slug_prefix, "count": len(rows),
            "windows": len({r["slug"] for r in rows}), "complete": complete, "read_to": read_to, "source": source,
            "trades": rows,
            "note": "Fills as Polymarket records them (block time, a few seconds after the trade). Maker or taker "
                    "isn't known from this read.",
        }  # fmt: skip
        if not complete:
            out["note"] += (f" Partial: stopped after {len(seen)} trades (of every market) at {iso(read_to)}; "
                            f"nothing after that was read. Ask for a range starting there to see the rest.")  # fmt: skip
        if sdk_warnings:
            out["complete"] = False
            out["sdk_warnings"] = list(dict.fromkeys(sdk_warnings))
            out["note"] += " Polymarket couldn't list every trade (sdk_warnings): this history is cut short."
        return out

    def wallet_profile(self, wallet: str) -> dict[str, Any]:
        w = str(wallet).strip().lower()
        if not WALLET.fullmatch(w):
            raise ReadError("That isn't a Polymarket wallet address (0x and 40 hex characters).")
        out: dict[str, Any] = {"wallet": w, "source": f"Signals engine {self.engine}/api/record and /api/account"}
        for key, path in (("record", f"/api/record/{w}"), ("account", f"/api/account/{w}")):
            try:
                r = self.web.get(self.engine + path)
                r.raise_for_status()
                out[key] = r.json()
            except (httpx.HTTPError, ValueError) as e:
                out[key] = None
                out.setdefault("missing", []).append(f"{key}: {type(e).__name__}")
        return out

    # ---- a window ----

    def _market(self, slug: str | None, condition_id: str | None) -> dict[str, Any]:
        poly = self.whales._poly
        if condition_id:
            found = poly.markets([condition_id], closed=True) or poly.markets([condition_id], closed=False)
        else:
            # TODO(uselayer): a public market-by-slug read; until then the SDK reader's own Gamma list call.
            # Gamma leaves closed markets out unless asked, so ask for each, closed first (most windows asked about).
            found = [m for closed in ("true", "false")
                     for m in poly._list(poly._profiles + "/markets", {"slug": slug, "closed": closed})][:1]  # fmt: skip
        if not found:
            raise ReadError(f"Polymarket has no market {slug or condition_id}.")
        return found[0]

    def window(self, slug: str | None = None, condition_id: str | None = None) -> dict[str, Any]:
        if not slug and not condition_id:
            raise ReadError("Give the window's slug (like btc-updown-15m-1794285000) or its condition_id.")
        recorded = self.recorded_window(slug) if slug else None
        m = self._market(slug, condition_id)
        slug = m.get("slug") or slug
        event = (m.get("events") or [{}])[0]
        meta = event.get("eventMetadata") or {}
        span = window_of(slug or "")
        start = span["start"] if span else unix(m.get("eventStartTime") or event.get("startTime"))
        end = span["end"] if span else unix(m.get("endDate"))
        outcomes = json.loads(m.get("outcomes") or "[]")
        tokens = json.loads(m.get("clobTokenIds") or "[]")
        paid = json.loads(m.get("outcomePrices") or "[]")
        result = None
        if m.get("closed") and len(paid) == len(outcomes):
            result = next((o for o, p in zip(outcomes, paid, strict=True) if float(p) == 1.0), None)
        cid = m.get("conditionId")
        out: dict[str, Any] = {
            "slug": slug, "condition_id": cid, "title": m.get("question") or event.get("title"),
            "start": start, "end": end, "start_iso": iso(start), "end_iso": iso(end),
            "price_to_beat": meta.get("priceToBeat"), "final_price": meta.get("finalPrice"), "result": result,
            "closed": bool(m.get("closed")), "resolution_source": m.get("resolutionSource") or event.get("resolutionSource"),
            "tokens": dict(zip(outcomes, tokens, strict=False)),
        }  # fmt: skip
        if recorded:  # Layer's window reader: books, trades, Chainlink and Binance, and its own coverage
            return out | {k: v for k, v in recorded.items() if v is not None} | {
                "recording_notes": recording_notes(start, end)}  # fmt: skip
        out["prices"] = {}
        for name, token in out["tokens"].items():  # Polymarket's CLOB history, about 1 point a minute
            pts = self.whales.price_history(token, start - 60, end + 60)
            out["prices"][name] = [[int(t), float(p)] for t, p in pts]
        trades = [
            {"ts": int(r.get("timestamp") or 0), "wallet": r.get("proxyWallet"), "outcome": r.get("outcome"),
             "action": "sell" if str(r.get("side")).upper() == "SELL" else "buy", "price": float(r.get("price") or 0),
             "size": float(r.get("size") or 0), "tx": r.get("transactionHash")}
            for r in self.whales._poly.market_trades(cid, limit=MARKET_TRADES)
        ]  # fmt: skip
        trades.sort(key=lambda r: r["ts"])
        gaps = [b[0] - a[0] for pts in out["prices"].values() for a, b in zip(pts, pts[1:], strict=False)]
        out["trades"] = trades
        out["book"] = {"available": False, "why": "Order books come from Layer's recordings through its window "
                       "reader, which isn't connected yet. Prices here are Polymarket's price history."}  # fmt: skip
        out["coverage"] = {
            "source": "Polymarket API (uselayer)",
            "price_step_s": sorted(gaps)[len(gaps) // 2] if gaps else None,  # measured (median), not assumed
            "price_points": {k: len(v) for k, v in out["prices"].items()},
            "largest_price_gap_s": max(gaps) if gaps else None,
            "trades_read": len(trades), "trades_complete": len(trades) < MARKET_TRADES,
        }  # fmt: skip
        if len(trades) >= MARKET_TRADES:
            out["coverage"]["note"] = f"Only the latest {MARKET_TRADES} trades in this market were read."
        return out

    # ---- prices outside Polymarket ----

    def outside_prices(self, source: str, start: Any, end: Any, symbol: str = "BTC") -> dict[str, Any]:
        a, b = unix(start), unix(end)
        if b < a:
            raise ReadError("The range ends before it starts.")
        sym = str(symbol).upper().removesuffix("USDT").removesuffix("/USD")
        if source == "chainlink":
            pts = self.chainlink(f"{sym.lower()}/usd", a, b)
            if pts is None:
                why = ("Chainlink wasn't recorded before 10 Nov 05:27 UTC, so these prices don't exist anywhere."
                       if b < OUTSIDE_FROM else
                       "Chainlink is recorded from 10 Nov 05:27 UTC, but only a recorded window (window tool) "
                       "can be read from here.")  # fmt: skip
                return {"source": "chainlink", "symbol": f"{sym}/USD", "start": a, "end": b, "available": False,
                        "why": why + " For a window, its start price (price_to_beat) and final price come from "
                                     "Polymarket (window tool)."}  # fmt: skip
            return {"source": "chainlink (Layer recording of Polymarket's live data feed)", "symbol": f"{sym}/USD",
                    "start": a, "end": b, "available": True, "step": "1 second", "points": pts}  # fmt: skip
        if source != "binance":
            raise ReadError('source must be "binance" or "chainlink".')
        if b - a > BINANCE_MAX_S:
            raise ReadError("Ask Binance for at most 2 days at a time.")
        interval, step_s = ("1s", 1) if b - a <= 3_600 else ("1m", 60)
        pts: list[list[float]] = []
        at = a * 1000
        while at <= b * 1000:
            try:
                r = self.web.get(BINANCE, params={"symbol": f"{sym}USDT", "interval": interval, "startTime": at,
                                                  "endTime": b * 1000, "limit": 1000})  # fmt: skip
            except httpx.HTTPError as e:
                return {"source": "binance", "available": False, "why": f"Binance couldn't be reached: {type(e).__name__}."}
            if r.status_code in (403, 451):
                return {"source": "binance", "available": False,
                        "why": f"Binance refuses reads from this server's location (HTTP {r.status_code})."}  # fmt: skip
            if r.status_code == 400:
                raise ReadError(f"Binance doesn't list {sym}USDT.")
            r.raise_for_status()
            rows = r.json()
            pts += [[k[0] // 1000, float(k[4])] for k in rows]
            if len(rows) < 1000:
                break
            at = rows[-1][0] + step_s * 1000
        return {"source": "binance spot (data-api.binance.vision)", "symbol": f"{sym}USDT", "start": a, "end": b,
                "available": True, "step": f"{step_s} second{'s' if step_s > 1 else ''}", "price": "candle close",
                "points": pts}  # fmt: skip


def reads() -> Reads:
    """The service's ``Reads``: its own SDK client, Polymarket reads on the "research" budget."""
    from uselayer import Client
    from uselayer.whales import Whales

    from signals.budget import BackgroundHttp, Budget
    from signals.research import recorded

    client = Client()
    rate = float(os.environ.get("RESEARCH_READ_RATE", "4"))
    whales = Whales(BackgroundHttp(client._http, Budget(rate, name="research")), client._layer, client)  # type: ignore[arg-type]
    return Reads(whales, recorded_window=recorded.reader(recorded.R2.from_env()))


def now() -> float:
    return time.time()
