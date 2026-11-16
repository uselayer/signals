"""Your copies (signals/copies.py, /api/me/copies): every Copy tap of an account with copying on, what it bought or
why it didn't, the trader's own price, the price now or how it ended, and one line per trader. No exchange is read:
own_trading's order calls are the stand-in Exchange (test_own_trading) and own_trading.marks is replaced."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
import test_own_trading as own
from fastapi.testclient import TestClient
from test_alerts import auth
from test_own_trading import MISS, OWNER, Exchange, new_alert, tap

from signals import app as engine
from signals import copies, copying, own_trading


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    return own.api.__wrapped__(monkeypatch, tmp_path)  # type: ignore[attr-defined,no-any-return]


@pytest.fixture
def ex(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> Exchange:
    return own.ex.__wrapped__(api, monkeypatch)  # type: ignore[attr-defined,no-any-return]


def marks(mark: float | None = 0.50, settled: bool = False, outcome: str | None = None) -> Any:
    engine._cache.clear()  # the view's reads are kept a minute: a new answer needs a fresh read
    return lambda code, store_dir: {("KX-RAIN", "yes"): {"mark": mark, "settled": settled, "outcome": outcome}}


def mine(api: TestClient, uid: str = OWNER) -> dict[str, Any]:
    r = api.get("/api/me/copies", headers=auth(uid))
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_only_an_account_with_copying_on_sees_the_tab_and_its_copies(ex: Exchange, api: TestClient) -> None:
    assert api.get("/api/me/copies/on", headers=auth(OWNER)).json() == {"on": True}
    assert api.get("/api/me/copies/on", headers=auth("user_2")).json() == {"on": False}
    assert api.get("/api/me/copies", headers=auth("user_2")).status_code == 404
    assert api.get("/api/me/copies").status_code == 401
    assert mine(api)["rows"] == []


def test_a_bought_copy_shows_what_it_cost_beside_the_traders_price_and_its_price_now(
    ex: Exchange, api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid = new_alert()
    tap(f"cv:{aid}")
    monkeypatch.setattr(own_trading, "marks", marks(0.50))
    d = mine(api)
    [r] = d["rows"]
    with engine._db() as con:
        theirs = con.execute("SELECT price, usd FROM buys WHERE uid = ?", (OWNER,)).fetchone()
    assert (r["id"], r["exchange"], r["status"], r["bought"]) == (aid, "Kalshi", "open", True)
    assert r["title"] and r["label"] and r["url"] == "https://kalshi.com/m"
    assert (r["their_price"], r["their_usd"]) == tuple(theirs)
    assert r["paid"] == pytest.approx(23.65 / 55) and r["now"] == 0.50
    assert r["worth"] == pytest.approx(27.5) and r["pnl"] == pytest.approx(27.5 - 23.65)
    assert r["trade_at"] and r["sent_at"] and r["tapped_at"]  # the story: their buy, the alert, the tap
    t = d["totals"]
    assert (t["put_in"], t["bought"], t["missed"], t["unvalued"]) == (23.65, 1, 0, 0)
    assert t["profit"] == pytest.approx(3.85) and t["open_worth"] == pytest.approx(27.5) and t["paid_out"] == 0
    assert {c["exchange"]: c["usd"] for c in d["cash"]} == {"Kalshi": 100.0, "Polymarket US": 100.0}
    [tr] = d["traders"]
    assert (tr["bought"], tr["open"], tr["put_in"]) == (1, 1, 23.65)
    assert d["failed"] == []


def test_a_settled_copy_reads_won_lost_or_voided(ex: Exchange, api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    tap(f"cv:{new_alert()}")
    monkeypatch.setattr(own_trading, "marks", marks(None, True, "yes"))
    [r] = mine(api)["rows"]
    assert (r["status"], r["now"], r["worth"]) == ("won", 1.0, 55.0)
    assert mine(api)["totals"]["paid_out"] == 55.0
    monkeypatch.setattr(own_trading, "marks", marks(None, True, "no"))
    [r] = mine(api)["rows"]
    assert (r["status"], r["worth"], r["pnl"]) == ("lost", 0.0, -23.65)
    monkeypatch.setattr(own_trading, "marks", marks(None, True, "void"))
    [r] = mine(api)["rows"]
    assert (r["status"], r["worth"], r["pnl"]) == ("void", 23.65, 0.0)


def test_an_exchange_that_cant_be_read_is_named_and_its_copies_show_no_price(
    ex: Exchange, api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tap(f"cv:{new_alert()}")
    engine._cache.clear()
    monkeypatch.setattr(own_trading, "marks", lambda code, store_dir: None)
    d = mine(api)
    assert d["failed"] == ["Kalshi"] and d["rows"][0]["worth"] is None
    assert (d["totals"]["put_in"], d["totals"]["unvalued"], d["totals"]["profit"]) == (23.65, 1, 0)


def test_a_missed_copy_says_why_and_spends_nothing(ex: Exchange, api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ex.answer = dict(MISS)
    tap(f"cv:{new_alert()}")
    monkeypatch.setattr(own_trading, "marks", marks())
    d = mine(api)
    [r] = d["rows"]
    assert (r["status"], r["bought"], r["worth"]) == ("missed", False, None)
    assert r["why"] == "No one was selling at 45¢ or less."
    assert (d["totals"]["bought"], d["totals"]["missed"], d["totals"]["put_in"]) == (0, 1, 0)


def test_an_account_sees_only_its_own_copies(ex: Exchange, api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    tap(f"cv:{new_alert()}")
    with engine._db() as con:
        con.execute("INSERT INTO copy_orders (alert_id, uid, token, usd, max_price, state, at) VALUES"
                    " ('other', 'user_2', 'kalshi:KX-SNOW:yes', 25, 0.5, 'filled', 1)")  # fmt: skip
    monkeypatch.setattr(own_trading, "marks", marks())
    assert [r["token"] if "token" in r else r["market"] for r in mine(api)["rows"]] == ["KX-RAIN"]


def row(**kw: Any) -> dict[str, Any]:
    base = {"id": "a", "code": "k", "venue": "kalshi", "exchange": "Kalshi", "market": "M", "side": "yes", "title": "T",
            "label": "Yes", "trader": "0xa", "trader_name": "Ann", "url": None, "usd": 25.0, "max_price": 0.53,
            "state": "filled", "spent": 25.0, "shares": 50.0, "error": None, "tapped_at": 10.0, "sent_at": 5.0,
            "trade_at": 1.0, "alert_price": 0.5, "their_price": 0.40, "their_usd": 500.0, "limit_until": None}  # fmt: skip
    return base | kw


def test_by_trader_puts_the_same_dollars_in_at_the_traders_own_price() -> None:
    rows = [row(id="a", market="M1"), row(id="b", market="M2", spent=10.0, shares=20.0, their_price=0.50),
            row(id="c", market="M3", state="missed", spent=None, shares=None, error="not_filled")]  # fmt: skip
    own = {"k": {("M1", "yes"): {"mark": 0.60, "settled": False, "outcome": None},
                 ("M2", "yes"): {"mark": None, "settled": True, "outcome": "no"}}}  # fmt: skip
    v = copies.view(rows, own, {})
    [t] = v["traders"]
    # you: M1 50 × 60¢ − $25 = +$5; M2 lost −$10. Them, same dollars: M1 $25 / 40¢ × 60¢ − $25 = +$12.50; M2 −$10
    assert (t["bought"], t["missed"], t["put_in"]) == (2, 1, 35.0)
    assert t["same_you"] == pytest.approx(-5.0) and t["same_them"] == pytest.approx(2.5) and t["same_put_in"] == 35.0
    assert v["totals"]["gap"] == pytest.approx(((0.5 - 0.4) + (0.5 - 0.5)) / 2)  # 10¢ worse, then the same price
    assert [r["status"] for r in v["rows"]] == ["open", "lost", "missed"]


def test_a_one_tap_copy_keeps_its_names_and_an_old_table_gets_the_columns() -> None:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE copy_offers (alert_id TEXT PRIMARY KEY, uid TEXT NOT NULL, token TEXT NOT NULL,"
                " price REAL NOT NULL, at REAL NOT NULL)")  # fmt: skip
    con.execute("INSERT INTO copy_offers VALUES ('old', 'u', 't0', 0.4, 1)")
    copying.migrate(con)
    copying.migrate(con)  # once is enough; twice changes nothing
    copying.offer(con, "new", "u", "t1", 0.42, label="Yes", title="Rain in NYC?", trader="Sam", url="https://p/m")
    got = con.execute("SELECT alert_id, label, title, trader, url FROM copy_offers ORDER BY at").fetchall()
    assert got == [("old", None, None, None, None), ("new", "Yes", "Rain in NYC?", "Sam", "https://p/m")]


@pytest.mark.parametrize(("error", "said"), [
    ("fak_not_filled", "No one was selling at 45¢ or less."),
    ("not_enough_balance", "Your balance was under $25.00."),
    ("market_not_ready", "The market wasn't taking orders."),
    ("Trading is restricted for this account in this market", "Kalshi said: Trading is restricted for this account in this market"),
    ("odd_code", "Kalshi didn't take the order (odd_code). Nothing was spent."),
    (None, "The exchange didn't take the order. Nothing was spent."),
])  # fmt: skip
def test_why_a_copy_missed_is_one_plain_sentence_or_the_exchanges_own_words(error: str | None, said: str) -> None:
    assert copies.reason(error, 0.45, 25.0, "Kalshi") == said


def test_a_tap_from_before_offers_kept_names_takes_them_from_the_alert(
    ex: Exchange, api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    aid = new_alert()
    tap(f"cv:{aid}")
    monkeypatch.setattr(own_trading, "marks", marks())
    before = mine(api)["rows"][0]
    with engine._db() as con:
        con.execute("UPDATE own_offers SET title = NULL, label = NULL, trader = NULL WHERE alert_id = ?", (aid,))
    engine._cache.clear()
    after = mine(api)["rows"][0]
    assert (after["title"], after["label"], after["trader_name"]) == (before["title"], before["label"], before["trader_name"])
    assert after["title"] and after["title"] != "A market"
