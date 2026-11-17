"""Wallets to study (signals/research/suggest.py): the ask box's wallet list and "Pick one for me" (owner, 16 Nov),
built from Signals' own Leaderboard (the engine's /api/leaderboard, never a Polymarket leaderboard read) and one
read of each Crypto wallet's recent trades to tell BTC 15-minute traders from long-dated BTC ones."""

from __future__ import annotations

import os
import tempfile
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

os.environ.setdefault("RESEARCH_STORE_DIR", tempfile.mkdtemp(prefix="research-test-"))

from signals.research import suggest as S  # noqa: E402
from signals.research.store import Store  # noqa: E402

ENGINE = "https://engine.test"


def _w(n: int) -> str:
    return "0x" + f"{n:02x}" * 20


def _board_row(n: int, name: str | None, pnl: float, bot: int | None = 0) -> dict[str, Any]:
    return {"wallet": _w(n), "name": name, "bot": bot, "periods": {"30d": {"trading_pnl": pnl, "volume": pnl * 4}}}


BOARDS = {
    "Politics": [_board_row(1, "pol-a", 500_000), _board_row(2, "pol-b", 400_000, 1), _board_row(3, None, 300_000),
                 _board_row(4, "pol-d", 200_000)],
    "Crypto": [_board_row(10, "windows-bot", 800_000, 1), _board_row(11, "long-btc", 300_000),
               _board_row(12, "eth-only", 250_000), _board_row(13, "both", 100_000)],
    # Premier League: three bots ahead of a person, and a wallet with only a couple of its markets
    "Sports": [_board_row(20, "epl-bot-a", 900_000, 1), _board_row(21, "epl-bot-b", 800_000, 1),
               _board_row(22, "nba-only", 700_000), _board_row(23, "epl-bot-c", 600_000, 1),
               _board_row(24, "epl-person", 500_000, 0), _board_row(25, "two-epl", 400_000, 0)],
}
EPL = "epl-ars-eve-2026-11-22-ars"
WINDOW = "btc-updown-15m-1794800000"
LONG = "will-bitcoin-reach-150000-by-december-31-2026"
TRADES = {
    _w(10): [WINDOW] * 9 + ["eth-updown-15m-1794800000"],
    _w(11): ["will-trump-win-x", LONG, "some-sports-game"],
    _w(12): ["will-ethereum-reach-10000-by-december-31-2026"],
    _w(13): [WINDOW] * 6 + [LONG] * 4,
    **{_w(n): [EPL] * 12 for n in (20, 21, 23, 24)},
    _w(22): ["nba-lal-bos-2026-11-20"] * 30,
    _w(25): [EPL] * 2 + ["nba-lal-bos-2026-11-20"] * 20,
}


class FakeWhales:
    def __init__(self) -> None:
        self.asked: list[tuple[str, str, int]] = []

    def trades(self, venue: str, wallet: str, *, limit: int = 50) -> list[Any]:
        self.asked.append((venue, wallet, limit))
        return [SimpleNamespace(slug=s) for s in TRADES.get(wallet, [])]


def _web(boards: dict[str, list[dict[str, Any]]] | None = None, fail: bool = False) -> tuple[httpx.Client, list[str]]:
    seen: list[str] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if fail:
            return httpx.Response(503)
        assert req.url.path == "/api/leaderboard"
        assert req.url.params["period"] == "30d" and req.url.params["sort"] == "profit"
        return httpx.Response(200, json={"rows": (boards or BOARDS).get(req.url.params["category"], [])})

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


def test_recent_markets_tell_15_minute_traders_from_long_dated_ones() -> None:
    assert S.kinds_of([WINDOW] * 3 + ["x"]) == {"btc-updown-15m"}
    assert S.kinds_of([WINDOW] + ["x"] * 9) == set()  # a few windows among other markets isn't a 15-minute trader
    assert S.kinds_of([WINDOW] + ["x"] * 3) == {"btc-updown-15m"}  # a quarter is: its BTC windows are read alone
    assert S.kinds_of(["bitcoin-above-66k-on-november-15-2026"]) == set()  # one day: under a monthly scope's 7
    assert S.kinds_of(["x", LONG]) == {"btc-yearly"}  # one yearly BTC market is enough to study
    assert S.kinds_of(["will-bitcoin-reach-100k-in-november-2026"]) == {"btc-monthly"}
    assert S.kinds_of([WINDOW] * 6 + [LONG] * 4) == {"btc-updown-15m", "btc-yearly"}
    assert S.kinds_of([]) == set()
    assert S.kinds_of([EPL] * 10) == {"soccer"}  # matches count: listed weeks ahead, they pass the 7 days
    assert S.kinds_of(["will-arsenal-win-the-2026-27-english-premier-league"] * 9 + ["x"]) == set()  # under SOCCER_MIN
    assert S.kinds_of(["bitcoin-up-or-down-november-16-12pm-et"]) == set()  # an Up/Down market is neither


