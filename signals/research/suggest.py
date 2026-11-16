"""Wallets to study, for the ask box's wallet list and "Pick one for me" (owner, 16 Nov: someone without a wallet to
reverse-engineer needs one to start from). Facts only, as the Leaderboard says them: a wallet's rank by trading
profit over 30 days in its category on Signals' own Leaderboard (the engine's ``/api/leaderboard``, from its stored
records, never a Polymarket read), its profit and money traded, and Bot or Human. Never "recommended", never a
reading of whether it will keep making money.

Each market type a breakdown can study gets the top few that trade it:

- Politics: the Politics category's first ``PER_TYPE`` (a wallet's category is where most of its trades are).
- BTC 15-minute windows and long-dated BTC: the Crypto category's first ``CRYPTO_LOOKED_AT``, each one's latest
  ``RECENT`` trades read once (one SDK read each, on the research budget) and sorted by what they are: mostly BTC
  15-minute windows, or any long-dated BTC market (``markets.btc_long_matches``). A wallet can be in both.

Built in a background thread at most every ``TTL_S`` and kept in memory; a page asks while it builds and gets what
was kept last (or nothing yet, ``ready`` false)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

PER_TYPE = 3  # wallets shown per market type
CRYPTO_LOOKED_AT = 15  # the Crypto category's first wallets whose recent trades are read
RECENT = 500  # recent trades read per Crypto wallet
WINDOWS_SHARE = 0.5  # a BTC 15-minute trader: at least this share of its recent trades in those windows
TTL_S = 6 * 3_600
RETRY_S = 300  # after a failed build, the next one waits this long
READS_AT_ONCE = 4

_lock = threading.Lock()
_kept: dict[str, Any] = {"types": [], "built_at": None}
_building = False
_tried_at = 0.0


def _board(web: httpx.Client, engine: str, category: str) -> list[dict[str, Any]]:
    r = web.get(f"{engine}/api/leaderboard", params={"category": category, "period": "30d", "sort": "profit"})
    r.raise_for_status()
    return list(r.json().get("rows") or [])


def _row(r: dict[str, Any], rank: int, category: str) -> dict[str, Any]:
    p = (r.get("periods") or {}).get("30d") or {}
    return {"wallet": r["wallet"], "name": r.get("name") or None, "bot": r.get("bot"), "category": category,
            "rank": rank, "profit_30d": p.get("trading_pnl"), "traded_30d": p.get("volume")}  # fmt: skip


def kinds_of(slugs: list[str]) -> set[str]:
    """What a wallet's recent markets say it trades: "btc-updown-15m" when most are BTC 15-minute windows,
    "btc-long" when any is a long-dated BTC market."""
    from signals.research import markets as M
    from signals.research.data import BTC_15M

    out: set[str] = set()
    if slugs and sum(s.startswith(BTC_15M) for s in slugs) / len(slugs) >= WINDOWS_SHARE:
        out.add(M.BTC_15M.id)
    if any(not M.is_window(s) and M.btc_long_matches(s, {}) for s in slugs):
        out.add(M.BTC_LONG.id)
    return out


def build(whales: Any, web: httpx.Client, engine: str) -> list[dict[str, Any]]:
    """Every market type's wallets, in ``markets.TYPES`` order; a type with none is left out."""
    from signals.research import markets as M

    found: dict[str, list[dict[str, Any]]] = {t.id: [] for t in M.TYPES}
    try:
        found[M.POLITICS.id] = [_row(r, i + 1, "Politics") for i, r in enumerate(_board(web, engine, "Politics")[:PER_TYPE])]
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    try:
        crypto = [_row(r, i + 1, "Crypto") for i, r in enumerate(_board(web, engine, "Crypto")[:CRYPTO_LOOKED_AT])]
    except (httpx.HTTPError, ValueError, KeyError):
        crypto = []

    def recent(w: str) -> set[str]:
        try:
            return kinds_of([t.slug or "" for t in whales.trades("polymarket", w, limit=RECENT)])
        except Exception:  # noqa: BLE001 - one wallet that can't be read is left out, never the whole list
            return set()

    with ThreadPoolExecutor(READS_AT_ONCE) as pool:
        kinds = list(pool.map(recent, [r["wallet"] for r in crypto]))
    for r, k in zip(crypto, kinds, strict=True):
        for t in k:
            if len(found[t]) < PER_TYPE:
                found[t].append(r)
    return [{"id": t.id, "label": t.label, "wallets": found[t.id]} for t in M.TYPES if found[t.id]]


def suggestions(make: Any) -> dict[str, Any]:
    """What's kept, and a rebuild started in the background when it's missing or older than ``TTL_S``. ``make``
    returns ``(whales, web, engine)``, called only when a rebuild starts."""
    global _building, _tried_at
    with _lock:
        stale = _kept["built_at"] is None or time.time() - _kept["built_at"] > TTL_S
        start = stale and not _building and time.time() - _tried_at > RETRY_S
        if start:
            _building, _tried_at = True, time.time()
        out = {"types": _kept["types"], "built_at": _kept["built_at"], "ready": _kept["built_at"] is not None}

    if start:
        def run() -> None:
            global _building
            try:
                types = build(*make())
                if not types:  # the engine couldn't be read: keep the last list, try again after RETRY_S
                    print("research: wallet suggestions found none (engine unreachable?)", flush=True)
                    return
                with _lock:
                    _kept.update(types=types, built_at=time.time())
            except Exception as e:  # noqa: BLE001 - logged; the page keeps the last list
                print(f"research: wallet suggestions failed: {type(e).__name__}: {e}", flush=True)
            finally:
                with _lock:
                    _building = False

        threading.Thread(target=run, name="suggestions", daemon=True).start()
    return out
