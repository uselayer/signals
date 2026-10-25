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
from uselayer import ProfitHistory

from signals import app as engine
from signals import records
from signals.directory import BOARD_MIN_CLOSED, RECORD_REFRESH_S, Directory, Seen, record_of_score

DAY = 86400
NOW = 1_800_000_000.0
AMY = "0x" + "a1" * 20
BEN = "0x" + "b2" * 20
CAL = "0x" + "c3" * 20
DAN = "0x" + "d4" * 20


def history(days: int, per_day: float, volume_per_day: float = 1000.0, now: float = NOW) -> ProfitHistory:
    """Polymarket's hourly profit history, one point a day: running totals from their first trade ``days`` ago."""
    start = now - days * DAY
    return ProfitHistory([{"timestamp": int(start + i * DAY), "realized_pnl": per_day * i, "unrealized_pnl": 0.0,
             "volume_usdc": volume_per_day * i, "wallet_income": 0.0} for i in range(days + 1)])  # fmt: skip


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
    assert p["30d"]["realized"] == 300  # profit taken (history() has nothing open), a trader's page's headline
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
    cap = records.CLOSED_PAGES * 50
    rows = [position(1, closed_days_ago=10 * (i + 1) / cap) for i in range(cap)]  # the closed list's cap, in 10 days
    p = records.build(history(100, 1.0), positions(rows, complete=False), [], NOW)["periods"]
    assert (p["7d"]["won"], p["7d"]["closed"]) == (round(cap * 0.7), round(cap * 0.7))  # read in full back to 10 days
    assert p["30d"]["closed"] is None and p["90d"]["closed"] is None  # the oldest read is inside both: unknown


def test_old_unredeemed_losers_never_make_a_cut_read_look_like_it_reached_back() -> None:
    """A busy trader: their newest closed positions (mostly wins) reach back 10 days, their losers never redeemed
    months. The losers' dates aren't how far the read reached: 90 days counted every loser and only 10 days of wins
    (THEHIGHLIFE, 23 Oct: 30% shown, 55% read in full)."""
    cap = records.CLOSED_PAGES * 50
    rows = [position(1, closed_days_ago=10 * (i + 1) / cap) for i in range(cap)]
    rows += [position(-10, ended_days_ago=d) for d in (3, 20, 45, 80)]  # settled, never redeemed
    p = records.build(history(100, 1.0), positions(rows, complete=False), [], NOW)["periods"]
    assert p["30d"]["closed"] is None and p["90d"]["closed"] is None
    assert p["7d"]["closed"] == round(cap * 0.7) + 1 and p["7d"]["won"] == round(cap * 0.7)  # the 3-day loser counts


def test_a_cut_held_list_leaves_losers_out_so_no_period_has_a_win_rate() -> None:
    """The closed list ended (fewer than its cap) but the read isn't complete: the held list was cut, where losers
    never redeemed sit in no order of time (ic4cream, 23 Oct: 71% shown, 54% read in full)."""
    rows = [position(1, closed_days_ago=d) for d in range(1, 60)] + [position(-5, ended_days_ago=40)]
    p = records.build(history(100, 1.0), positions(rows, complete=False), [], NOW)["periods"]
    assert all(p[k]["closed"] is None and p[k]["won"] is None for k in ("7d", "30d", "90d"))


def test_without_their_positions_the_rest_of_the_record_stands() -> None:
    rec = records.build(history(40, 5.0), None, [], NOW)
    assert rec["periods"]["30d"]["trading_pnl"] == 150 and rec["periods"]["30d"]["closed"] is None
    assert rec["positions_complete"] is None


def test_the_usual_trade_adds_up_one_orders_fills_so_a_big_trader_doesnt_look_small() -> None:
    fills = [(NOW - 100 + i, True, "0xm1", 1000.0) for i in range(25)]  # one $25K order in 25 fills
    fills += [(NOW - 5000, True, "0xm2", 30000.0), (NOW - 9000, True, "0xm3", 20000.0)]
    rec = records.build(ProfitHistory([]), positions([]), fills, NOW)
    assert rec["typical_usd"] == 25000 and rec["buys_30d"] == 3 and rec["last_buy"] == NOW - 76


