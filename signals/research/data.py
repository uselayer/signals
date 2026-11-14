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
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

WALLET = re.compile(r"0x[0-9a-f]{40}")
WINDOW_SLUG = re.compile(r"(?P<family>[a-z0-9]+-updown-(?P<len>\d+)m)-(?P<start>\d{9,11})")
BTC_15M = "btc-updown-15m-"
PAGE = 10_000  # trades per SDK read (``trades_between``'s default limit)
MAX_TRADES = 30_000  # a wallet's trades read for one call, every market; more and it says so (``complete`` false)
MARKET_TRADES = 3_000  # a window's trades by everyone read for one call
# A window's fills count as read in full when the read began this long before it opened (windows are listed about a
# day ahead; pre-open fills are mostly seconds early). Same span as the replay's axis (workspace.PRE_OPEN_MAX_S).
PRE_OPEN_READ_S = 1_800
BINANCE = "https://data-api.binance.vision/api/v3/klines"  # market data only; api.binance.com refuses the US (451)
BINANCE_MAX_S = 2 * 86_400  # 1-minute candles up to here; longer spans step up (BINANCE_STEPS)
# Longer spans: hourly candles to 120 days, daily beyond, each with its high and low (a candle's high and low cover
# every minute in it, so "the highest 1-minute high" over a span is exact at any step).
BINANCE_STEPS = [(120 * 86_400, "1h", 3_600), (None, "1d", 86_400)]
# Polymarket's price history (clob prices-history, 1-minute) refuses a span over about 15 days ("interval is too
# long", measured 13 Nov): read in 14-day pieces and keep one point per step, the step growing with the span.
PRICE_CHUNK_S = 14 * 86_400
PRICE_STEPS = [(2 * 86_400, 60), (15 * 86_400, 900), (120 * 86_400, 3_600), (None, 14_400)]
MARKET_FILLS = 5_000  # a wallet's fills in one market read over its whole life (Polymarket lists 5,000 by offset)
FACTS_AT_ONCE = 20  # Gamma's markets by condition id, per read
MARKETS_TOP = 20  # a market-type scope's tiles: its markets with the most money traded in the range
MARKETS_LOOKED_AT = 60  # markets whose facts are read to find them (the most money traded first)
NEWEST_CHUNK_S = 7 * 86_400  # a market-type scope reads the wallet's trades a week at a time, newest first
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


SCOPE_WORDS = re.compile(r"(today|yesterday)(?:\s+at)?\s+(\d{1,2}):(\d{2})(?:\s*utc)?", re.IGNORECASE)


def scope_time(x: Any, now: float | None = None) -> int:
    """unix() plus the words a plan's scope carries when the agent writes it as it would say it: "now",
    "today 05:30 UTC", "yesterday 22:00" (UTC). A plan's scope written this way once made Start's tiles fail."""
    if isinstance(x, str):
        s, now = x.strip(), time.time() if now is None else now
        if s.lower() == "now":
            return int(now)
        m = SCOPE_WORDS.fullmatch(s)
        if m:
            try:
                d = datetime.fromtimestamp(now, UTC).replace(hour=int(m[2]), minute=int(m[3]), second=0, microsecond=0)
            except ValueError as e:
                raise ReadError(f"Not a time: {x!r}.") from e
            return int((d - timedelta(days=1 if m[1].lower() == "yesterday" else 0)).timestamp())
    return unix(x)


