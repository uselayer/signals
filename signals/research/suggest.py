"""Wallets to study, for the ask box's wallet list and "Pick one for me" (owner, 16 Nov: someone without a wallet to
reverse-engineer needs one to start from). Facts only, as the Leaderboard says them: a wallet's rank by trading
profit over 30 days in its category on Signals' own Leaderboard (the engine's ``/api/leaderboard``, from its stored
records, never a Polymarket read), its profit and money traded, and Bot or Human. Never "recommended", never a
reading of whether it will keep making money.

Each market type a breakdown can study gets the top ``PER_TYPE`` that trade it, by rank, always with its best
wallet tagged Human among them when one was found (owner, 16 Nov: "Pick one for me" studies a person first, and
three bots would leave it none; ``with_human``):

- Politics: the Politics category's first ``LOOKED_AT`` (a wallet's category is where most of its trades are).
- BTC 15-minute windows and long-dated BTC: the Crypto category's first ``LOOKED_AT``, each one's latest
  ``RECENT`` trades read once (one SDK read each, on the research budget) and sorted by what they are: a fifth or
  more BTC 15-minute windows, or any long-dated BTC market that isn't a one-day one (``markets.btc_long_matches``).
  A wallet can be in both.
- Soccer: the Sports category's first ``SPORTS_LOOKED_AT``, read the same way, with ``SOCCER_MIN`` or more of
  their recent trades in soccer markets (``markets.soccer_hint``: any league's matches, or the Premier League's
  markets; matches are let in whatever the 7 days a breakdown keeps say).

Built in a background thread at most every ``TTL_S`` and kept in memory; a page asks while it builds and gets what
was kept last (or nothing yet, ``ready`` false)."""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

PER_TYPE = 3  # wallets shown per market type
LOOKED_AT = 30  # the Politics and Crypto categories' first wallets looked at (Crypto's: their recent trades read)
SPORTS_LOOKED_AT = 50  # Sports: its top traders trade every sport (8 of 50 had Premier League, 16 Nov)
RECENT = 500  # recent trades read per Crypto or Sports wallet
SOCCER_MIN = 10  # a soccer trader: at least this many of its recent trades in soccer markets
# a BTC 15-minute trader: at least this share of its recent trades in those windows (16 Nov, the top 30 read: the
# busiest window traders spread over many coins, so half was too strict; a breakdown reads only its BTC windows)
WINDOWS_SHARE = 0.2
# a one-day BTC market ("Bitcoin above $66k on November 15") runs under the 7 days a long-dated breakdown keeps
DAILY = re.compile(r"-on-(january|february|march|april|may|june|july|august|september|october|november|december)-\d")
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


def with_human(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first ``PER_TYPE`` of ``rows`` (rank order), the last swapped for the best-ranked wallet tagged Human when
    none of them is and one is further down."""
    top = rows[:PER_TYPE]
    if top and not any(r.get("bot") == 0 for r in top):
        human = next((r for r in rows[PER_TYPE:] if r.get("bot") == 0), None)
        if human:
            top = top[: PER_TYPE - 1] + [human]
    return top


def kinds_of(slugs: list[str]) -> set[str]:
    """What a wallet's recent markets say it trades: "btc-updown-15m" when a fifth or more are BTC 15-minute
    windows, "btc-long" when any is a long-dated BTC market (not a one-day one), "soccer" when ``SOCCER_MIN`` or
    more are soccer markets."""
    from signals.research import markets as M
    from signals.research.data import BTC_15M

    out: set[str] = set()
    if slugs and sum(s.startswith(BTC_15M) for s in slugs) / len(slugs) >= WINDOWS_SHARE:
        out.add(M.BTC_15M.id)
    if any(not M.is_window(s) and M.btc_long_matches(s, {}) and not DAILY.search(s) for s in slugs):
        out.add(M.BTC_LONG.id)
    if sum(M.soccer_hint(s) for s in slugs) >= SOCCER_MIN:
        out.add(M.SOCCER.id)
    return out


def build(whales: Any, web: httpx.Client, engine: str) -> list[dict[str, Any]]:
    """Every market type's wallets, in ``markets.TYPES`` order; a type with none is left out."""
    from signals.research import markets as M

    found: dict[str, list[dict[str, Any]]] = {t.id: [] for t in M.TYPES}

    def board(category: str, n: int) -> list[dict[str, Any]]:
        try:
            return [_row(r, i + 1, category) for i, r in enumerate(_board(web, engine, category)[:n])]
        except (httpx.HTTPError, ValueError, KeyError):
            return []

    found[M.POLITICS.id] = board("Politics", LOOKED_AT)
    read = board("Crypto", LOOKED_AT) + board("Sports", SPORTS_LOOKED_AT)

    def recent(w: str) -> set[str]:
        try:
            return kinds_of([t.slug or "" for t in whales.trades("polymarket", w, limit=RECENT)])
        except Exception:  # noqa: BLE001 - one wallet that can't be read is left out, never the whole list
            return set()

    with ThreadPoolExecutor(READS_AT_ONCE) as pool:
        kinds = list(pool.map(recent, [r["wallet"] for r in read]))
    for r, k in zip(read, kinds, strict=True):
        for t in k:
            found[t].append(r)
    found = {t: with_human(rows) for t, rows in found.items()}
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