def test_the_usual_trade_is_where_their_money_goes_not_the_middle_of_their_scraps() -> None:
    """Most of their trades are $5 scraps, almost all their money is in a few big bets (0x361b…74fe, 19 Oct: $22
    usual against $1.3M profit): the usual trade is the big bets' size, never the scraps'."""
    fills = [(NOW - 1000 * i, True, f"0xs{i}", 5.0) for i in range(1, 41)]  # 40 scraps, $200
    fills += [(NOW - 3600 * i, True, f"0xb{i}", usd) for i, usd in enumerate((20000.0, 50000.0, 60000.0), 1)]
    rec = records.build(ProfitHistory([]), positions([]), fills, NOW)
    assert rec["typical_usd"] == 50000  # half the $130,200 is in trades of $50K or more
    assert records._usual([10.0, 10.0, 10.0]) == 10 and records._usual([]) is None


def test_a_record_read_takes_the_profit_history_and_the_completed_positions() -> None:
    asked: list[Any] = []

    class Sdk:
        def profit_history(self, w: str) -> ProfitHistory:
            asked.append(("pnl", w))
            return history(40, 1.0)

        def completed_positions(self, w: str, **k: Any) -> Any:
            asked.append(("positions", w, k))
            raise engine.VenueError("rate_limited", "Polymarket's firewall said no.", venue="polymarket")

    rec, kept = records.read(Sdk(), AMY, [], None, NOW)  # type: ignore[arg-type]
    assert asked == [("pnl", AMY), ("positions", AMY, {"max_pages": records.FIRST_PAGES, "held_pages": records.HELD_PAGES})]
    assert rec["periods"]["30d"]["trading_pnl"] == 30 and rec["periods"]["30d"]["closed"] is None
    assert kept is None  # nothing read: what's kept stays as it was


# ---- positions kept between reads ----


def kept_position(market: str, pnl: float, closed_days_ago: float) -> Any:
    return SimpleNamespace(market=market, pnl=pnl, redeemed=True, end_date=None,
                           closed_at=datetime.fromtimestamp(NOW - closed_days_ago * DAY, UTC))  # fmt: skip


def busy_read(start_days_ago: float, at: float = NOW, prefix: str = "m") -> list[Any]:
    """A cut read of a busy trader: the closed list's cap, the newest reaching back ``start_days_ago`` days from
    ``at``, two in three made money."""
    cap = records.CLOSED_PAGES * 50
    ago = (NOW - at) / DAY
    return [kept_position(f"{prefix}{i}", 1 if i % 3 else -1, ago + start_days_ago * (i + 1) / cap) for i in range(cap)]


def test_a_read_that_reaches_back_to_the_last_one_extends_what_is_kept() -> None:
    """Each read adds what closed since the last, so a busy trader's win rate reaches back further each time instead
    of one read's 200 (THEHIGHLIFE, 23 Oct: 200 closed reached back about 10 days)."""
    first = records.merge(None, busy_read(10, at=NOW - 8 * DAY, prefix="a"), False, records.CLOSED_PAGES, NOW - 8 * DAY)
    assert first is not None and first.since == pytest.approx(NOW - 18 * DAY)
    second = records.merge(first, busy_read(10, prefix="b"), False, records.CLOSED_PAGES, NOW)  # back past 8 days
    assert second is not None and second.since == pytest.approx(NOW - 18 * DAY) and second.read_at == NOW
    assert len(second.rows) == 2 * records.CLOSED_PAGES * 50
    p = records.build(history(100, 1.0), None, [], NOW, kept=second)["periods"]
    assert p["7d"]["closed"] is not None and p["30d"]["closed"] is None  # 18 days kept: 7 in full, 30 not yet


def test_a_read_that_doesnt_reach_back_to_the_last_one_starts_again_from_what_it_read() -> None:
    first = records.merge(None, busy_read(10, at=NOW - 20 * DAY, prefix="a"), False, records.CLOSED_PAGES, NOW - 20 * DAY)
    second = records.merge(first, busy_read(10, prefix="b"), False, records.CLOSED_PAGES, NOW)  # a 10-day gap
    assert second is not None and second.since == pytest.approx(NOW - 10 * DAY)
    assert all(m.startswith("b") for m in second.rows)  # what the gap may have missed isn't counted


def test_a_read_whose_held_list_may_be_cut_changes_nothing_kept_and_gives_no_win_rate() -> None:
    kept = records.PositionHistory(NOW - 50 * DAY, NOW - DAY, {"x": (NOW - 2 * DAY, True)})
    rows = [kept_position(f"m{i}", 1, i + 1) for i in range(30)]  # the closed list ended: the held list was cut
    assert records.merge(kept, rows, False, records.CLOSED_PAGES, NOW) is None


