"""Realized profit by category for the recommended traders, read once a day on the background's budget and kept in
directory.db, so Traders can pick a category, sort by it and keep those who made money in it with no read on a page
load (no network: the reads are stand-ins)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uselayer import VenueError
from uselayer.whales import RealizedByCategory

from signals import app as engine
from signals.directory import Directory

SHARP, RISER, OTHER, BROKEN = ("0x" + c * 40 for c in "abcd")
NOW = 1_800_000_000.0


def board(wallet: str, segment: str) -> dict[str, Any]:
    return {"wallet": wallet, "segment": segment, "name": wallet[:6]}


def realized(wallet: str) -> RealizedByCategory:
    sports = {SHARP: 5000.0, RISER: -200.0}.get(wallet, 10.0)
    return RealizedByCategory(wallet=wallet, categories={"SPORTS": sports, "POLITICS": 300.0}, overall=sports + 300.0,
                              uncategorised=0.0, realized_pnl=sports + 300.0, realized_market_pnl=sports + 300.0,
                              realized_combo_pnl=0.0, read_at=datetime(2026, 10, 19, tzinfo=UTC))  # fmt: skip


@pytest.fixture
def kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> tuple[Directory, list[str]]:
    """A directory of its own, the check's list (two recommended traders, one broken, one not recommended) and a
    background whose reads are counted."""
    engine._cache.clear()
    d = Directory(tmp_path / "directory.db")
    monkeypatch.setattr(engine, "directory", lambda: d)
    scores = [board(SHARP, "proven"), board(RISER, "rising"), board(BROKEN, "quiet"), board(OTHER, "no_edge")]
    monkeypatch.setattr(engine, "_check_result", lambda: {"scores": scores})
    asked: list[str] = []

    class Background:
        def realized_by_category(self, venue: str, wallet: str) -> RealizedByCategory:
            asked.append(wallet)
            if wallet == BROKEN:
                raise VenueError("unavailable", "Polymarket is down", venue="polymarket", retryable=True)
            return realized(wallet)

    monkeypatch.setattr(engine, "background", lambda: Background())
    return d, asked


def test_the_recommended_traders_are_read_once_a_day_on_the_background_budget(kept: tuple[Directory, list[str]]) -> None:
    d, asked = kept
    got = engine.categories_round(now=NOW)
    # only the recommended (never the others), one at a time; a failed read is left for the next round
    assert sorted(asked) == sorted([SHARP, RISER, BROKEN]) and OTHER not in asked
    assert got == {"recommended": 3, "due": 3, "read": 2, "failed": 1}
    stored = d.realized_of([SHARP, RISER, OTHER])
    assert set(stored) == {SHARP, RISER}
    assert stored[SHARP]["rows"][0] == {"category": "Sports", "usd": 5000.0} and stored[SHARP]["overall"] == 5300.0
    asked.clear()
    stored_at = stored[SHARP]["stored_at"]
    engine.categories_round(now=stored_at + 3600)  # an hour later: only the one that failed is due
    assert asked == [BROKEN]
    asked.clear()
    engine.categories_round(now=stored_at + engine.CATEGORY_DAILY_S)  # a day later: everyone again
    assert sorted(asked) == sorted([SHARP, RISER, BROKEN])


def test_a_round_stops_when_asked(kept: tuple[Directory, list[str]]) -> None:
    _, asked = kept
    stop = threading.Event()
    stop.set()
    assert engine.categories_round(stop, now=NOW)["read"] == 0 and asked == []


def test_a_newer_read_replaces_the_kept_one_never_an_older(tmp_path: Any) -> None:
    d = Directory(tmp_path / "directory.db")
    d.keep_realized(SHARP, {"rows": [{"category": "Sports", "usd": 1.0}], "overall": 1.0}, at=NOW)
    d.keep_realized(SHARP.upper().replace("0X", "0x"), {"rows": [], "overall": 2.0}, at=NOW - 10)  # older: ignored
    assert d.realized_of([SHARP])[SHARP]["overall"] == 1.0
    d.keep_realized(SHARP, {"rows": [], "overall": 3.0}, at=NOW + 10)
    assert d.realized_of([SHARP])[SHARP] == {"rows": [], "overall": 3.0, "stored_at": NOW + 10}


def test_traders_rows_carry_what_was_kept_with_no_read_and_a_profile_uses_it(
    kept: tuple[Directory, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    d, asked = kept
    engine.categories_round(now=NOW)
    asked.clear()
    monkeypatch.setattr(engine, "_worth_load", lambda *a, **k: {"scores": [board(SHARP, "proven"), board(OTHER, "no_edge")]})
    client = TestClient(engine.app)
    rows = {s["wallet"]: s for s in client.get("/api/worth").json()["result"]["scores"]}
    assert rows[SHARP]["realized"]["usd"] == {"Sports": 5000.0, "Politics": 300.0, "All categories": 5300.0}
    assert "realized" not in rows[OTHER]  # not recommended: never read, so nothing, never $0
    # a profile of a recommended trader: the kept one while it's fresh, no read on the checks' budget either
    monkeypatch.setattr(engine, "checker", lambda: (_ for _ in ()).throw(AssertionError("read")))
    monkeypatch.setattr(engine.time, "time", lambda: NOW + 3600)
    assert client.get(f"/api/categories/{SHARP}").json()["overall"] == 5300.0
    assert asked == []


# ---- the page ----

PICKER = ("usd", "pl", "esc", "plural", "byDesc", "lb", "WIN_LABEL", "winRateOf", "REALIZED_CATS", "realizedIn", "realizedText",
          "LB_SORTS", "categoryNote")  # fmt: skip


def test_the_category_picker_sorts_by_realized_profit_in_it_and_says_what_it_counts(run_js: Any) -> None:
    rows = ('[{wallet: "a", realized: {usd: {Sports: 5000, Politics: 300}}}, {wallet: "b"},'
            ' {wallet: "c", realized: {usd: {Sports: -200, Politics: 900}}}, {wallet: "d", realized: {usd: {Politics: 50}}}]')
    got = run_js(PICKER, f"""(() => {{ const r = {rows}; lb.cat = "Sports";
      const sports = [...r].sort(LB_SORTS.category[1]).map((s) => s.wallet);
      lb.cat = "Politics"; const rest = [...r].sort(LB_SORTS.category[1]).map((s) => s.wallet);
      return [sports, rest, r.map((s) => realizedText(s, "Sports")), r.filter((s) => realizedIn(s, "Sports") > 0).map((s) => s.wallet),
        categoryNote(r, "Sports"), REALIZED_CATS]; }})()""")
    sports, rest, texts, made, note, cats = got
    assert sports[:2] == ["a", "c"] and set(sports[2:]) == {"b", "d"}  # unknown or none at the bottom, never $0
    assert rest[:3] == ["c", "a", "d"]
    assert texts == ["Sports: +$5K realized, all time", "Sports: not read yet", "Sports: −$200 realized, all time", "Sports: none"]
    assert made == ["a"]  # made money in Sports: realized profit above zero there
    assert note.startswith("Realized profit in Sports, all time: Polymarket's figures, read once a day for the traders we recommend.")
    assert "Parlays included" in note and note.endswith("Not read yet for 1 trader.")
    assert cats[0] == "Sports" and "All except Sports" not in cats and "Uncategorised" in cats  # the owner, 20 Oct


def test_the_picker_adds_no_tier_and_loosens_nothing() -> None:
    """The picker only sorts and filters the traders already listed: the recommended list's own filter (tiers) is
    untouched, and there's no raw-profit leaderboard beyond this sort."""
    page = (engine.HERE / "static" / "index.html").read_text()
    assert "const recommended = scores.filter((s) => SEG_ORDER.includes(s.segment));" in page
    assert ".filter((s) => !cat || !lb.made || realizedIn(s, cat) > 0)" in page


