"""A trader's record as Polymarket reports it (/api/record), for a page without a fresh score: Polymarket's own
figures, open positions biggest first, the categories they hold and lately traded, read on the checks' budget and
kept for minutes, and a page that keeps the record apart from our skill test (no network: the reads are stand-ins)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uselayer import VenueError
from uselayer.whales import WhalePosition

from signals import app as engine

W = "0x" + "a" * 40
# a Polymarket trader's figures as uselayer 0.14 passes them on: volume_usd is dollars, volume_contracts contracts,
# trades the fills, markets_traded the markets (the profile's "Predictions"), pnl_as_of when Polymarket worked them out
STATS = {"trading_pnl": 5200.0, "realized_pnl": 6000.0, "unrealized_pnl": -800.0, "pnl": 5300.0, "income": 100.0,
         "volume_usd": 190000.0, "volume_contracts": 410000.0, "trades": 1234, "markets_traded": 84,
         "biggest_win": 2500.0, "fees_paid": 12.0, "pnl_as_of": "2026-10-18T19:47:41+00:00"}  # fmt: skip


def pos(market: str, value: float | None, title: str = "A market") -> WhalePosition:
    return WhalePosition(market, title, "Yes", 100.0, 0.4, 0.5, value, None)


class FakeChecker:
    """The checks' client: counts its reads of a trader's page."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def trader(self, venue: str, wallet: str, *, trades: int, closed: int) -> Any:
        self.calls.append((wallet, trades, closed))
        held = [pos("0xs:0", 50.0, "Small"), pos("0xb:1", 9000.0, "Big"), pos("0xn:0", None, "Unpriced")]
        held += [pos(f"0x{i}:0", 10.0) for i in range(7)]
        return SimpleNamespace(trader=SimpleNamespace(name="Rec"), joined="2024-03-01T00:00:00Z", stats=STATS,
                               positions=held, trades=[SimpleNamespace(market="0xb:0"), SimpleNamespace(market="0xt:1")])  # fmt: skip


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> tuple[TestClient, FakeChecker]:
    from signals.directory import Directory

    engine._cache.clear()
    fake = FakeChecker()
    monkeypatch.setattr(engine, "checker", lambda: fake)
    kept = Directory(tmp_path / "directory.db")  # never the developer's own store
    monkeypatch.setattr(engine, "directory", lambda: kept)
    cats = {"0xb:1": "Sports", "0xb:0": "Sports", "0xt:1": "Politics", "0xs:0": "Sports"}
    monkeypatch.setattr(engine, "_categories", lambda ms: {m: cats[m] for m in ms if m in cats})
    return TestClient(engine.app), fake


def test_the_record_is_polymarkets_figures_with_open_positions_biggest_first(api: tuple[TestClient, FakeChecker]) -> None:
    client, fake = api
    r = client.get(f"/api/record/{W.upper().replace('0X', '0x')}").json()
    assert fake.calls == [(W, engine.RECORD_TRADES, 0)]  # their trades for categories; no closed positions read
    # 0.14's figures pass through: dollars stay dollars (never taken for contracts), and trades are the fills
    kept = ("trading_pnl", "realized_pnl", "unrealized_pnl", "pnl", "income", "volume_usd", "biggest_win",
            "volume_contracts", "trades", "markets_traded", "pnl_as_of")  # fmt: skip
    assert r["stats"] == {k: STATS[k] for k in kept}
    assert r["open"] == {"count": 10, "at_least": False, "value": 9120.0, "pnl": None}  # an unpriced one isn't counted as $0; no figure on a position: no open profit
    assert [p["title"] for p in r["positions"][:2]] == ["Big", "Small"] and len(r["positions"]) == engine.RECORD_POSITIONS
    assert r["positions"][0]["category"] == "Sports"
    # markets (not outcomes) per category: 0xb held and traded counts once; 0xs held; 0xt traded
    assert r["categories"] == [{"category": "Sports", "markets": 2}, {"category": "Politics", "markets": 1}]


