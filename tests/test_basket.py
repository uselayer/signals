"""Baskets (the Watchlist): where a group of the traders you follow agree, worked out from what each holds now, and the
engine's basket endpoints and the page's rows (no network)."""

from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uselayer import VenueError, WhalePosition, WhaleTrade

from signals import app as engine
from signals import basket
from test_follow import FAPI, KEY, Telegram, auth, token

A, B, C, D, E = ("0x" + c * 40 for c in "abcde")
NAMES = {A: "northpaw", B: "Velodrome", C: "kestrel_88", D: "ThinEdge", E: None}
SETTLED = (engine.SETTLED_LOW, engine.SETTLED_HIGH)


def pos(market: str, outcome: str, put_in: float, paid: float, now: float, title: str = "Celtics vs Knicks") -> WhalePosition:
    size = put_in / paid
    return WhalePosition(market, title, outcome, size, paid, now, size * now, size * (now - paid))


def test_most_holders_on_one_side_agree_and_even_sides_split() -> None:
    held = {
        A: [pos("0xcel:0", "Celtics", 2000, 0.50, 0.57), pos("0xlak:0", "Lakers", 500, 0.40, 0.45, "Lakers vs Warriors")],
        B: [pos("0xcel:0", "Celtics", 3000, 0.54, 0.57), pos("0xlak:1", "Warriors", 700, 0.60, 0.55, "Lakers vs Warriors")],
        C: [pos("0xcel:0", "Celtics", 1000, 0.52, 0.57)],
        D: [pos("0xcel:1", "Knicks", 400, 0.46, 0.43)],
    }
    v = basket.view(held, NAMES, settled=SETTLED)
    [row] = v["agree"]
    assert (row["market"], row["outcome"], row["count"], row["others"], row["other_outcomes"]) == ("0xcel:0", "Celtics", 3, 1, ["Knicks"])
    assert [h["wallet"] for h in row["holders"]] == [B, A, C]  # most put in first
    assert row["put_in"] == 6000 and row["now"] == 0.57
    size = 2000 / 0.50 + 3000 / 0.54 + 1000 / 0.52
    assert row["paid"] == pytest.approx(6000 / size)  # by contracts, as Polymarket averages
    [split] = v["split"]
    assert split["condition"] == "0xlak" and [(s["outcome"], s["count"]) for s in split["sides"]] == [("Warriors", 1), ("Lakers", 1)]


def test_dust_settled_markets_and_a_lone_holder_are_not_agreement() -> None:
    held = {
        A: [pos("0xbtc:0", "Yes", 5, 0.5, 0.5), pos("0xfed:0", "Yes", 900, 0.9, 0.99), pos("0xone:0", "Yes", 900, 0.5, 0.5)],
        B: [pos("0xbtc:0", "Yes", 5, 0.5, 0.5), pos("0xfed:0", "Yes", 900, 0.9, 0.99)],
    }
    v = basket.view(held, NAMES, settled=SETTLED)
    assert v["agree"] == [] and v["split"] == []  # under $10 in, at 98¢ or more, or one trader alone


def test_a_trader_on_both_sides_counts_once_on_the_side_they_put_more_into() -> None:
    held = {A: [pos("0xcel:0", "Celtics", 300, 0.5, 0.5), pos("0xcel:1", "Knicks", 100, 0.5, 0.5)],
            B: [pos("0xcel:0", "Celtics", 200, 0.5, 0.5)]}  # fmt: skip
    [row] = basket.view(held, NAMES, settled=SETTLED)["agree"]
    assert row["count"] == 2 and row["others"] == 0


def test_more_agreement_comes_first_then_more_money() -> None:
    held = {w: [pos("0xbig:0", "Yes", 9000, 0.5, 0.5, "Big"), pos("0xsmall:0", "Yes", 20, 0.5, 0.5, "Small")] for w in (A, B)}
    held[C] = [pos("0xsmall:0", "Yes", 20, 0.5, 0.5, "Small")]
    assert [r["title"] for r in basket.view(held, NAMES, settled=SETTLED)["agree"]] == ["Small", "Big"]