def test_a_kept_figure_over_a_day_old_shows_as_not_read_yet(
    kept: tuple[Directory, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 26-hour rule (CATEGORY_KEPT_S) holds on Traders as on a profile: a kept figure older than that isn't on the
    row (the page says "not read yet"), never a stale figure."""
    d, _ = kept
    d.keep_realized(SHARP, engine.category_view(realized(SHARP).to_dict()), at=NOW)
    d.keep_realized(RISER, engine.category_view(realized(RISER).to_dict()), at=NOW - engine.CATEGORY_KEPT_S - 60)
    monkeypatch.setattr(engine, "_worth_load", lambda *a, **k: {"scores": [board(SHARP, "proven"), board(RISER, "rising")]})
    monkeypatch.setattr(engine.time, "time", lambda: NOW + 60)
    rows = {s["wallet"]: s for s in TestClient(engine.app).get("/api/worth").json()["result"]["scores"]}
    assert rows[SHARP]["realized"]["usd"]["Sports"] == 5000.0
    assert "realized" not in rows[RISER]


def test_one_bad_wallet_never_stops_the_round(kept: tuple[Directory, list[str]], monkeypatch: pytest.MonkeyPatch) -> None:
    d, asked = kept

    class Odd:
        def realized_by_category(self, venue: str, wallet: str) -> RealizedByCategory:
            asked.append(wallet)
            if wallet == SHARP:
                raise RuntimeError("something nobody expected")  # not a VenueError: still only that wallet
            return realized(wallet)

    monkeypatch.setattr(engine, "background", lambda: Odd())
    got = engine.categories_round(now=NOW)
    assert asked == sorted([SHARP, RISER, BROKEN]) and got["failed"] == 1 and got["read"] == 2
    assert set(d.realized_of([SHARP, RISER, BROKEN])) == {RISER, BROKEN}
    assert "RuntimeError" in engine._category_state["error"]


def test_a_kept_figure_needs_no_turn_and_a_queued_write_goes_where_it_was_queued(
    kept: tuple[Directory, list[str]], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    d, _ = kept
    d.keep_realized(SHARP, engine.category_view(realized(SHARP).to_dict()), at=NOW)
    monkeypatch.setattr(engine.time, "time", lambda: NOW + 60)
    monkeypatch.setattr(engine, "_checks", threading.BoundedSemaphore(1))
    engine._checks.acquire()  # every turn taken: a recommended trader's kept figure still comes
    monkeypatch.setattr(engine, "CHECK_WAIT_S", 0)
    assert TestClient(engine.app).get(f"/api/categories/{SHARP}").json()["overall"] == 5300.0
    engine._checks.release()
    # the directory is captured when the write is queued: one swapped in before the writer runs never gets it
    gate = threading.Event()
    engine._directory_writer.submit(gate.wait)  # hold the writer thread
    engine._directory_later(lambda dd: dd.keep_realized(OTHER, {"rows": [], "overall": 1.0}, at=NOW))
    other = Directory(tmp_path / "elsewhere.db")
    monkeypatch.setattr(engine, "directory", lambda: other)
    gate.set()
    engine._directory_writer.submit(lambda: None).result(timeout=5)  # the queued write has run
    assert OTHER in d.realized_of([OTHER]) and other.realized_of([OTHER]) == {}
