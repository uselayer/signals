"""Track records and the Leaderboard: a wallet's record from a few cheap reads (profit and volume by period, weeks up,
the profit line, the win rate from positions closed, usual trade), kept in the directory, copied from kept scores, and
ranked by what they did, never by a verdict (no network: the SDK's reads are stand-ins)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from signals import app as engine
from signals import records
from signals.directory import BOARD_MIN_CLOSED, RECORD_REFRESH_S, Directory, Seen, record_of_score

DAY = 86400
NOW = 1_800_000_000.0
AMY = "0x" + "a1" * 20
BEN = "0x" + "b2" * 20
CAL = "0x" + "c3" * 20
DAN = "0x" + "d4" * 20


def history(days: int, per_day: float, volume_per_day: float = 1000.0, now: float = NOW) -> list[dict[str, Any]]:
    """Polymarket's hourly profit history, one point a day: running totals from their first trade ``days`` ago."""
    start = now - days * DAY
    return [{"timestamp": int(start + i * DAY), "realized_pnl": per_day * i, "unrealized_pnl": 0.0,
             "volume_usdc": volume_per_day * i, "wallet_income": 0.0} for i in range(days + 1)]  # fmt: skip


def position(pnl: float, closed_days_ago: float | None = None, ended_days_ago: float | None = None) -> Any:
    closed = None if closed_days_ago is None else datetime.fromtimestamp(NOW - closed_days_ago * DAY, UTC)
    ended = None if ended_days_ago is None else datetime.fromtimestamp(NOW - ended_days_ago * DAY, UTC).isoformat()
    return SimpleNamespace(pnl=pnl, closed_at=closed, end_date=ended)


def positions(rows: list[Any], complete: bool = True) -> Any:
    return SimpleNamespace(positions=rows, complete=complete)


# ---- a record ----


def test_a_record_has_profit_volume_and_profit_per_dollar_for_each_period_and_all_time() -> None:
    rec = records.build(history(100, 10.0), positions([]), [], NOW)
    p = rec["periods"]
    assert p["7d"]["trading_pnl"] == 70 and p["7d"]["volume"] == 7000 and p["7d"]["return_per_dollar"] == 0.01
    assert p["30d"]["trading_pnl"] == 300 and p["90d"]["trading_pnl"] == 900
    assert p["all"]["trading_pnl"] == 1000 and p["all"]["volume"] == 100_000  # from their first trade
    assert rec["since"] == int(NOW - 100 * DAY)


def test_weeks_before_their_first_trade_are_unknown_never_losing_weeks() -> None:
    rec = records.build(history(20, 10.0), positions([]), [], NOW)
    assert rec["weeks_known"] == 3 and rec["weeks_up"] == 3  # 20 days: each week that ended after their first trade
    assert rec["pnl_weeks"][:9] == [None] * 9


def test_the_win_rate_counts_positions_closed_in_profit_in_each_period_unredeemed_losers_included() -> None:
    rows = [position(50, closed_days_ago=2), position(-20, closed_days_ago=3), position(10, closed_days_ago=20),
            position(-100, ended_days_ago=25),  # settled, never redeemed: a loss Polymarket's closed list leaves out
            position(5, closed_days_ago=60)]  # fmt: skip
    p = records.build(history(100, 1.0), positions(rows), [], NOW)["periods"]
    assert (p["7d"]["won"], p["7d"]["closed"]) == (1, 2)
    assert (p["30d"]["won"], p["30d"]["closed"]) == (2, 4)
    assert (p["90d"]["won"], p["90d"]["closed"]) == (3, 5)


def test_a_period_a_cut_read_doesnt_reach_back_through_has_no_win_rate() -> None:
    rows = [position(1, closed_days_ago=d / 10) for d in range(1, 50)]  # 49 closed in 5 days, more not read
    p = records.build(history(100, 1.0), positions(rows, complete=False), [], NOW)["periods"]
    assert p["7d"]["closed"] is None and p["30d"]["closed"] is None  # oldest read is inside both: unknown, never 49


def test_without_their_positions_the_rest_of_the_record_stands() -> None:
    rec = records.build(history(40, 5.0), None, [], NOW)
    assert rec["periods"]["30d"]["trading_pnl"] == 150 and rec["periods"]["30d"]["closed"] is None
    assert rec["positions_complete"] is None