# ---- each trader's position: worth now, share, rank among their own, and what their trades did to it ----

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
DAY = 86400


def trade(market: str, action: str, size: float, days_ago: float, outcome: str | None = "Celtics", price: float = 0.5) -> WhaleTrade:
    at = NOW - timedelta(days=days_ago)
    return WhaleTrade("polymarket", None, None, market, "yes", action, price, size, size * price, at, f"{market}{action}{days_ago}",  # type: ignore[arg-type]
                      "Celtics vs Knicks", outcome)  # fmt: skip


def holders(held: dict[str, list[WhalePosition]], **k: Any) -> dict[str, dict[str, Any]]:
    [row] = basket.view(held, NAMES, settled=SETTLED, at=NOW.timestamp(), **k)["agree"]
    return {h["wallet"]: h for h in row["holders"]}


def test_a_position_is_its_worth_now_with_its_share_of_the_side_and_rank_among_their_own() -> None:
    # A put $9,000 in at 90¢, now 20¢: worth $2,000. B put $3,000 in at 20¢: worth $3,000. What's at stake now leads.
    held = {A: [pos("0xcel:0", "Celtics", 9000, 0.90, 0.20), pos("0xbig:0", "Yes", 9000, 0.5, 0.6, "Big")],
            B: [pos("0xcel:0", "Celtics", 3000, 0.20, 0.20)] + [pos(f"0x{i}:0", "Yes", 20, 0.5, 0.5, "Small") for i in range(5)]}  # fmt: skip
    hs = holders(held, cut=frozenset({B}))
    assert list(hs) == [B, A]
    assert hs[A]["worth"] == pytest.approx(2000) and hs[B]["worth"] == pytest.approx(3000)
    assert hs[A]["share"] == pytest.approx(0.4) and hs[B]["share"] == pytest.approx(0.6)
    assert (hs[A]["rank"], hs[A]["of"], hs[A]["of_more"]) == (2, 2, False)  # their Big position is worth more
    assert (hs[B]["rank"], hs[B]["of"], hs[B]["of_more"]) == (1, 6, True)  # biggest of the 6 read, and they hold more


def test_a_recent_change_walks_back_from_what_they_hold_now() -> None:
    held = {w: [pos("0xcel:0", "Celtics", 500, 0.5, 0.5)] for w in (A, B, C, D, E)}  # 1,000 contracts each now
    kept = {
        A: ([trade("0xcel:0", "buy", 1000, 2)], 0.0),  # all 1,000 bought this week: new
        B: ([trade("0xcel:0", "buy", 500, 3), trade("0xcel:0", "buy", 9999, 10)], 0.0),  # 500 held before: doubled
        C: ([trade("0xcel:0", "sell", 9000, 1)], 0.0),  # sold 9,000 of 10,000: holds 90% less
        D: ([trade("0xcel:1", "buy", 400, 1, "Knicks"), trade("0xlak:0", "buy", 50, 1)], 0.0),  # traded, not this
        E: ([trade("0xcel:0", "buy", 100, 1), trade("0xcel:0", "sell", 100, 1)], 0.0),  # in and out: holds the same
    }
    hs = holders(held, trades=kept)
    assert hs[A]["recent"] == {"kind": "new"}
    assert hs[B]["recent"] == {"kind": "added", "ratio": 2.0}
    assert hs[C]["recent"] == {"kind": "reduced", "ratio": 0.1}
    assert hs[D]["recent"] == {"kind": "none"}
    assert hs[E]["recent"] == {"kind": "same", "ratio": 1.0}