def test_a_complete_read_keeps_everything_back_to_the_keep_limit() -> None:
    rows = [kept_position("new", 5, 3), kept_position("old", -5, records.KEEP_DAYS + 10)]
    got = records.merge(None, rows, True, records.CLOSED_PAGES, NOW)
    assert got is not None and got.since == NOW - records.KEEP_DAYS * DAY and set(got.rows) == {"new"}
    p = records.build(history(100, 1.0), None, [], NOW, kept=got)["periods"]
    assert (p["90d"]["won"], p["90d"]["closed"]) == (1, 1)


def test_a_redeemed_position_read_again_is_the_new_reads() -> None:
    """A loser kept as never redeemed that they later redeemed is in the new read's closed list: counted once."""
    kept = records.PositionHistory(NOW - 30 * DAY, NOW - DAY, {"x": (NOW - 5 * DAY, False)})
    rows = [kept_position("x", 2, 0.5)] + [kept_position(f"m{i}", 1, 0.5 + 2 * i / 200) for i in range(199)]
    got = records.merge(kept, rows, False, records.CLOSED_PAGES, NOW)
    assert got is not None and got.rows["x"] == (pytest.approx(NOW - 0.5 * DAY), True) and len(got.rows) == 200


def test_the_next_read_takes_enough_pages_to_reach_back_to_the_last() -> None:
    assert records.pages_for(None, NOW) == records.FIRST_PAGES
    quiet = records.PositionHistory(NOW - 60 * DAY, NOW - 2 * DAY, {f"m{i}": (NOW - 3 * DAY - i * DAY, True) for i in range(5)})
    assert records.pages_for(quiet, NOW) == records.CLOSED_PAGES
    busy = records.PositionHistory(NOW - 9 * DAY, NOW - 2 * DAY,
                                   {f"m{i}": (NOW - 2 * DAY - i * 0.001 * DAY, True) for i in range(1400)})  # fmt: skip
    assert records.pages_for(busy, NOW) == 13  # 200 a day for the 2 days since, half again: 600, 12 pages and 1
    assert records.pages_for(busy, NOW + 30 * DAY) == records.MAX_PAGES


def test_the_directory_keeps_a_wallets_positions_with_its_record(d: Directory) -> None:
    kept = records.PositionHistory(NOW - 20 * DAY, NOW, {"m1": (NOW - DAY, True), "m2": (NOW - 3 * DAY, False)})
    d.keep_record(AMY, rec(100.0), at=NOW, positions=kept)
    assert d.kept_positions(AMY) == kept and d.kept_positions(BEN) is None
    d.keep_record(AMY, rec(100.0), at=NOW, positions=records.PositionHistory(NOW - DAY, NOW, {"m3": (NOW, True)}))
    assert set(d.kept_positions(AMY).rows) == {"m3"}  # type: ignore[union-attr]
    d.keep_record(AMY, rec(100.0), at=NOW)  # a read with nothing new to keep leaves them as they were
    assert set(d.kept_positions(AMY).rows) == {"m3"}  # type: ignore[union-attr]


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
    d.keep_record(CAL, rec(100, won=10, closed=12, vol30=2_000, weeks=(3, 3)), at=NOW)
    order = lambda sort: [r["wallet"] for r in d.leaderboard("30d", sort, new=True, now=NOW)["rows"]]  # noqa: E731
    assert order("profit") == [BEN, AMY, CAL]
    assert order("return") == [CAL, AMY, BEN]  # 5% beats 0.5%; BEN's $900 traded ranks last
    assert order("win") == [BEN, AMY, CAL]  # 60 of 80 beats 9 of 10 and 10 of 12 on the bottom of its range
    assert order("volume") == [AMY, CAL, BEN]
    assert order("weeks") == [AMY, BEN, CAL]  # 3 of 3 weeks is under 4 weeks of history: unranked


def test_new_accounts_are_hidden_unless_asked_for_and_the_list_says_how_many(d: Directory) -> None:
    d.add([Seen(w, "leaderboard", "PNL MONTH OVERALL") for w in (AMY, BEN)])
    d.keep_record(AMY, rec(500), at=NOW)
    d.keep_record(BEN, rec(954_000, weeks=(1, 1)), at=NOW)  # one big first week
    got = d.leaderboard(now=NOW)
    assert [r["wallet"] for r in got["rows"]] == [AMY] and got["total"] == 1 and got["new_hidden"] == 1
    shown = d.leaderboard(new=True, now=NOW)
    assert [(r["wallet"], r["new_account"]) for r in shown["rows"]] == [(BEN, True), (AMY, False)]
    assert shown["new_hidden"] == 0