def test_the_usual_trade_adds_up_one_orders_fills_so_a_big_trader_doesnt_look_small() -> None:
    fills = [(NOW - 100 + i, True, "0xm1", 1000.0) for i in range(25)]  # one $25K order in 25 fills
    fills += [(NOW - 5000, True, "0xm2", 30000.0), (NOW - 9000, True, "0xm3", 20000.0)]
    rec = records.build([], positions([]), fills, NOW)
    assert rec["typical_usd"] == 25000 and rec["buys_30d"] == 3 and rec["last_buy"] == NOW - 76


def test_a_record_read_takes_the_profit_history_and_the_completed_positions() -> None:
    asked: list[Any] = []

    class Sdk:
        _poly = SimpleNamespace(pnl_history=lambda w: asked.append(("pnl", w)) or history(40, 1.0))

        def completed_positions(self, w: str, **k: Any) -> Any:
            asked.append(("positions", w, k))
            raise engine.VenueError("rate_limited", "Polymarket's firewall said no.", venue="polymarket")

    rec = records.read(Sdk(), AMY, [], NOW)  # type: ignore[arg-type]
    assert asked == [("pnl", AMY), ("positions", AMY, {"max_pages": records.CLOSED_PAGES, "held_pages": records.HELD_PAGES})]
    assert rec["periods"]["30d"]["trading_pnl"] == 30 and rec["periods"]["30d"]["closed"] is None


# ---- the directory ----


@pytest.fixture
def d(tmp_path: Any) -> Directory:
    return Directory(tmp_path / "directory.db")


def rec(pnl30: float, last_buy: float = NOW - DAY, won: int | None = 6, closed: int | None = 10, vol30: float = 10_000,
        weeks: tuple[int, int] = (6, 12)) -> dict[str, Any]:  # fmt: skip
    per = {p: {"trading_pnl": pnl30, "volume": vol30, "return_per_dollar": pnl30 / vol30, "won": won, "closed": closed}
           for p in ("7d", "30d", "90d")}  # fmt: skip
    per["all"] = {"trading_pnl": pnl30, "volume": vol30}
    return {"read_at": NOW, "periods": per, "weeks_up": weeks[0], "weeks_known": weeks[1], "typical_usd": 50.0,
            "last_buy": last_buy, "pnl_weeks": None, "pnl_daily": None}  # fmt: skip


def test_the_leaderboard_lists_public_traders_active_in_30_days_with_a_few_positions_closed(d: Directory) -> None:
    d.add([Seen(w, "leaderboard", "PNL MONTH OVERALL") for w in (AMY, BEN, CAL)] + [Seen(DAN, "search")])
    d.keep_record(AMY, rec(500), at=NOW)
    d.keep_record(BEN, rec(900, last_buy=NOW - 40 * DAY), at=NOW)  # no buy in 30 days
    d.keep_record(CAL, rec(800, closed=BOARD_MIN_CLOSED - 1), at=NOW)  # too few positions closed
    d.keep_record(DAN, rec(1000), at=NOW)  # only known because someone searched for them: never listed
    got = d.leaderboard(now=NOW)
    assert [r["wallet"] for r in got["rows"]] == [AMY] and got["total"] == 1


def test_each_sort_ranks_by_what_they_did_and_a_small_sample_never_tops_a_rate(d: Directory) -> None:
    d.add([Seen(w, "leaderboard", "PNL MONTH OVERALL") for w in (AMY, BEN, CAL)])
    d.keep_record(AMY, rec(500, won=9, closed=10, vol30=100_000), at=NOW)
    d.keep_record(BEN, rec(900, won=60, closed=80, vol30=900), at=NOW)  # under $1K traded: no profit per dollar
    d.keep_record(CAL, rec(100, won=8, closed=8, vol30=2_000, weeks=(3, 3)), at=NOW)  # 8 of 8: too few to rank
    order = lambda sort: [r["wallet"] for r in d.leaderboard("30d", sort, now=NOW)["rows"]]  # noqa: E731
    assert order("profit") == [BEN, AMY, CAL]
    assert order("return") == [CAL, AMY, BEN]  # 5% beats 0.5%; BEN's $900 traded ranks last
    assert order("win") == [BEN, AMY, CAL]  # 60 of 80 beats 9 of 10 on the bottom of its range; 8 of 8 unranked
    assert order("volume") == [AMY, CAL, BEN]
    assert order("weeks") == [AMY, BEN, CAL]  # 3 of 3 weeks is under 4 weeks of history: unranked


def test_a_record_read_schedules_the_next_look_and_says_nothing_against_them(d: Directory) -> None:
    d.add([Seen(AMY, "leaderboard", "PNL MONTH OVERALL")])
    d.keep_record(AMY, rec(500), at=NOW)
    w = d.wallet(AMY)
    assert w is not None and w["status"] == "checked" and w["not_recommended"] is None
    assert w["next_check"] == NOW + RECORD_REFRESH_S


