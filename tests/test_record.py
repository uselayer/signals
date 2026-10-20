"""A trader's record as Polymarket reports it (/api/record), for a page without a fresh score: Polymarket's own
figures, open positions biggest first, the categories they hold and lately traded, read on the checks' budget and
kept for minutes, and a page that keeps the record apart from our skill test (no network: the reads are stand-ins)."""

from __future__ import annotations

from pathlib import Path
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


PROFILE = ("usd", "pl", "esc", "plural", "weekBars", "numberRow", "numberRows", "BUSY_TEXT", "readFailed", "worstDrop", "CATEGORY_NOTE",
           "UNCATEGORISED", "catLabel", "categoryCard")


def test_the_worst_drop_is_the_scores_and_a_score_from_before_it_shows_a_dash(run_js: Any) -> None:
    got = run_js(PROFILE, """[worstDrop({worst_drop: {"90d": {usd: 690520.84, peak_at: "a", trough_at: "b"}}}, "90d"),
      worstDrop({worst_drop: {"7d": {usd: 0, peak_at: null, trough_at: null}}}, "7d"), worstDrop({}, "90d"),
      worstDrop({worst_drop: {}}, "30d")]""")
    assert got[0] == '<span class="loss">−$691K</span>' and got[1] == "$0.00" and got[2] is None and got[3] is None


def test_the_category_card_has_all_except_sports_and_says_what_it_counts(run_js: Any) -> None:
    html = run_js(PROFILE, """categoryCard({rows: [{category: "Sports", usd: 5000}, {category: "Uncategorised", usd: 50},
      {category: "Crypto", usd: -300}], overall: 4750, except_sports: -250})""")
    assert "Realized profit by category, all time" in html
    for row in ("Sports", "Other markets", "Crypto", "All except Sports", "All categories"):
        assert f"<dt>{row}" in html, row
    assert '<span class="loss">−$250</span>' in html and '<span class="gain">+$4.8K</span>' in html
    note = "Parlays included. Polymarket's figures, updated every few hours. Trades still open aren't counted."
    assert note in html.replace("&#39;", "'")  # the owner's words, as they are
    loading, failed, empty = run_js(PROFILE, "[categoryCard(null), categoryCard({error: true}), categoryCard({rows: [], overall: null})]")
    assert "skel" in loading and "couldn't be read just now" in failed and "No realized profit or loss" in empty


def test_the_category_card_never_repeats_a_row_or_shows_a_0_for_categories_never_traded(run_js: Any) -> None:
    """OhWhenTheReds, 19 Oct: all $673,545 in Sports. One category is that row alone: no "All except Sports" $0.00 and
    no "All categories" repeating it. Sports and one other: "All except Sports" would be that other row again."""
    only, two, none = run_js(PROFILE, """[categoryCard({rows: [{category: "Sports", usd: 673545.48}], overall: 673545.48, except_sports: 0}),
      categoryCard({rows: [{category: "Sports", usd: 500}, {category: "Politics", usd: 200}], overall: 700, except_sports: 200}),
      categoryCard({rows: [{category: "Politics", usd: 900}, {category: "Crypto", usd: 100}], overall: 1000, except_sports: 1000})]""")
    assert "<dt>Sports" in only and "All except Sports" not in only and "All categories" not in only and "$0" not in only
    assert "All except Sports" not in two and "<dt>All categories" in two
    assert "All except Sports" not in none and "<dt>All categories" in none  # never traded Sports: it would repeat All
    cent = run_js(PROFILE, """categoryCard({rows: [{category: "Politics", usd: 496188.58}, {category: "Crypto", usd: 8747.88},
      {category: "Uncategorised", usd: 0.01}], overall: 504936.47, except_sports: 504936.47})""")
    assert "Other markets" not in cent and "<dt>All categories" in cent  # flawfence's +$0.01: rounding, no row


def test_other_markets_is_uncategorised_in_plain_words_and_noise_against_their_total_has_no_row(run_js: Any) -> None:
    """The owner, 19 Oct, on +$1.17 beside $9.1M: "what is uncategorized?" It's markets Polymarket puts in no category,
    read as "Other markets"; under 0.1% of their total it's noise, so no row. The kept data keeps the engine's name."""
    noise, real = run_js(PROFILE, """[categoryCard({rows: [{category: "Sports", usd: 9.1e6}, {category: "Politics", usd: 4600},
      {category: "Culture", usd: -39700}, {category: "Uncategorised", usd: 1.17}], overall: 9.1e6, except_sports: -35100}),
      categoryCard({rows: [{category: "Politics", usd: 900}, {category: "Uncategorised", usd: 40}], overall: 940, except_sports: 940})]""")
    assert "Other markets" not in noise and "Uncategorised" not in noise and "<dt>Culture" in noise
    assert "<dt>Other markets" in real and "Uncategorised" not in real