def test_only_rows_with_every_column_are_listed_and_a_search_still_finds_the_rest(d: Directory) -> None:
    """The owner, 19 Oct: "if they don't have all values for all columns, remove them". A record copied from a score
    (no win rate yet), one whose positions couldn't be read, under 10 closed in the period, or no usual trade waits;
    the list says how many. A busy trader whose 30 days weren't read in full shows their 7 days, as the row does."""
    ws = (AMY, BEN, CAL, DAN, "0x" + "e5" * 20, "0x" + "f6" * 20)
    d.add([Seen(w, "leaderboard", "PNL MONTH OVERALL") for w in ws])
    d.keep_record(AMY, rec(500), at=NOW)
    d.keep_record(BEN, rec(900, won=None, closed=None), via="score", at=NOW)  # copied from a score: not read yet
    d.keep_record(CAL, rec(800, won=None, closed=None), at=NOW)  # positions couldn't be read
    d.keep_record(DAN, rec(700, won=8, closed=8), at=NOW)  # 8 closed: no win rate
    d.keep_record(ws[4], rec(600) | {"typical_usd": None}, at=NOW)  # no usual trade
    busy = rec(400)
    busy["periods"]["30d"] |= {"won": None, "closed": None}
    busy["periods"]["90d"] |= {"won": None, "closed": None}
    d.keep_record(ws[5], busy, at=NOW)  # 30 and 90 days not read in full: their 7 days' 6 of 10 stands in
    got = d.leaderboard(now=NOW)
    assert [r["wallet"] for r in got["rows"]] == [AMY, ws[5]] and got["total"] == 2 and got["incomplete"] == 4
    assert [r["wallet"] for r in d.leaderboard("7d", now=NOW)["rows"]] == [AMY, ws[5]]
    found = d.leaderboard(q=BEN[:10], now=NOW)
    assert [r["wallet"] for r in found["rows"]] == [BEN] and found["incomplete"] == 0  # a search finds anyone


def test_traders_the_leaderboard_waits_on_are_read_next_the_most_profitable_first(d: Directory) -> None:
    """Copied records have no win rate, so they aren't listed until read: right after the traders people are shown,
    ahead of wallets never looked at, the most profit over 30 days first; made due at launch, and only once."""
    d.add([Seen(w, "leaderboard", "PNL MONTH OVERALL") for w in (AMY, BEN, CAL)] + [Seen(DAN, "search")])
    for w, pnl in ((AMY, 100), (BEN, 900), (DAN, 5000)):  # DAN: never found anywhere public, so never listed
        d.keep_record(w, rec(pnl, won=None, closed=None), via="score", at=NOW - DAY)
    d.keep_record(CAL, rec(50), at=NOW)  # CAL's own record was read
    with d._db() as con:  # as their scores left them: next looked at in a day
        con.execute("UPDATE wallets SET status = 'scored', next_check = ? WHERE wallet != ?", (NOW + DAY, CAL))
    d.add([Seen("0x" + "e5" * 20, "leaderboard", "PNL MONTH OVERALL")], at=NOW)  # a wallet never looked at
    assert d.due(10, now=NOW + 1)[0]["wallet"] != BEN  # not due before launch makes them so
    assert d.board_due_now(NOW) == 2 and d.board_due_now(NOW) == 0  # BEN and AMY, once
    due = d.due(10, now=NOW + 1)
    assert [(x["wallet"], x["kind"]) for x in due[:2]] == [(BEN, "board"), (AMY, "board")]
    assert due[2]["kind"] == "new" and d.due(10, now=NOW + 1, new_first=True)[0]["wallet"] == BEN
    assert d.due_counts(now=NOW + 1)["board"] == 2
    d.keep_record(BEN, rec(900), at=NOW + 2)  # read: off the queue, due again with everyone else's next look
    assert [x["wallet"] for x in d.due(10, now=NOW + 3) if x["kind"] == "board"] == [AMY]


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


def trade(at: float, action: str = "buy", market: str = "0xm1", usd: float = 100.0, price: float = 0.5) -> Any:
    return SimpleNamespace(at=datetime.fromtimestamp(at, UTC), action=action, market=f"{market}:0", usd=usd, price=price)


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
        def profit_history(self, w: str) -> ProfitHistory:
            read.append(w)
            return history(40, 2.0, now=now)
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
