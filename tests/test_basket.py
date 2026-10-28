"""Baskets (the Watchlist): where a group of the traders you follow agree, worked out from what each holds now, and the
engine's basket endpoints and the page's rows (no network)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uselayer import VenueError, WhalePosition

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


# ---- the page ----

ROW = ("esc", "plural", "tenths", "cents", "usd", "ago", "ADDR", "SHORT_ADDR", "displayName", "hash32", "avatar", "KIND",
       "isNew", "bk", "agreeRow", "splitRow")  # fmt: skip


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