def test_kept_scores_are_copied_once_without_a_win_rate_and_never_over_a_record_read(d: Directory) -> None:
    score = {"wallet": AMY, "segment": "no_edge", "trading_pnl": 5000.0, "volume": 50_000.0, "typical_usd": 80.0,
             "periods": {"30d": {"trading_pnl": 700.0, "volume": 7000.0, "return_per_dollar": 0.1}},
             "pnl_weeks": [None, 10.0, -5.0, 20.0], "last_buy": datetime.fromtimestamp(NOW - DAY, UTC).isoformat()}
    d.keep_scores([score, score | {"wallet": BEN}], "background", at=NOW - DAY)
    d.keep_record(BEN, rec(1), at=NOW)  # BEN's own record was read: the score doesn't replace it
    assert d.seed_records() == (1, AMY)
    assert d.seed_records(AMY) == (0, None)
    amy = d.record(AMY)
    assert amy is not None and amy["via"] == "score" and amy["periods"]["30d"]["trading_pnl"] == 700
    assert amy["periods"]["30d"]["closed"] is None and amy["weeks_up"] == 2 and amy["weeks_known"] == 3
    assert d.record(BEN)["via"] == "read"  # type: ignore[index]
    assert d.wallet(AMY)["status"] == "scored"  # type: ignore[index]  # copying changes no schedule


def test_a_score_kept_before_profit_by_period_isnt_copied() -> None:
    assert record_of_score({"wallet": AMY, "trading_pnl": 1.0}, NOW) is None


# ---- the evaluation ----


def trade(at: float, action: str = "buy", market: str = "0xm1", usd: float = 100.0) -> Any:
    return SimpleNamespace(at=datetime.fromtimestamp(at, UTC), action=action, market=f"{market}:0", usd=usd)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    engine._cache.clear()
    monkeypatch.setattr(engine, "STORE_DIR", tmp_path)
    monkeypatch.setattr(engine, "SKILL_TEST", False)
    monkeypatch.setitem(engine._evaluate_state, "since_launch", dict.fromkeys(engine.OUTCOMES, 0))
    return tmp_path


def test_a_wallet_that_bought_lately_gets_a_record_and_one_that_didnt_only_the_quick_check(store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    now = time.time()
    read: list[str] = []

    class Sdk:
        _poly = SimpleNamespace(pnl_history=lambda w: read.append(w) or history(40, 2.0, now=now))
        _trades = {AMY: [trade(now - 3600)], BEN: [trade(now - 95 * DAY)], CAL: [trade(now - 40 * DAY)]}

        def trades(self, venue: str, w: str, limit: int) -> list[Any]:
            return self._trades.get(w, [])

        def completed_positions(self, w: str, **k: Any) -> Any:
            return positions([position(10, closed_days_ago=1)])

        def score(self, *a: Any, **k: Any) -> Any:
            raise AssertionError("the skill test is off: no score")

    monkeypatch.setattr(engine, "background", lambda: Sdk())
    d = engine.directory()
    d.add([Seen(w, "leaderboard", "PNL MONTH OVERALL") for w in (AMY, BEN, CAL)])
    r = engine.evaluate_round()
    assert r["done"]["recorded"] == 1 and r["done"]["dormant"] == 1 and r["done"]["not_trading_lately"] == 1
    assert read == [AMY]
    assert d.record(AMY)["periods"]["30d"]["trading_pnl"] == 60  # type: ignore[index]
    assert d.wallet(BEN)["not_recommended"] == "dormant" and d.record(BEN) is None  # type: ignore[index]


def test_the_leaderboard_api_pages_the_records_with_each_rows_win_rate(store: Any) -> None:
    d = engine.directory()
    d.add([Seen(AMY, "leaderboard", "PNL MONTH OVERALL", name="amy")])
    busy = rec(500, last_buy=time.time() - DAY)
    busy["periods"]["30d"] |= {"won": None, "closed": None}  # closed more than a record reads in 30 days
    busy["periods"]["90d"] |= {"won": None, "closed": None}
    busy["periods"]["7d"] |= {"won": 40, "closed": 90}
    d.keep_record(AMY, busy)
    api = TestClient(engine.app)
    got = api.get("/api/leaderboard?period=30d&sort=profit").json()
    assert got["total"] == 1 and got["rows"][0]["name"] == "amy"
    assert got["rows"][0]["win"] == {"won": 40, "closed": 90, "days": 7}  # the longest period read in full
    assert api.get("/api/leaderboard?sort=skill").status_code == 400
