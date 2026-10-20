"""The Leaderboard's world (SIGNALS_SKILL_TEST off, the default) outside Traders: the Feed's Top traders, a trader's
page from their track record, and alerts' names, none with a tier, label or copy status (no network: the SDK's reads
are stand-ins)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from signals import app as engine
from signals import records
from signals.directory import Seen

DAY = 86400
AMY = "0x" + "a1" * 20
BEN = "0x" + "b2" * 20
CAL = "0x" + "c3" * 20


@pytest.fixture
def board(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Any:
    engine._cache.clear()
    engine._record_one.clear()
    monkeypatch.setattr(engine, "STORE_DIR", tmp_path)
    monkeypatch.setattr(engine, "SKILL_TEST", False)
    return engine.directory()


def rec(pnl30: float, read_at: float | None = None, last_buy: float | None = None) -> dict[str, Any]:
    now = time.time()
    per = {p: {"trading_pnl": pnl30, "realized": pnl30 / 2, "volume": 10_000.0, "return_per_dollar": pnl30 / 10_000,
               "won": 12, "closed": 20} for p in ("7d", "30d", "90d")}  # fmt: skip
    per["all"] = {"trading_pnl": pnl30, "volume": 10_000.0}
    return {"read_at": read_at or now, "since": now - 200 * DAY, "periods": per, "weeks_up": 7, "weeks_known": 12,
            "pnl_weeks": [1.0] * 12, "pnl_daily": None, "typical_usd": 80.0, "markets_per_day": 2.0, "paid_30d": 0.62,
            "worst_drop": {"90d": {"usd": 40.0}}, "last_buy": last_buy or now - DAY, "positions_complete": True}  # fmt: skip


def wait_for_writer() -> None:
    engine._directory_writer.submit(lambda: None).result()


# ---- nothing says a verdict ----


def test_with_the_skill_test_off_no_check_result_reaches_the_feed_alerts_or_pages(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    kept = {"scores": [{"wallet": AMY, "segment": "proven", "name": "amy", "copyable": "yes"}]}
    monkeypatch.setattr(engine, "_check_load", lambda: kept)
    assert engine._worth_load() is None
    assert engine._stored_score(AMY) is None


# ---- the Feed's Top traders ----


def test_top_traders_are_the_leaderboards_first_by_30_day_profit_with_no_tier_or_copy_offer(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    board.add([Seen(w, "leaderboard", "PNL MONTH OVERALL", name=n) for w, n in ((AMY, "amy"), (BEN, "ben"), (CAL, "cal"))])
    for w, pnl in ((AMY, 500.0), (BEN, 900.0), (CAL, 100.0)):
        board.keep_record(w, rec(pnl))
    monkeypatch.setattr(engine, "FEED_TOP", 2)
    shown: list[Any] = []
    monkeypatch.setattr(engine, "_feed", lambda people, *a, **k: shown.append(people) or {"bets": []})
    got = TestClient(engine.app).get("/api/live").json()
    assert got["pool"] == "top" and [t["wallet"] for t in got["traders"]] == [BEN, AMY]
    assert all(t["segment"] is None and t["label"] is None and t["copy_ok"] is False for t in got["traders"])
    assert engine._live_wanted()[1] == {AMY, BEN}  # the poller reads the same traders


def test_with_the_skill_test_on_the_feed_is_recommended_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    kept = {"scores": [{"wallet": AMY, "segment": "proven", "name": "amy", "label": "Sharp"}, {"wallet": BEN, "segment": "no_edge"}]}
    monkeypatch.setattr(engine, "_worth_load", lambda *a: kept)
    monkeypatch.setattr(engine, "_feed", lambda people, *a, **k: {"bets": []})
    got = TestClient(engine.app).get("/api/live").json()
    assert got["pool"] == "recommended" and [t["wallet"] for t in got["traders"]] == [AMY]


# ---- a trader's page ----


def test_a_traders_page_shows_a_fresh_record_without_reading_and_without_a_verdict(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    board.add([Seen(AMY, "leaderboard", "PNL MONTH OVERALL", name="amy")])
    board.keep_record(AMY, rec(500.0))
    monkeypatch.setattr(engine, "record_now", lambda *a, **k: pytest.fail("a fresh record is shown as kept"))
    got = TestClient(engine.app).get(f"/api/worth/{AMY}").json()
    assert got["record"] is True and got["name"] == "amy" and got["periods"]["30d"]["realized"] == 250
    assert got["win"]["90d"] == {"won": 12, "closed": 20, "days": 90} and got["paid_30d"] == 0.62
    assert got["worst_drop"]["90d"]["usd"] == 40 and got["trades_per_day"] == 2.0
    assert not {"segment", "label", "copy_ok", "copy_label", "why", "checks"} & got.keys()


def test_a_traders_page_without_a_fresh_record_reads_one_and_keeps_it_for_the_leaderboard(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    now = time.time()
    asked: list[str] = []
    fill = SimpleNamespace(at=datetime.fromtimestamp(now - 3600, UTC), action="buy", market="0xm1:0", usd=90.0, price=0.9)
    monkeypatch.setattr(engine.reads.whales, "trades", lambda venue, w, limit: asked.append("trades") or [fill])
    monkeypatch.setattr(records, "_pnl_points", lambda wh, w: asked.append("pnl") or [
        {"timestamp": int(now - 40 * DAY), "realized_pnl": 0, "unrealized_pnl": 0, "volume_usdc": 0},
        {"timestamp": int(now - DAY), "realized_pnl": 30, "unrealized_pnl": 0, "volume_usdc": 900}])
    monkeypatch.setattr(engine.reads.whales, "completed_positions", lambda w, **k: asked.append("positions") or SimpleNamespace(positions=[], complete=True), raising=False)
    got = TestClient(engine.app).get(f"/api/worth/{AMY}").json()
    assert asked == ["trades", "pnl", "positions"]
    assert got["record"] is True and got["periods"]["30d"]["trading_pnl"] == 30 and got["paid_30d"] == 0.9
    wait_for_writer()
    assert board.record(AMY)["via"] == "read"  # type: ignore[index]
    TestClient(engine.app).get(f"/api/worth/{AMY}")
    assert asked.count("trades") == 1  # read once: the next page shows it as kept


def test_when_a_record_cant_be_read_now_an_older_one_is_shown_with_when_it_was_read(board: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    old = time.time() - 3 * DAY
    board.keep_record(AMY, rec(500.0, read_at=old), at=old)

    def busy(*a: Any, **k: Any) -> Any:
        raise HTTPException(429, detail="Lots of traders are being checked right now. Try again in a minute.")

    monkeypatch.setattr(engine, "record_now", busy)
    got = TestClient(engine.app).get(f"/api/worth/{AMY}").json()
    assert got["record"] is True and got["stored_at"] == pytest.approx(old)
    assert TestClient(engine.app).get(f"/api/worth/{BEN}").status_code == 429  # nothing to show: says so
    assert TestClient(engine.app).get("/api/worth/not-a-wallet").status_code == 400


# ---- alerts ----


def test_alerts_name_a_trader_from_the_directory_and_link_every_wallets_page(board: Any) -> None:
    board.add([Seen(AMY, "leaderboard", "PNL MONTH OVERALL", name="amy")])
    assert engine._who(AMY) == "amy" and engine._who(BEN) == f"Trader {BEN[:4]}…{BEN[-2:]}"
    assert engine._scored(BEN)


# ---- the average price paid ----


def test_the_average_price_paid_counts_each_outcome_once_whatever_its_size() -> None:
    now = 1_800_000_000.0
    trades = [(now - 60, True, "0xm1", 900.0, 0.9, "0xm1:0"), (now - 50, True, "0xm1", 100.0, 1.0, "0xm1:0"),
              (now - 40, True, "0xm2", 10.0, 0.2, "0xm2:1"),
              (now - 40 * DAY, True, "0xm3", 10.0, 0.01, "0xm3:0"),  # older than 30 days
              (now - 30, False, "0xm4", 10.0, 0.5, "0xm4:0")]  # a sell  # fmt: skip
    got = records.build([], None, trades, now)
    # 0xm1:0: $1,000 for 1,100 contracts (91¢); 0xm2:1: 20¢; each outcome once, not by dollars
    assert got["paid_30d"] == pytest.approx((1000 / 1100 + 0.2) / 2, abs=1e-4)
    assert records.build([], None, [t[:4] for t in trades], now)["paid_30d"] is None  # no prices read: unknown