def test_a_recent_change_is_not_known_rather_than_guessed() -> None:
    held = {w: [pos("0xcel:0", "Celtics", 500, 0.5, 0.5)] for w in (A, B, C, D, E)}
    short_from = (NOW - timedelta(days=2)).timestamp()
    kept = {
        A: ([], short_from),  # no trade kept, but the trades kept reach back only 2 days: not "no trades"
        B: ([trade("0xcel:999", "buy", 10, 1, None)], 0.0),  # a junk outcome index and no name: whose side?
        C: ([trade("0xcel:0", "buy", 5000, 1)], 0.0),  # bought 5,000, holds 1,000: merged or converted, not a trade
        # D: no trades kept for them
        E: ([trade("0xcel:1", "buy", 10, 1, None)], 0.0),  # no name, but a real index: the other side
    }
    hs = holders(held, trades=kept)
    assert hs[A]["recent"] == {"kind": "unknown", "why": "short", "from": "2026-10-27T12:00:00+00:00"}
    assert hs[B]["recent"] == {"kind": "unknown", "why": "unplaced"}
    assert hs[C]["recent"] == {"kind": "unknown", "why": "outside"}
    assert hs[D]["recent"] == {"kind": "unknown", "why": "unread"}
    assert hs[E]["recent"] == {"kind": "none"}


# ---- the engine ----


class Reads:
    """The checks' SDK client, as far as a basket reads it: each trader's open positions."""

    def __init__(self, held: dict[str, list[WhalePosition]], failing: tuple[str, ...] = ()) -> None:
        self.held, self.failing = held, failing
        self.calls: list[str] = []

    def positions(self, venue: str, w: str, **k: Any) -> list[WhalePosition]:
        self.calls.append(w)
        if w in self.failing:
            raise VenueError("rate_limited", "Too many requests")
        return self.held.get(w, [])


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    engine._cache.clear()
    monkeypatch.setattr(engine, "STORE_DIR", tmp_path)
    monkeypatch.setattr(engine, "CLERK_KEY", "pk_test_" + base64.b64encode(f"{FAPI}$".encode()).decode().rstrip("="))
    monkeypatch.setattr(engine, "_signing_key", lambda t: KEY.public_key())
    monkeypatch.setattr(engine, "TG_TOKEN", "")
    monkeypatch.setattr(engine, "tg", Telegram())
    monkeypatch.setattr(engine, "_directory_name", lambda w: NAMES.get(w))
    return TestClient(engine.app)


def follow(api: TestClient, *ws: str, who: str = "user_1") -> None:
    for w in ws:
        assert api.post("/api/me/follows", json={"wallet": w}, headers=auth(token(who))).status_code == 200


def test_a_basket_holds_2_or_more_traders_you_follow_and_is_yours_alone(api: TestClient) -> None:
    assert api.post("/api/me/baskets", json={"name": "Sports", "wallets": [A, B]}).status_code == 401
    follow(api, A, B, C)
    bad = {"name": "Sports", "wallets": [A, D]}, {"name": "Sports", "wallets": [A, A]}, {"name": "  ", "wallets": [A, B]}
    for body in bad:
        assert api.post("/api/me/baskets", json=body, headers=auth()).status_code == 400
    r = api.post("/api/me/baskets", json={"name": "  Sports   traders ", "wallets": [A.upper().replace("0X", "0x"), B]}, headers=auth())
    assert r.headers["cache-control"] == "private, no-store"
    [b] = r.json()["baskets"]
    assert b["name"] == "Sports traders" and b["wallets"] == [A, B] and r.json()["max_baskets"] == engine.MAX_BASKETS
    me = api.put(f"/api/me/baskets/{b['id']}", json={"name": "NBA", "wallets": [A, B, C]}, headers=auth()).json()
    assert me["baskets"] == [{"id": b["id"], "name": "NBA", "wallets": [A, B, C]}]
    other = auth(token("user_2"))  # someone else's basket is never theirs to read or change
    assert api.get(f"/api/me/baskets/{b['id']}/view", headers=other).status_code == 404
    assert api.delete(f"/api/me/baskets/{b['id']}", headers=other).status_code == 404
    api.delete(f"/api/me/follows/{C}", headers=auth())  # unfollowing takes them out of your baskets
    assert api.get("/api/me", headers=auth()).json()["baskets"][0]["wallets"] == [A, B]
    assert api.delete(f"/api/me/baskets/{b['id']}", headers=auth()).json()["baskets"] == []


def test_baskets_stop_at_the_most_you_can_have(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "MAX_BASKETS", 2)
    follow(api, A, B)
    for _ in range(2):
        assert api.post("/api/me/baskets", json={"name": "x", "wallets": [A, B]}, headers=auth()).status_code == 200
    r = api.post("/api/me/baskets", json={"name": "x", "wallets": [A, B]}, headers=auth())
    assert r.status_code == 400 and "up to 2 baskets" in r.json()["detail"]