def test_a_figure_that_cant_be_given_has_no_row(run_js: Any) -> None:
    """A row with no value isn't drawn (the owner's call: left out, never "—"); one still loading ("…") is."""
    html = run_js(PROFILE, """numberRows([{k: "Open P&L", v: null, sub: "they hold over 500 positions"}, {k: "Wallet", v: "$1M"},
      {k: "Open P&L ", v: "…"}, {k: "Worst drop from a high", v: null}])""")
    assert "<dt>Wallet" in html and "<dt>Open P&amp;L " in html and "Open P&L" not in html and "Worst drop" not in html
    assert "—" not in html


def test_the_page_says_positions_never_predictions() -> None:
    """A trader's record counts positions (each outcome of a market): the page never calls them "predictions",
    Polymarket's word for markets traded (its comments may say so). The streak's "Past results, not a prediction"
    (the owner's words, 19 Oct) says what a run of weeks isn't, so it's the one use allowed."""
    page = (engine.HERE / "static" / "index.html").read_text().splitlines()
    said = [ln.lower().replace("past results, not a prediction", "") for ln in page if not ln.lstrip().startswith("//")]
    assert not [ln for ln in said if "prediction" in ln]


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
    card = run_js(PROFILE, "categoryCard(readFailed({status: 429}))")
    assert "Busy, try again in a minute." in card and "$0" not in card


POSITIONS = ("usd", "pl", "esc", "cents", "tenths", "centsPair", "ago", "marketLink", "usLink", "usInline", "STATUS", "statusLine", "OPEN",
             "neutralStatus", "tradeStatus", "openPositionRow", "closedPositionRow", "TAB_NOTES")  # fmt: skip


def test_a_position_says_what_they_put_in_and_what_its_worth_or_what_they_got_back(run_js: Any) -> None:
    """The owner, 19 Oct: "how much did they put in?" An open position says what they put in and what it's worth now,
    in dollars, with the price they paid and the price now staying the neutral status (no colour). A closed one says
    what they put in, at what price, what they got back, and how it ended with Polymarket's profit after fees."""
    open_, won, sold, checked = run_js(POSITIONS, """[openPositionRow({title: "Will Manchester City win?", outcome: "No", size: 454676,
        price: 0.71, now: 0.84, value: 381928, status: "moved", url: "https://polymarket.com/event/x", us: {found: false}}),
      closedPositionRow({title: "Commanders vs. 49ers", outcome: "49ers", size: 311333, avg_price: 0.81, exit_price: 1, pnl: 56800,
        result: "won", settled: true, closed_at: null, url: null}),
      closedPositionRow({title: "Sold early", outcome: "Yes", size: 1000, avg_price: 0.4, exit_price: 0.3, pnl: -100.5,
        result: "sold", settled: false, closed_at: null, url: null}),
      closedPositionRow({title: "Checked", outcome: "Yes", price: 0.43, usd: 5900, payout: 1})]""")
    assert "Put in $252K at 81¢ · got back $311K" in won and "Won</span>" in won and '<span class="gain">+$56.8K</span>' in won
    assert "Put in $400 at 40¢ · sold at 30¢ · got back $300" in sold and "Closed</span>" in sold and '<span class="loss">−$101</span>' in sold
    assert "Put in $5.9K at 43¢" in checked and "got back" not in checked
    assert "Put in $323K</span> · worth $382K now" in open_ and 'title="454,676 contracts at 71¢"' in open_
    assert "Now 84¢ · they paid 71¢" in open_ and "gain" not in open_ and "loss" not in open_  # an open position stays neutral
    assert "now 84¢" not in open_  # the price now is the status's, once
    nothing = run_js(POSITIONS, """openPositionRow({title: "T", outcome: null, size: null, price: null, now: null, value: null, status: "in"})""")
    assert "Put in" not in nothing and "worth" not in nothing and "undefined" not in nothing and "NaN" not in nothing
    notes = run_js(POSITIONS, "TAB_NOTES")
    assert "added up" in notes["positions"] and "Several trades can make up one position" in notes["activity"]


def test_the_profile_tabs_are_positions_and_recent_trades() -> None:
    page = (Path(engine.__file__).parent / "static" / "index.html").read_text()
    assert '[["positions", "Positions"], ["activity", "Recent trades"]]' in page and '"Activity"]' not in page
    assert "See recent trades" in page and "See activity" not in page and " · profit after fees" in page
    assert "REALIZED_CATS.map((c) => [c, catLabel(c)])" in page  # the picker reads "Other markets" too