def test_the_record_is_kept_for_minutes_and_bad_input_or_a_failed_read_says_so(
    api: tuple[TestClient, FakeChecker], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake = api
    client.get(f"/api/record/{W}")
    client.get(f"/api/record/{W}")
    assert len(fake.calls) == 1  # one read of their page per RECORD_TTL_S
    assert client.get("/api/record/someone").status_code == 400

    def down(*a: Any, **k: Any) -> Any:
        raise VenueError("unavailable", "Polymarket is down", venue="polymarket", retryable=True)

    monkeypatch.setattr(fake, "trader", down)
    assert client.get("/api/record/0x" + "b" * 40).status_code >= 400

    def no_categories(ms: Any) -> Any:
        raise VenueError("unavailable", "gamma is down", venue="polymarket", retryable=True)

    monkeypatch.setattr(fake, "trader", FakeChecker().trader)
    monkeypatch.setattr(engine, "_categories", no_categories)
    r = client.get("/api/record/0x" + "c" * 40).json()
    assert r["categories"] == [] and r["open"]["count"] == 10  # the record still shows, without categories


def test_figures_missing_from_the_stats_are_none_never_dropped_or_taken_for_contracts(
    api: tuple[TestClient, FakeChecker], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The key-set trap: the record picks its keys from the SDK's stats. A trader Polymarket has no figures for (no
    all-time profit) has 0.14's keys missing or None: each stays, as None, and no dollars are relabelled contracts."""
    client, fake = api
    bare = {"trading_pnl": None, "volume_usd": 900.0, "biggest_win": None}  # no volume_contracts, trades… at all
    monkeypatch.setattr(fake, "trader", lambda *a, **k: SimpleNamespace(trader=SimpleNamespace(name="Rec"), joined=None, stats=bare,
                                                                       positions=[], trades=[]))  # fmt: skip
    st = client.get(f"/api/record/{W}").json()["stats"]
    assert st["volume_usd"] == 900.0 and st["volume_contracts"] is None  # dollars stay dollars
    assert (st["trades"], st["markets_traded"], st["pnl_as_of"]) == (None, None, None)
    # uselayer 0.12's shape (no 0.14 key at all): its volume_usd was contracts, and its trades wasn't a trade count
    old = engine.poly_stats({"volume_usd": 410000.0, "trades": 14, "trading_pnl": 1.0})
    assert old == {"volume_contracts": 410000.0, "trading_pnl": 1.0}
    assert engine.poly_stats(STATS) == STATS


# ---- a trader's whole record of positions, and realized profit by category (uselayer 0.14) ----


class Record(SimpleNamespace):
    pass


def test_made_money_on_comes_from_every_position_they_have_had_and_is_kept(
    api: tuple[TestClient, FakeChecker], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake = api
    asked: list[str] = []

    def completed_positions(wallet: str) -> Any:
        from datetime import UTC, datetime

        asked.append(wallet)
        return Record(summary="Made money on 215 of 400 positions · parlays not included", made_money=215,
                      positions=[object()] * 400, complete=True, reconciles=True, parlays_excluded=True,
                      read_at=datetime(2026, 10, 19, tzinfo=UTC))  # fmt: skip

    monkeypatch.setattr(fake, "completed_positions", completed_positions, raising=False)
    r = client.get(f"/api/completed/{W.upper().replace('0X', '0x')}").json()
    assert r == {"summary": "Made money on 215 of 400 positions · parlays not included", "made_money": 215,
                 "count": 400, "complete": True, "reconciles": True, "parlays_excluded": True,
                 "read_at": "2026-10-19T00:00:00+00:00"}  # fmt: skip
    client.get(f"/api/completed/{W}")
    assert asked == [W]  # kept COMPLETED_TTL_S: 3-13 reads each
    assert client.get("/api/completed/someone").status_code == 400

    def down(wallet: str) -> Any:
        raise VenueError("unavailable", "Polymarket is down", venue="polymarket", retryable=True)

    monkeypatch.setattr(fake, "completed_positions", down, raising=False)
    assert client.get("/api/completed/0x" + "b" * 40).status_code >= 400


def test_realized_profit_by_category_names_them_plainly_with_all_except_sports() -> None:
    v = engine.category_view({"categories": {"SPORTS": 5000.0, "POLITICS": 1200.5, "GEOPOLITICS": 10.0, "CRYPTO": -300.0},
                              "overall": 5950.5, "uncategorised": 40.0, "read_at": "2026-10-19T00:00:00+00:00"})  # fmt: skip
    # a category Polymarket adds that we don't know yet is uncategorised, with markets in none
    assert v["rows"] == [{"category": "Sports", "usd": 5000.0}, {"category": "Politics", "usd": 1200.5},
                         {"category": "Uncategorised", "usd": 50.0}, {"category": "Crypto", "usd": -300.0}]  # fmt: skip
    assert (v["overall"], v["except_sports"]) == (5950.5, 950.5)
    none = engine.category_view({"categories": {"ESPORTS": 80.0}, "overall": 80.0, "uncategorised": 0.0, "read_at": None})
    assert none["rows"] == [{"category": "Esports", "usd": 80.0}] and none["except_sports"] == 80.0  # $0 left out
    unread = engine.category_view({"categories": {}, "overall": None, "uncategorised": None, "read_at": None})
    assert (unread["rows"], unread["except_sports"]) == ([], None)


def test_realized_profit_by_category_is_read_on_the_checks_budget_and_kept(
    api: tuple[TestClient, FakeChecker], monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from uselayer.whales import RealizedByCategory

    client, fake = api
    asked: list[tuple[str, str]] = []

    def realized_by_category(venue: str, wallet: str) -> RealizedByCategory:
        asked.append((venue, wallet))
        return RealizedByCategory(wallet=wallet, categories={"SPORTS": 900.0, "POLITICS": 100.0}, overall=1000.0,
                                  uncategorised=0.0, realized_pnl=1000.0, realized_market_pnl=1000.0,
                                  realized_combo_pnl=0.0, read_at=datetime(2026, 10, 19, tzinfo=UTC))  # fmt: skip

    monkeypatch.setattr(fake, "realized_by_category", realized_by_category, raising=False)
    r = client.get(f"/api/categories/{W}").json()
    assert r["rows"] == [{"category": "Sports", "usd": 900.0}, {"category": "Politics", "usd": 100.0}]
    assert (r["overall"], r["except_sports"]) == (1000.0, 100.0)
    client.get(f"/api/categories/{W}")
    assert asked == [("polymarket", W)]  # 12 reads, kept CATEGORY_TTL_S
    assert client.get("/api/categories/0x12").status_code == 400


# ---- the page ----

FACTS = ("usd", "pl", "esc", "cents", "tenths", "centsPair", "plural", "ago", "recordFacts", "recordPositions", "RECORD_NOTE")


def test_the_page_says_its_a_record_not_a_skill_test_and_unknown_stays_a_dash(run_js: Any) -> None:
    rec = ('{stats: {trading_pnl: 5200, realized_pnl: 6000, unrealized_pnl: -800, volume_usd: 190000, volume_contracts: 410000,'
           ' trades: 1234, markets_traded: 84, pnl_as_of: "2026-10-18T19:47:41Z", biggest_win: null}, open: {count: 50, at_least: true, value: 9120, pnl: -812.5}, joined: "2024-03-01T00:00:00Z",'
           ' categories: [{category: "Sports", markets: 2}], positions: [{title: "Big <b>", outcome: "Yes", value: 9000,'
           ' avg_price: 0.4, current_price: 0.5, category: "Sports"}]}')  # fmt: skip
    got = run_js(FACTS, f"[recordFacts({rec}), recordPositions({rec}), RECORD_NOTE, recordFacts({{}})]")
    facts = dict(got[0])
    assert facts["Profit from trading"].startswith('<span class="gain">+$5.2K</span> all time')
    # still open: their positions' own figures added up (−$812.50), never the summary's −$800, which can be months old;
    # a full read (50+) says it's their biggest ones'
    assert "+$6K closed, −$813 still open on their 50 biggest positions" in facts["Profit from trading"]
    # dollars bought and sold, with the contracts beside them; trades are fills, in so many markets
    assert facts["Bought and sold"].startswith("$190K, all time") and "410K contracts" in facts["Bought and sold"]
    assert facts["Trades"] == "1,234 trades in 84 markets, all time" and facts["Biggest win"] == "—"
    assert "Polymarket works them out every few hours" in facts["Figures as of"]
    assert facts["Open now"].startswith("50+ positions over 1 contract, worth $9.1K")
    assert "positions under 1 contract aren't listed or counted" in facts["Open now"] and "−$800" not in facts["Open now"]
    assert facts["Joined"].startswith("Mar 2024")  # in UTC
    # none listed: what's open isn't known (positions under 1 contract aren't listed), never "nothing" or the summary's
    small = dict(run_js(FACTS, "recordFacts({stats: {trading_pnl: 431, realized_pnl: 424, unrealized_pnl: 7.71}, open: {count: 0, pnl: null}})"))
    assert small["Open now"] == "No positions over 1 contract" and "still open" not in small["Profit from trading"]
    tiny = run_js(FACTS, "recordFacts({stats: {trading_pnl: 1162, realized_pnl: 1162}, open: {count: 2, pnl: -0.0035}})")
    assert "+$1.2K closed, nothing still open" in dict(tiny)["Profit from trading"]  # never "−$0.00 still open"
    assert got[1][0][0].startswith("Big &lt;b&gt;") and "40¢ → 50¢ · Sports" in got[1][0][1]  # titles escaped
    assert "not a test of skill" in got[2] and "buying after them" in got[2]
    assert dict(got[3]) == {"Profit from trading": "—", "Bought and sold": "—", "Trades": "—", "Biggest win": "—",
                            "Open now": "No positions over 1 contract", "Markets": "—"}  # fmt: skip


def test_the_records_open_profit_is_added_up_from_their_positions_never_the_summary(
    api: tuple[TestClient, FakeChecker], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Polymarket's summary of open profit can be months old: the record adds up each position's own figure, as
    the scored profile does. One without a figure, or none listed, leaves it unknown, never $0."""
    client, fake = api
    held = [WhalePosition("0xa:0", "A", "Yes", 100.0, 0.4, 0.5, 50.0, 12.5), WhalePosition("0xb:1", "B", "No", 10.0, 0.6, 0.3, 3.0, -3.0)]
    monkeypatch.setattr(fake, "trader", lambda *a, **k: SimpleNamespace(trader=SimpleNamespace(name="Rec"), joined=None, stats=STATS,
                                                                       positions=held, trades=[]))  # fmt: skip
    assert client.get(f"/api/record/{W}").json()["open"]["pnl"] == 9.5
    engine._cache.clear()
    monkeypatch.setattr(fake, "trader", lambda *a, **k: SimpleNamespace(trader=SimpleNamespace(name="Rec"), joined=None, stats=STATS,
                                                                       positions=[], trades=[]))  # fmt: skip
    assert client.get(f"/api/record/{W}").json()["open"]["pnl"] is None


PROFILE = ("usd", "pl", "esc", "plural", "weekBars", "numberRow", "BUSY_TEXT", "readFailed", "madeMoneyRow", "worstDrop", "CATEGORY_NOTE", "categoryCard")


def test_made_money_on_is_given_only_when_the_record_adds_up_and_says_positions(run_js: Any) -> None:
    rows = run_js(PROFILE, """[madeMoneyRow(null), madeMoneyRow({error: true}),
      madeMoneyRow({reconciles: true, count: 400, made_money: 215, parlays_excluded: true, summary: "x"}),
      madeMoneyRow({reconciles: true, count: 82, made_money: 43, parlays_excluded: false}),
      madeMoneyRow({reconciles: false, count: 401, made_money: 215, summary: "Their positions don't add up to Polymarket's total right now; it updates every few hours, so their record can't be given."}),
      madeMoneyRow({reconciles: true, count: 0, made_money: 0, parlays_excluded: true, summary: "They trade only parlays, which Polymarket doesn't list: no positions to count."})]""")
    assert rows[0]["v"] == "…" and rows[1]["v"] is None and "couldn't be read" in rows[1]["sub"]
    assert rows[2]["v"] == "215 of 400 positions" and rows[2]["sub"].endswith("· parlays not included")
    assert rows[3]["v"] == "43 of 82 positions" and "parlays" not in rows[3]["sub"]
    assert rows[4]["v"] is None and rows[4]["sub"].startswith("Their positions don't add up")  # the SDK's own line
    assert rows[5]["v"] is None and "only parlays" in rows[5]["sub"]  # nothing to count: never "0 of 0"


def test_the_worst_drop_is_the_scores_and_a_score_from_before_it_shows_a_dash(run_js: Any) -> None:
    got = run_js(PROFILE, """[worstDrop({worst_drop: {"90d": {usd: 690520.84, peak_at: "a", trough_at: "b"}}}, "90d"),
      worstDrop({worst_drop: {"7d": {usd: 0, peak_at: null, trough_at: null}}}, "7d"), worstDrop({}, "90d"),
      worstDrop({worst_drop: {}}, "30d")]""")
    assert got[0] == '<span class="loss">−$691K</span>' and got[1] == "$0.00" and got[2] is None and got[3] is None


def test_the_category_card_has_all_except_sports_and_says_what_it_counts(run_js: Any) -> None:
    html = run_js(PROFILE, """categoryCard({rows: [{category: "Sports", usd: 5000}, {category: "Uncategorised", usd: 50},
      {category: "Crypto", usd: -300}], overall: 4750, except_sports: -250})""")
    assert "Realized profit by category, all time" in html
    for row in ("Sports", "Uncategorised", "Crypto", "All except Sports", "All categories"):
        assert f"<dt>{row}" in html, row
    assert '<span class="loss">−$250</span>' in html and '<span class="gain">+$4.8K</span>' in html
    note = "Parlays included. Polymarket's figures, updated every few hours. Trades still open aren't counted."
    assert note in html.replace("&#39;", "'")  # the owner's words, as they are
    loading, failed, empty = run_js(PROFILE, "[categoryCard(null), categoryCard({error: true}), categoryCard({rows: [], overall: null})]")
    assert "skel" in loading and "couldn't be read just now" in failed and "No realized profit or loss" in empty


def test_the_page_says_positions_never_predictions() -> None:
    """A trader's record counts positions (each outcome of a market): the page never calls them "predictions",
    Polymarket's word for markets traded (its comments may say so)."""
    page = (engine.HERE / "static" / "index.html").read_text().splitlines()
    assert not [ln for ln in page if "prediction" in ln.lower() and not ln.lstrip().startswith("//")]


def test_a_profiles_own_reads_are_under_check_nows_limits_and_busy_says_so(
    api: tuple[TestClient, FakeChecker], monkeypatch: pytest.MonkeyPatch
) -> None:
    """/api/completed and /api/categories cost up to ~25 reads for a wallet not read lately, so they take "Check now"'s
    turns (CHECKS_AT_ONCE, waiting CHECK_WAIT_S) and, hosted, CHECKS_PER_CLIENT wallets per visitor (each wallet once,
    however many of its reads): past one, a 429 that says "Busy, try again in a minute." A kept answer needs no turn."""
    import threading
    from datetime import UTC, datetime

    client, fake = api
    reads: list[str] = []

    def completed_positions(wallet: str) -> Any:
        reads.append(wallet)
        return Record(summary="Made money on 1 of 2 positions", made_money=1, positions=[1, 2], complete=True,
                      reconciles=True, parlays_excluded=False, read_at=datetime(2026, 10, 19, tzinfo=UTC))  # fmt: skip

    def realized_by_category(venue: str, wallet: str) -> Any:
        from uselayer.whales import RealizedByCategory

        return RealizedByCategory(wallet=wallet, categories={}, overall=None, uncategorised=None, realized_pnl=None,
                                  realized_market_pnl=None, realized_combo_pnl=None, read_at=datetime(2026, 10, 19, tzinfo=UTC))  # fmt: skip

    monkeypatch.setattr(fake, "completed_positions", completed_positions, raising=False)
    monkeypatch.setattr(fake, "realized_by_category", realized_by_category, raising=False)
    a, b, c = ("0x" + x * 40 for x in "abc")
    assert client.get(f"/api/completed/{a}").status_code == 200
    # every turn taken: busy, plainly, never a failed read; a kept answer still comes
    monkeypatch.setattr(engine, "_checks", threading.BoundedSemaphore(1))
    engine._checks.acquire()
    monkeypatch.setattr(engine, "CHECK_WAIT_S", 0)
    busy = client.get(f"/api/completed/{b}")
    assert busy.status_code == 429 and busy.json()["detail"] == "Busy, try again in a minute."
    assert client.get(f"/api/completed/{a}").status_code == 200 and reads == [a]
    engine._checks.release()
    # hosted: wallets per visitor, each counted once whichever of its reads asks
    monkeypatch.setattr(engine, "HOSTED", True)
    monkeypatch.setattr(engine, "CHECKS_PER_CLIENT", (2, 600))
    monkeypatch.setattr(engine, "_profile_reads", {})
    engine._cache.clear()
    assert client.get(f"/api/completed/{a}").status_code == 200
    assert client.get(f"/api/categories/{a}").status_code == 200  # the same wallet: not counted again
    assert client.get(f"/api/completed/{b}").status_code == 200
    third = client.get(f"/api/completed/{c}")
    assert third.status_code == 429 and third.json()["detail"] == "Busy, try again in a minute."


def test_busy_shows_as_busy_on_the_page_never_an_error_or_zero(run_js: Any) -> None:
    row, card = run_js(PROFILE, "[madeMoneyRow(readFailed({status: 429})), categoryCard(readFailed({status: 429}))]")
    assert row["v"] is None and row["sub"] == "Busy, try again in a minute."
    assert "Busy, try again in a minute." in card and "$0" not in card
    failed = run_js(PROFILE, "madeMoneyRow(readFailed({status: 502}))")
    assert failed["sub"] == "their positions couldn't be read just now"