def test_a_basket_reads_what_each_holds_once_for_everyone_and_names_who_couldnt_be_read(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    held = {A: [pos("0xcel:0", "Celtics", 2000, 0.5, 0.57)], B: [pos("0xcel:0", "Celtics", 3000, 0.54, 0.57)],
            C: [pos("0xcel:1", "Knicks", 400, 0.46, 0.43)]}  # fmt: skip
    r = Reads(held, failing=(D,))
    monkeypatch.setattr(engine, "checker", lambda: r)
    follow(api, A, B, C, D)
    follow(api, A, B, who="user_2")
    bid = api.post("/api/me/baskets", json={"name": "Sports", "wallets": [A, B, C, D]}, headers=auth()).json()["baskets"][0]["id"]
    v = api.get(f"/api/me/baskets/{bid}/view", headers=auth()).json()
    assert sorted(r.calls) == [A, B, C, D]
    assert v["name"] == "Sports" and v["read"] == 3 and v["unread"] == [D]
    [row] = v["agree"]
    assert (row["outcome"], row["count"], row["others"]) == ("Celtics", 2, 1)
    assert [t["name"] for t in v["traders"]] == ["northpaw", "Velodrome", "kestrel_88", "ThinEdge"]
    # someone else's basket of the same traders, a moment later: what they hold is kept, read once for everyone
    bid2 = api.post("/api/me/baskets", json={"name": "Mine", "wallets": [A, B]}, headers=auth(token("user_2"))).json()["baskets"][0]["id"]
    api.get(f"/api/me/baskets/{bid2}/view", headers=auth(token("user_2")))
    assert sorted(r.calls) == [A, B, C, D]


def test_a_basket_takes_recent_changes_from_the_pollers_kept_trades_without_reading(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    held = {w: [pos("0xcel:0", "Celtics", 500, 0.5, 0.5)] for w in (A, B, C)}
    r = Reads(held)
    monkeypatch.setattr(engine, "checker", lambda: r)
    follow(api, A, B, C)
    bid = api.post("/api/me/baskets", json={"name": "NBA", "wallets": [A, B, C]}, headers=auth()).json()["baskets"][0]["id"]
    recent = datetime.now(UTC) - timedelta(days=1)
    sold = [WhaleTrade("polymarket", A, None, "0xcel:0", "yes", "sell", 0.5, 1000, 500, recent, "t1", "Celtics vs Knicks", "Celtics")]
    busy = [WhaleTrade("polymarket", B, None, "0xbtc:0", "yes", "buy", 0.5, 1, 0.5, recent, f"b{i}", "BTC", "Up")
            for i in range(engine.LIVE_TRADES)]  # fmt: skip
    mono = time.monotonic()
    engine._cache[f"live:{A}"] = (mono, SimpleNamespace(trades=sold))
    engine._cache[f"live:{B}"] = (mono, SimpleNamespace(trades=busy))  # 100 trades, all from yesterday
    engine._cache[f"live:{C}"] = (mono - engine.BASKET_TRADES_S - 1, SimpleNamespace(trades=[]))  # kept too long ago
    [row] = api.get(f"/api/me/baskets/{bid}/view", headers=auth()).json()["agree"]
    hs = {h["wallet"]: h["recent"] for h in row["holders"]}
    assert hs[A] == {"kind": "reduced", "ratio": 0.5}
    assert hs[B]["kind"] == "unknown" and hs[B]["why"] == "short"  # no trade in it, but not "no trades": too few days
    assert hs[C] == {"kind": "unknown", "why": "unread"}
    assert sorted(r.calls) == [A, B, C]  # one positions read each, as before: the trades are the poller's


# ---- the page ----

ROW = ("esc", "plural", "tenths", "cents", "usd", "ago", "ADDR", "SHORT_ADDR", "displayName", "hash32", "avatar", "KIND",
       "isNew", "bk", "agreeRow", "splitRow", "BASKET_DAYS", "sharePct", "holderChange", "holderRank", "holderRow")  # fmt: skip


def test_an_agreement_row_says_who_holds_which_side_and_never_shows_a_wallet(run_js: Any) -> None:
    r = {"market": "0xcel:0", "title": "Celtics vs Knicks", "outcome": "Celtics", "count": 3, "others": 1,
         "other_outcomes": ["Knicks"], "put_in": 6000, "paid": 0.52, "now": 0.57,
         "holders": [{"wallet": B, "name": "Velodrome"}, {"wallet": A, "name": "northpaw"}, {"wallet": E, "name": None}],
         "latest": {"wallet": B, "name": "Velodrome", "kind": "added", "action": "buy", "usd": 3100, "at": "2026-10-28T12:00:00+00:00"}}  # fmt: skip
    html = run_js(ROW, f"agreeRow({json.dumps(r)}, 5)")
    for said in ("Celtics vs Knicks", "Celtics", "3 of 5", "Velodrome, northpaw, Trader 0xee…ee", "1 trader holds Knicks",
                 "They put in", "$6K", "52¢", "Market price now", "57¢", "Bought more", "$3.1K", f"#/check/{B}/0xcel%3A0"):  # fmt: skip
        assert said in html, said
    assert html.count('class="on"') == 3 and html.count('class="alt"') == 1  # the bars: this side, another side, none
    assert "0x" + "e" * 40 not in html and "0x" + "a" * 40 not in html.replace(f"#/check/{B}", "")
    lone = run_js(ROW, f"agreeRow({json.dumps(r | {'others': 0, 'other_outcomes': [], 'latest': None})}, 5)")
    assert "No one in the basket holds another side" in lone and "Check your price" not in lone
    split = run_js(ROW, f"splitRow({json.dumps({'condition': '0xlak', 'title': 'Lakers vs Warriors', 'sides': [{'outcome': 'Lakers', 'count': 2}, {'outcome': 'Warriors', 'count': 2}]})})")
    assert "Lakers vs Warriors" in split and "vs</span>" in split


def test_each_traders_position_says_its_worth_share_rank_and_change_and_never_guesses_one(run_js: Any) -> None:
    h = {"wallet": B, "name": "Velodrome", "put_in": 9000, "paid": 0.9}
    r = {"market": "0xcel:0", "title": "Celtics vs Knicks", "outcome": "Celtics", "count": 4, "others": 0, "other_outcomes": [],
         "put_in": 9300, "paid": 0.8, "now": 0.3, "latest": None, "holders": [
             h | {"worth": 3400, "share": 0.58, "rank": 1, "of": 31, "of_more": False, "recent": {"kind": "reduced", "ratio": 0.1}},
             h | {"wallet": A, "name": "northpaw", "worth": 2400, "share": 0.41, "rank": 6, "of": 500, "of_more": True, "recent": {"kind": "added", "ratio": 3.24}},
             h | {"wallet": C, "name": "kestrel_88", "worth": 40, "share": 0.004, "rank": 1, "of": 1, "of_more": False, "recent": {"kind": "none"}},
             h | {"wallet": D, "name": "ThinEdge", "worth": 30, "share": 0.003, "rank": 2, "of": 3, "of_more": False,
                  "recent": {"kind": "unknown", "why": "short", "from": "2000-01-01T00:00:00+00:00"}}]}  # fmt: skip
    html = run_js(ROW, f"agreeRow({json.dumps(r)}, 4)")
    for said in ("Each trader's position", "$3.4K", "58% of this side", "Holds 90% less than 7 days ago", "Their biggest open position",
                 "$2.4K", "Holds 3.2× what they held 7 days ago", "#6 of 500+ open positions",
                 "under 1% of this side", "No trades in it in the last 7 days", "Their only open position",
                 "Last 7 days not known: the trades we keep only cover the last", "#2 of 3 open positions"):  # fmt: skip
        assert said in html, said
    assert html.count("No trades") == 1  # the trader whose kept trades are too few days is never "no trades"
    old = run_js(ROW, f"agreeRow({json.dumps(r | {'holders': [h]})}, 4)")
    assert "Each trader's position" not in old  # a view from before worth was sent: the row as it was