def iso(t: int | float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def window_of(slug: str) -> dict[str, Any] | None:
    """A crypto Up/Down window's family, length and start from its slug (``btc-updown-15m-1794285000``)."""
    m = WINDOW_SLUG.fullmatch(slug or "")
    if not m:
        return None
    start = int(m["start"])
    return {"family": m["family"], "start": start, "end": start + 60 * int(m["len"])}


def window_length(family: str) -> int:
    """A family's window length in seconds (``btc-updown-15m`` → 900); 15 minutes when it doesn't say."""
    m = re.search(r"-(\d+)m-?$", family or "")
    return 60 * int(m[1]) if m else 900


def in_scope(slug: str | None, a: int, b: int) -> bool:
    """Whether a window belongs to a range: it starts in it (``a`` <= start < ``b``). A range 05:30–06:45 holds the
    windows 05:30 to 06:30, each whole, never the 06:45 one a fill bought into a few seconds before it opened."""
    w = window_of(slug or "")
    return bool(w) and a <= w["start"] < b  # type: ignore[index]


def complete_slugs(got: dict[str, Any], a: int, b: int, also: tuple[str, ...] = ()) -> set[str]:
    """The windows whose fills a ``wallet_trades`` answer read from ``a`` to ``b`` holds in full: read from
    PRE_OPEN_READ_S before the window opened to a minute after it closed (block time lags), and nothing cut short.
    ``also``: windows to judge even if the wallet has no fill in them. A window still open is never complete."""
    if got.get("sdk_warnings"):
        return set()
    to = min(b if got.get("complete", True) else int(got.get("read_to") or a) - 1, int(now()))
    slugs = {t.get("slug") for t in got.get("trades") or []} | set(also)
    return {s for s in slugs if s and (w := window_of(s)) and a <= w["start"] - PRE_OPEN_READ_S and w["end"] + 60 <= to}


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


def _when(x: Any) -> int | None:
    """Unix seconds from Gamma's dates ("2026-12-31T12:00:00Z", "2026-09-12 14:03:22+00"), None when missing."""
    if not x:
        return None
    s = str(x).strip().replace(" ", "T", 1)
    if re.search(r"[+-]\d\d$", s):
        s += ":00"
    try:
        return unix(s)
    except ReadError:
        return None


def market_facts(m: dict[str, Any]) -> dict[str, Any]:
    """A Gamma market as the agent and the replay read it: the question, its event (several strikes of one event
    share it), its own rules (what resolves it), when it was listed, ends and closed, its outcomes and tokens, and
    the outcome that won (None while open)."""
    event = (m.get("events") or [{}])[0]
    outcomes = json.loads(m.get("outcomes") or "[]")
    tokens = json.loads(m.get("clobTokenIds") or "[]")
    paid = json.loads(m.get("outcomePrices") or "[]")
    result = None
    if m.get("closed") and len(paid) == len(outcomes):
        result = next((o for o, p in zip(outcomes, paid, strict=True) if float(p) == 1.0), None)
    start = _when(m.get("startDate") or m.get("createdAt") or event.get("startDate"))
    end = _when(m.get("endDate") or event.get("endDate"))
    closed_at = _when(m.get("closedTime")) if m.get("closed") else None
    return {"slug": m.get("slug"), "condition_id": m.get("conditionId"), "question": m.get("question"),
            "event_slug": event.get("slug"), "event_title": event.get("title"),
            "start": start, "end": end, "closed_at": closed_at, "start_iso": iso(start) if start else None,
            "end_iso": iso(end) if end else None, "closed_at_iso": iso(closed_at) if closed_at else None,
            "closed": bool(m.get("closed")), "result": result, "outcomes": outcomes,
            "tokens": dict(zip(outcomes, tokens, strict=False)), "description": m.get("description"),
            "resolution_source": m.get("resolutionSource") or event.get("resolutionSource")}  # fmt: skip


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
        # reads two callers may ask for at once (Start's tiles and the agent's code): the second waits for the first
        self._memo: dict[Any, tuple[float, Any]] = {}
        self._memo_lock = threading.Lock()
        self._key_locks: dict[Any, threading.Lock] = {}

    def _once(self, key: Any, fn: Callable[[], Any], ttl: float) -> Any:
        with self._memo_lock:
            lock = self._key_locks.setdefault(key, threading.Lock())
        with lock:
            hit = self._memo.get(key)
            if hit is not None and time.time() - hit[0] < ttl:
                return hit[1]
            v = fn()
            with self._memo_lock:
                for k in [k for k, (at, _) in self._memo.items() if time.time() - at > 3_600]:
                    self._memo.pop(k, None)
                self._memo[key] = (time.time(), v)
            return v

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
            # "stopped at the limit" (0.19.1) is this loop's own cue to read on, handled below; the rest lose trades.
            sdk_warnings.extend(m for m in caught if "stopped at the limit" not in m)
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

    def window(self, slug: str | None = None, condition_id: str | None = None, *,
               with_trades: bool = True) -> dict[str, Any]:  # fmt: skip
        """One window. ``with_trades`` false skips everyone's trades in it (the case file's replay doesn't use them on
        the API path: a tile costs three reads instead of five or more)."""
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
            merged = out | {k: v for k, v in recorded.items() if v is not None}
            # coverage has the same keys whichever path read it (the agent's code relies on coverage.source)
            merged["coverage"] = {"source": recorded.get("source"), **(recorded.get("coverage") or {})}
            return merged | {"recording_notes": recording_notes(start, end)}
        out["prices"] = {}
        for name, token in out["tokens"].items():  # Polymarket's CLOB history, about 1 point a minute
            pts = self.whales.price_history(token, start - 60, end + 60)
            out["prices"][name] = [[int(t), float(p)] for t, p in pts]
        trades = [
            {"ts": int(r.get("timestamp") or 0), "wallet": r.get("proxyWallet"), "outcome": r.get("outcome"),
             "action": "sell" if str(r.get("side")).upper() == "SELL" else "buy", "price": float(r.get("price") or 0),
             "size": float(r.get("size") or 0), "tx": r.get("transactionHash")}
            for r in (self.whales._poly.market_trades(cid, limit=MARKET_TRADES) if with_trades else [])
        ]  # fmt: skip
        trades.sort(key=lambda r: r["ts"])
        gaps = [b[0] - a[0] for pts in out["prices"].values() for a, b in zip(pts, pts[1:], strict=False)]
        out["trades"] = trades
        if end > BOOKS_FROM:  # Layer recorded it; its window file just isn't built yet (it's built hourly)
            out["book"] = {"available": False, "status": "not_processed",
                           "why": "Layer recorded this window's order book, but it isn't processed yet. Prices here "
                                  "are Polymarket's once-a-minute history."}  # fmt: skip
        else:
            out["book"] = {"available": False, "status": "not_recorded",
                           "why": "Layer didn't record order books before 2 Nov 17:00 UTC. Prices here are "
                                  "Polymarket's once-a-minute history."}  # fmt: skip
        out["coverage"] = {
            "source": "Polymarket API (uselayer)",
            "price_step_s": sorted(gaps)[len(gaps) // 2] if gaps else None,  # measured (median), not assumed
            "price_points": {k: len(v) for k, v in out["prices"].items()},
            "largest_price_gap_s": max(gaps) if gaps else None,
            "trades_read": len(trades) if with_trades else None,
            "trades_complete": len(trades) < MARKET_TRADES if with_trades else None,
        }  # fmt: skip
        if len(trades) >= MARKET_TRADES:
            out["coverage"]["note"] = f"Only the latest {MARKET_TRADES} trades in this market were read."
        return out

    # ---- a market that isn't a 15-minute window (long-dated BTC; later politics, sports) ----

    def markets_facts(self, condition_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Gamma's facts for many markets by condition id, FACTS_AT_ONCE a read (open and closed asked apart), as
        ``market_facts`` shapes them, by condition id. Markets Gamma doesn't list are left out."""
        poly, out = self.whales._poly, {}
        ids = list(dict.fromkeys(c for c in condition_ids if c))
        for i in range(0, len(ids), FACTS_AT_ONCE):
            part = ids[i : i + FACTS_AT_ONCE]
            for closed in (True, False):
                for m in poly.markets(part, closed=closed) or []:
                    if m.get("conditionId") and m["conditionId"] not in out:
                        out[m["conditionId"]] = market_facts(m)
        return out

    def market_fills(self, wallet: str, condition_id: str) -> dict[str, Any]:
        """A wallet's fills in one market over the market's whole life (the SDK reader's ``trades_in``: until uselayer
        has a public read for it), as ``wallet_trades`` rows with the same ids. ``complete`` false: it stopped at
        MARKET_FILLS and the oldest fills weren't read."""
        w = str(wallet).strip().lower()
        if not WALLET.fullmatch(w):
            raise ReadError("That isn't a Polymarket wallet address (0x and 40 hex characters).")
        raw = self.whales._poly.trades_in(w, [condition_id], limit=MARKET_FILLS)
        rows = []
        for r in raw:
            action = "sell" if str(r.get("side")).upper() == "SELL" else "buy"
            row = {"ts": int(r.get("timestamp") or 0), "slug": r.get("slug"), "condition_id": r.get("conditionId"),
                   "outcome": r.get("outcome"), "outcome_index": r.get("outcomeIndex"), "token": r.get("asset"),
                   "action": action, "price": float(r.get("price") or 0), "size": round(float(r.get("size") or 0), 6),
                   "usd": float(r["usdcSize"]) if r.get("usdcSize") is not None else None, "tx": r.get("transactionHash")}  # fmt: skip
            row["id"] = trade_id(row["tx"], row["token"], action, row["price"], row["size"], row["ts"])
            rows.append(row)
        rows = list({r["id"]: r for r in rows}.values())
        rows.sort(key=lambda r: (r["ts"], r["tx"] or ""))
        return {"wallet": w, "condition_id": condition_id, "count": len(rows), "complete": len(raw) < MARKET_FILLS,
                "source": "Polymarket activity for this market (uselayer)", "trades": rows}  # fmt: skip

    def price_series(self, token: str, start: int, end: int) -> tuple[list[list[float]], int]:
        """An outcome's price from ``start`` to ``end`` at one step for the span (PRICE_STEPS: 1 minute to 2 days,
        15 minutes to 15 days, an hour to 120 days, 4 hours beyond), read in PRICE_CHUNK_S pieces: the last price in
        each step, at the second Polymarket took it. Returns (points, step in seconds)."""
        a, b = int(start), int(min(end, now()))
        step = next(s for lim, s in PRICE_STEPS if lim is None or b - a <= lim)
        seen: dict[int, float] = {}
        at = a
        while at <= b:
            hi = min(b, at + PRICE_CHUNK_S)
            for t, p in self.whales.price_history(token, at, hi):
                seen[int(t)] = float(p)
            at = hi + 1
        pts = sorted(seen.items())
        if step > 60:
            last: dict[int, tuple[int, float]] = {}
            for t, p in pts:
                last[t // step] = (t, p)
            pts = [last[k] for k in sorted(last)]
        return [[t, p] for t, p in pts], step

    def market_facts(self, slug: str | None = None, condition_id: str | None = None) -> dict[str, Any]:
        """One market's facts (``market_facts``), by slug or condition id."""
        return market_facts(self._market(slug, condition_id))

    def market(self, slug: str | None = None, condition_id: str | None = None, start: Any = None,
               end: Any = None, *, facts: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
        """One market's facts (``market_facts``: question, its rules and what resolves it, dates, outcomes, result)
        and its outcomes' prices from ``start`` to ``end`` (default: its listing, at most 120 days back, to its end
        or now) at a step for the span (``price_series``). Only the first outcome's history is read; the other's is
        1 minus it (a binary market's two prices add to about $1), and coverage says so."""
        if not slug and not condition_id:
            raise ReadError("Give the market's slug or its condition_id.")
        f = facts or market_facts(self._market(slug, condition_id))
        hi = int(min(unix(end) if end is not None else (f["closed_at"] or f["end"] or now()), now()))
        lo = unix(start) if start is not None else max(f["start"] or hi - 120 * 86_400, hi - 120 * 86_400)
        lo = min(lo, hi)
        names = list(f["tokens"])
        prices: dict[str, list[list[float]]] = {}
        step = None
        if names:
            pts, step = self.price_series(f["tokens"][names[0]], lo, hi)
            prices[names[0]] = pts
            if len(names) == 2:
                prices[names[1]] = [[t, round(1 - p, 6)] for t, p in pts]
        first = prices.get(names[0], []) if names else []
        gaps = [q[0] - p[0] for p, q in zip(first, first[1:], strict=False)]
        return f | {"prices": prices, "price_from": lo, "price_to": hi, "coverage": {
            "source": "Polymarket price history (uselayer), read in 14-day pieces",
            "price_step_s": step, "price_points": len(first),
            "largest_price_gap_s": max(gaps) if gaps else None,
            "price_note": (f"{names[1]}'s price is 1 minus {names[0]}'s: only {names[0]}'s history is read."
                           if len(names) == 2 else None)}}  # fmt: skip

    def wallet_markets(self, wallet: str, start: Any, end: Any, market_type: str, min_days: float | None = None,
                       top: int | None = None) -> dict[str, Any]:  # fmt: skip
        """The wallet's markets of one type (``markets.TYPES``) traded from ``start`` to ``end``, the most money
        traded first: every trade in the range read (``wallet_trades``, every market), the MARKETS_LOOKED_AT busiest
        candidates' facts read, kept when the type matches and the market runs ``min_days`` or more, ``top`` of
        them returned. Start's tiles and the agent's code get the same answer (read once, kept 10 minutes)."""
        from signals.research import markets as M

        mt = M.by_id(market_type)
        if mt is None or mt.unit != "market":
            names = ", ".join(t.id for t in M.TYPES if t.unit == "market")
            raise ReadError(f"market_type must be one of: {names}.")
        w = str(wallet).strip().lower()
        a, b = unix(start), unix(end)
        days = float(mt.min_days if min_days is None else min_days)
        n = int(top or MARKETS_TOP)
        return self._once(("wallet_markets", w, a // 60, b // 60, mt.id, days, n),
                          lambda: self._wallet_markets(w, a, b, mt, days, n), ttl=600)  # fmt: skip

    def _newest_trades(self, w: str, a: int, b: int) -> dict[str, Any]:
        """Every trade from ``a`` to ``b``, read newest week first (a long-dated scope wants the latest markets: read
        oldest first, a busy wallet's 30,000 trades ran out in its first 15 of 90 days, 13 Nov), until MAX_TRADES.
        A week that can't be read whole ends the read there. ``start``: how far back it got; ``complete`` false
        when that's later than ``a``."""
        rows: list[dict[str, Any]] = []
        hi, start, complete, note = b, b, True, ""
        while hi > a:
            lo = max(a, hi - NEWEST_CHUNK_S)
            got = self.wallet_trades(w, lo, hi, None)
            if not got["complete"]:
                complete = False
                break
            rows = got["trades"] + rows
            start, hi = lo, lo - 1
            if len(rows) >= MAX_TRADES and hi > a:
                complete = False
                break
        if not complete:
            note = (f"Partial: read back from {iso(b)} to {iso(start)} only, newest first; it stopped at "
                    f"{MAX_TRADES:,} trades (of every market), so trades before {iso(start)} weren't read.")  # fmt: skip
        return {"trades": rows, "count": len(rows), "start": start, "complete": complete,
                "read_to": b if complete else start, "source": "Polymarket activity via uselayer whales.trades_between",
                "note": note or "Fills as Polymarket records them. Maker or taker isn't known from this read."}  # fmt: skip

    def _wallet_markets(self, w: str, a: int, b: int, mt: Any, days: float, n: int) -> dict[str, Any]:
        from signals.research import markets as M

        got = self._newest_trades(w, a, b)
        by: dict[str, dict[str, Any]] = {}
        for t in got["trades"]:
            if M.is_window(t.get("slug")) or not mt.matches(t.get("slug"), {}):
                continue  # the slug alone rules it out (an Up/Down window, another subject)
            m = by.setdefault(t["condition_id"], {"usd": 0.0, "fills": 0, "first": t["ts"], "last": t["ts"],
                                                  "slug": t.get("slug")})  # fmt: skip
            m["usd"] += float(t.get("usd") or 0)
            m["fills"] += 1
            m["first"], m["last"] = min(m["first"], t["ts"]), max(m["last"], t["ts"])
        ranked = sorted(by, key=lambda c: -by[c]["usd"])
        looked = ranked[:MARKETS_LOOKED_AT]
        facts = self.markets_facts(looked)
        kept = []
        for c in looked:
            f = facts.get(c)
            if not f or not mt.matches(f["slug"], f):
                continue
            runs = (f["end"] - f["start"]) / 86_400 if f["end"] and f["start"] else None
            if runs is not None and runs < days:
                continue
            m = by[c]
            kept.append({"slug": f["slug"], "condition_id": c, "question": f["question"], "event_slug": f["event_slug"],
                         "event_title": f["event_title"], "start_iso": f["start_iso"], "end_iso": f["end_iso"],
                         "runs_days": None if runs is None else round(runs, 1), "closed": f["closed"],
                         "result": f["result"], "rule": mt.rule(f), "usd_in_range": round(m["usd"], 2),
                         "fills_in_range": m["fills"], "first_fill_in_range": m["first"],
                         "last_fill_in_range": m["last"]})  # fmt: skip
        return {"wallet": w, "start": got["start"], "asked_from": a, "end": b, "market_type": mt.id, "label": mt.label,
                "min_days": days,
                "top": n, "trades_read": got["count"], "trades_complete": got["complete"], "read_to": got["read_to"],
                "markets_traded": len(by), "markets_looked_at": len(looked), "matched": len(kept),
                "markets": kept[:n], "source": got["source"],
                "note": (f"The {len(looked)} markets with the most money traded were checked; "
                         f"{max(0, len(ranked) - len(looked))} smaller ones weren't. " + got["note"])}  # fmt: skip

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
                       "Layer's Chainlink recording (from 10 Nov 05:27 UTC) can't be read from here right now.")
                return {"source": "chainlink", "symbol": f"{sym}/USD", "start": a, "end": b, "available": False,
                        "why": why + " For a window, its start price (price_to_beat) and final price come from "
                                     "Polymarket (window tool)."}  # fmt: skip
            return {"source": "chainlink (Layer recording of Polymarket's live data feed)", "symbol": f"{sym}/USD", "unit": "USD",
                    "start": a, "end": b, "available": True, "step": "1 second", "points": pts}  # fmt: skip
        if source != "binance":
            raise ReadError('source must be "binance" or "chainlink".')
        if b - a > BINANCE_MAX_S:
            return self._binance_long(sym, a, b)
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
        return {"source": "binance spot (data-api.binance.vision)", "symbol": f"{sym}USDT", "unit": "USDT (Tether), not USD", "start": a, "end": b,
                "available": True, "step": f"{step_s} second{'s' if step_s > 1 else ''}", "price": "candle close",
                "points": pts}  # fmt: skip


    def _binance_long(self, sym: str, a: int, b: int) -> dict[str, Any]:
        """Binance over more than 2 days: hourly candles to 120 days, daily beyond (BINANCE_STEPS), each with its
        close (``points``) and its high and low (``ranges``), plus the span's highest high and lowest low. Read in
        whole 1,000-candle blocks; a block that has ended is kept, so markets over the same weeks read it once."""
        interval, step_s = next((iv, st) for lim, iv, st in BINANCE_STEPS if lim is None or b - a <= lim)
        block = 1_000 * step_s
        rows: list[list[Any]] = []
        at = a // block * block
        while at <= b:
            hi = at + block - 1

            def read(at: int = at, hi: int = hi) -> Any:
                try:
                    r = self.web.get(BINANCE, params={"symbol": f"{sym}USDT", "interval": interval, "startTime": at * 1000,
                                                      "endTime": hi * 1000, "limit": 1000})  # fmt: skip
                except httpx.HTTPError as e:
                    return {"why": f"Binance couldn't be reached: {type(e).__name__}."}
                if r.status_code in (403, 451):
                    return {"why": f"Binance refuses reads from this server's location (HTTP {r.status_code})."}
                if r.status_code == 400:
                    raise ReadError(f"Binance doesn't list {sym}USDT.")
                r.raise_for_status()
                return r.json()

            got = self._once(("binance", sym, interval, at), read, ttl=10 * 365 * 86_400) if hi < now() - step_s \
                else read()  # fmt: skip
            if isinstance(got, dict):
                with self._memo_lock:
                    self._memo.pop(("binance", sym, interval, at), None)  # a failure is never kept
                return {"source": "binance", "available": False, "why": got["why"]}
            rows += [k for k in got if a < k[0] // 1000 + step_s and k[0] // 1000 <= b]  # the candle holding a too
            at += block
        # a close is the price when its candle ended: stamped at the end, so "the close at or before a fill" is
        # never a price from after it
        pts = [[int(min(k[0] // 1000 + step_s, now())), float(k[4])] for k in rows]
        ranges = [[k[0] // 1000, float(k[2]), float(k[3])] for k in rows]
        top = max(ranges, key=lambda r: r[1], default=None)
        bottom = min(ranges, key=lambda r: r[2], default=None)
        word = {3_600: "1 hour", 86_400: "1 day"}[step_s]
        return {"source": "binance spot (data-api.binance.vision)", "symbol": f"{sym}USDT",
                "unit": "USDT (Tether), not USD", "start": a, "end": b, "available": True, "step": word,
                "price": "candle close", "points": pts, "ranges": ranges,
                "highest": {"t": top[0], "high": top[1]} if top else None,
                "lowest": {"t": bottom[0], "low": bottom[2]} if bottom else None,
                "note": f"{word} candles (the span is over 2 days): points are closes, stamped when each candle ended; "
                        "ranges [t (the candle's start), high, low] hold every minute's high and low inside each "
                        "candle, so the highest high is exact."}  # fmt: skip


def reads() -> Reads:
    """The service's ``Reads``: its own SDK client, Polymarket reads on the "research" budget."""
    from uselayer import Client
    from uselayer.whales import Whales

    from signals.budget import BackgroundHttp, Budget
    from signals.research import recorded

    client = Client()
    rate = float(os.environ.get("RESEARCH_READ_RATE", "4"))
    whales = Whales(BackgroundHttp(client._http, Budget(rate, name="research")), client._layer, client)  # type: ignore[arg-type]
    r2 = recorded.R2.from_env()
    # Layer's built windows first; Chainlink from its raw recording when a window isn't built yet.
    return Reads(whales, recorded_window=recorded.reader(r2), chainlink=recorded.raw_crypto(r2))


def now() -> float:
    return time.time()