def test_each_market_type_gets_its_top_wallets_from_signals_leaderboard() -> None:
    whales = FakeWhales()
    web, seen = _web()
    types = S.build(whales, web, ENGINE)
    by = {t["id"]: t for t in types}
    assert [t["id"] for t in types] == ["btc-updown-15m", "btc-yearly", "politics", "soccer"]  # TYPES order
    assert all(u.startswith(ENGINE + "/api/leaderboard") for u in seen)  # Signals' board, never Polymarket's
    pol = by["politics"]["wallets"]
    assert [w["name"] for w in pol] == ["pol-a", "pol-b", None]  # PER_TYPE, ranked by 30-day trading profit
    assert pol[0] == {"wallet": _w(1), "name": "pol-a", "bot": 0, "category": "Politics", "rank": 1,
                      "profit_30d": 500_000, "traded_30d": 2_000_000}  # fmt: skip
    assert [w["name"] for w in by["btc-updown-15m"]["wallets"]] == ["windows-bot", "both"]
    assert [w["name"] for w in by["btc-yearly"]["wallets"]] == ["long-btc", "both"]
    assert by["btc-yearly"]["wallets"][0]["rank"] == 2  # its rank in the Crypto category, as the Leaderboard shows it
    assert {w for _, w, _ in whales.asked} == {_w(n) for n in (10, 11, 12, 13, 20, 21, 22, 23, 24, 25)}  # Crypto, Sports
    # three bots trade the Premier League ahead of a person: the person takes the third place (owner, 16 Nov)
    assert [(w["name"], w["rank"]) for w in by["soccer"]["wallets"]] == [("epl-bot-a", 1), ("epl-bot-b", 2),
                                                                                ("epl-person", 5)]
    assert all(v == "polymarket" and n == S.RECENT for v, _, n in whales.asked)


def test_each_list_keeps_its_best_human() -> None:
    r = [{"name": n, "bot": b} for n, b in (("a", 1), ("b", 1), ("c", 1), ("d", None), ("e", 0), ("f", 0))]
    assert [x["name"] for x in S.with_human(r)] == ["a", "b", "e"]
    assert [x["name"] for x in S.with_human(r[3:])] == ["d", "e", "f"]  # one is already there: rank order kept
    assert [x["name"] for x in S.with_human(r[:4])] == ["a", "b", "c"]  # no human anywhere: the top three
    assert S.with_human([]) == []


def test_a_type_with_no_wallet_is_left_out_and_an_unreadable_wallet_skipped() -> None:
    class Flaky(FakeWhales):
        def trades(self, venue: str, wallet: str, *, limit: int = 50) -> list[Any]:
            if wallet == _w(11):
                raise RuntimeError("Polymarket turned it away")
            return super().trades(venue, wallet, limit=limit)

    web, _ = _web({"Politics": [], "Crypto": BOARDS["Crypto"][:3], "Sports": []})
    types = S.build(Flaky(), web, ENGINE)
    assert [(t["id"], [w["name"] for w in t["wallets"]]) for t in types] == [("btc-updown-15m", ["windows-bot"])]
    web, _ = _web(fail=True)
    assert S.build(FakeWhales(), web, ENGINE) == []


def _wait_built(timeout: float = 5.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with S._lock:
            if not S._building:
                return
        time.sleep(0.02)
    raise AssertionError("the suggestions build didn't finish")


def test_the_route_answers_at_once_and_builds_in_the_background(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from signals.research import server

    monkeypatch.setattr(S, "_kept", {"types": [], "built_at": None})
    monkeypatch.setattr(S, "_tried_at", 0.0)
    web, _ = _web()
    monkeypatch.setattr(server, "store", Store(os.path.join(tempfile.mkdtemp(), "s.db")))
    monkeypatch.setattr(server, "_reads", SimpleNamespace(whales=FakeWhales(), web=web, engine=ENGINE))
    server.app.dependency_overrides[server.auth.user_of] = lambda: "alice"
    try:
        c = TestClient(server.app)
        first = c.get("/api/research/suggestions")
        assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
        assert first.json()["ready"] is False and first.json()["types"] == []  # nothing kept yet: it's building
        _wait_built()
        again = c.get("/api/research/suggestions").json()
        assert again["ready"] is True and [t["id"] for t in again["types"]] == ["btc-updown-15m", "btc-yearly", "politics",
                                                                               "soccer"]
    finally:
        server.app.dependency_overrides.clear()


def test_suggestions_are_signed_in_only() -> None:
    from signals.research import server

    route = next(r for r in server.app.routes if getattr(r, "path", "") == "/api/research/suggestions")
    assert server.auth.user_of in [d.call for d in route.dependant.dependencies]  # type: ignore[attr-defined]
