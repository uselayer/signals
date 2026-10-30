"""Baskets (the Watchlist): where a group of the traders you follow agree, worked out from what each holds now, and the
engine's basket endpoints and the page's rows (no network)."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta
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


# ---- each trader's position: worth now, share, rank among their own, and their trades in that market ----

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


def row(cond: str, idx: int | str, side: str, usd: float, days_ago: float, outcome: str | None = "Celtics") -> dict[str, Any]:
    """One of Polymarket's activity rows, as the SDK's Polymarket reader hands it back."""
    return {"conditionId": cond, "outcomeIndex": idx, "outcome": outcome, "side": side, "usdcSize": usd,
            "timestamp": int((NOW - timedelta(days=days_ago)).timestamp())}  # fmt: skip


def at(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def holders(held: dict[str, list[WhalePosition]], **k: Any) -> dict[str, dict[str, Any]]:
    [r] = basket.view(held, NAMES, settled=SETTLED, **k)["agree"]
    return {h["wallet"]: h for h in r["holders"]}


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


def test_each_holder_gets_their_story_in_the_market_from_their_trades_in_it() -> None:
    held = {w: [pos("0xcel:0", "Celtics", 500, 0.5, 0.5)] for w in (A, B, C)}
    out = basket.view(held, NAMES, settled=SETTLED)
    history = {
        A: ([row("0xcel", 0, "BUY", 900, 40), row("0xcel", 0, "BUY", 100, 3), row("0xcel", 0, "SELL", 250, 1),
             row("0xcel", 1, "BUY", 50, 0.5, "Knicks"), row("0xoth", 0, "BUY", 7, 0)], True),  # other side, other market
        B: ([row("0xcel", 0, "BUY", 500, 2)], False),  # too many trades there to read them all: no totals
        # C: their read failed
    }  # fmt: skip
    basket.add_history(out, history)
    s = {h["wallet"]: h["story"] for h in out["agree"][0]["holders"]}
    assert s[A] == {"last": {"action": "sell", "usd": 250.0, "from": at(1), "at": at(1)}, "opened": at(40), "bought": 1000.0, "sold": 250.0}
    assert s[B] == {"last": {"action": "buy", "usd": 500.0, "from": at(2), "at": at(2)}, "opened": None, "bought": None, "sold": None}
    assert s[C] is None  # not "no trades": not read


def test_a_trade_is_placed_by_its_outcome_and_one_that_cant_be_placed_leaves_the_totals_unknown() -> None:
    held = {w: [pos("0xlol:0", "Anyone's Legend", 500, 0.5, 0.5, "Anyone's Legend vs LGD")] for w in (A, B)}
    out = basket.view(held, NAMES, settled=SETTLED)
    basket.add_history(out, {
        A: ([row("0xlol", 0, "BUY", 80, 2, "Anyones Legend")], True),  # the feed drops the apostrophe: still theirs
        B: ([row("0xlol", 0, "BUY", 80, 2, None), row("0xlol", 999, "SELL", 40, 1, None)], True),  # a junk index
    })  # fmt: skip
    s = {h["wallet"]: h["story"] for h in out["agree"][0]["holders"]}
    assert s[A]["bought"] == 80.0 and s[A]["last"]["action"] == "buy"
    assert s[B]["last"] == {"action": "buy", "usd": 80.0, "from": at(2), "at": at(2)} and s[B]["bought"] is None and s[B]["sold"] is None


def test_a_last_move_is_their_trades_one_way_each_close_to_the_one_before() -> None:
    held = {w: [pos("0xcel:0", "Celtics", 500, 0.5, 0.5)] for w in (A, B)}
    out = basket.view(held, NAMES, settled=SETTLED)
    six_h = engine.watch.MOVE_S / 86400
    basket.add_history(out, {A: ([row("0xcel", 0, "BUY", 900, 9), row("0xcel", 0, "SELL", 3685, 1.2),
                                  row("0xcel", 0, "SELL", 17117, 1.2 - six_h / 2)], True),  # two sales, 3 h apart: one
                             B: ([row("0xcel", 0, "BUY", 40, 3), row("0xcel", 0, "BUY", 60, 3 - 2 * six_h)], True)})  # 12 h apart
    s = {h["wallet"]: h["story"] for h in out["agree"][0]["holders"]}
    assert s[A]["last"] == {"action": "sell", "usd": 20802.0, "from": at(1.2), "at": at(1.2 - six_h / 2)}
    assert s[B]["last"]["usd"] == 60.0 and s[B]["last"]["from"] == at(3 - 2 * six_h)


def test_whose_money_a_side_is_mostly_one_traders_led_by_one_or_shared_evenly() -> None:
    def lead(*worths: float) -> dict[str, Any]:
        held = {w: [pos("0xcel:0", "Celtics", x / 2, 0.5, 0.5)] for w, x in zip((A, B, C), worths, strict=False)}
        return basket.view(held, NAMES, settled=SETTLED)["agree"][0]["lead"]  # type: ignore[no-any-return]

    assert lead(207481, 34250) == {"kind": "mostly", "wallets": [A]}  # 86%
    assert lead(28060, 12319) == {"kind": "led", "wallets": [A]}  # 69%: the most, not most of it
    assert lead(20000, 18000) == {"kind": "shared", "wallets": [A, B]}  # within a quarter of each other
    assert lead(20000, 17000, 9000) == {"kind": "shared", "wallets": [A, B]}  # the third isn't that close


# ---- the engine ----


class Poly:
    """The SDK's Polymarket reader, as far as a basket reads it: a trader's trades in some markets."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def trades_in(self, w: str, markets: list[str], limit: int = 500) -> list[dict[str, Any]]:
        self.calls.append((w, tuple(markets)))
        return [r for r in self.rows.get(w, []) if r["conditionId"] in markets][:limit]


class Reads:
    """The checks' SDK client, as far as a basket reads it: each trader's open positions, and its Polymarket reader."""

    def __init__(self, held: dict[str, list[WhalePosition]], failing: tuple[str, ...] = (), rows: dict[str, Any] | None = None) -> None:
        self.held, self.failing = held, failing
        self.calls: list[str] = []
        self._poly = Poly(rows or {})

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


def test_a_basket_reads_each_holders_trades_in_just_the_markets_they_agree_on(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "BASKET_HISTORY_IDS", 1)  # a read per market here, to see the reads split
    monkeypatch.setattr(engine, "BASKET_HISTORY_ROWS", 3)  # a read that comes back full: their totals aren't known
    held = {A: [pos("0xcel:0", "Celtics", 500, 0.5, 0.5), pos("0xlak:0", "Lakers", 500, 0.5, 0.5, "Lakers vs Warriors")],
            B: [pos("0xcel:0", "Celtics", 500, 0.5, 0.5), pos("0xlak:0", "Lakers", 500, 0.5, 0.5, "Lakers vs Warriors")],
            C: [pos("0xsol:0", "Yes", 500, 0.5, 0.5, "SOL up?")]}  # fmt: skip
    rows = {A: [row("0xcel", 0, "BUY", 900, 3), row("0xcel", 0, "SELL", 300, 1), row("0xlak", 0, "BUY", 50, 2, "Lakers")],
            B: [row("0xcel", 0, "BUY", 10, d) for d in (5, 4, 3)]}  # fmt: skip
    r = Reads(held, rows=rows)
    monkeypatch.setattr(engine, "checker", lambda: r)
    follow(api, A, B, C)
    bid = api.post("/api/me/baskets", json={"name": "NBA", "wallets": [A, B, C]}, headers=auth()).json()["baskets"][0]["id"]
    v = api.get(f"/api/me/baskets/{bid}/view", headers=auth()).json()
    assert "changes" not in v and all("latest" not in a for a in v["agree"])  # the latest-changes list is gone
    cel = next(a for a in v["agree"] if a["condition"] == "0xcel")
    s = {h["wallet"]: h["story"] for h in cel["holders"]}
    assert s[A]["last"]["action"] == "sell" and (s[A]["bought"], s[A]["sold"]) == (900.0, 300.0)
    assert s[B]["last"]["action"] == "buy" and s[B]["bought"] is None  # their read came back full
    assert sorted(r._poly.calls) == [(A, ("0xcel",)), (A, ("0xlak",)), (B, ("0xcel",)), (B, ("0xlak",))]  # never C
    api.get(f"/api/me/baskets/{bid}/view", headers=auth())  # a minute's kept for everyone
    assert len(r._poly.calls) == 4


# ---- the page ----

ROW = ("esc", "plural", "tenths", "cents", "usd", "ago", "ADDR", "SHORT_ADDR", "displayName", "hash32", "avatar", "bk",
       "agreeCard", "UP", "DOWN", "sharePct", "dayText", "lastText", "holderRank", "holderRow", "holderDetail", "splitCard",
       "whenText", "moveText", "leadLine")  # fmt: skip




def card(run_js: Any, r: dict[str, Any], of: int, *opened: str) -> str:
    adds = "".join(f"bk.open.add({json.dumps(k)}), " for k in opened)
    return run_js(ROW, f"({adds}agreeCard({json.dumps(r)}, {of}))")  # type: ignore[no-any-return]


def iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()


def test_an_agreement_card_is_a_row_per_trader_with_their_money_and_last_move_and_never_a_wallet(run_js: Any) -> None:
    holder = {"put_in": 9000, "paid": 0.66, "rank": 5, "of": 52, "of_more": False}
    r = {"market": "0xbop:0", "condition": "0xbop", "title": "2026 Balance of Power: D Senate, D House", "outcome": "Yes",
         "count": 2, "others": 0, "now": 0.685, "holders": [
             holder | {"wallet": B, "name": "BreakTheBank", "worth": 207481, "share": 0.858,
                       "story": {"last": {"action": "sell", "usd": 17117, "at": iso(1)}, "opened": iso(27), "bought": 392046, "sold": 72529}},
             holder | {"wallet": A, "name": "gopfan2", "worth": 34250, "share": 0.142, "rank": 1, "of": 62,
                       "story": {"last": {"action": "buy", "usd": 7736, "at": iso(60)}, "opened": None, "bought": None, "sold": None}},
             holder | {"wallet": E, "name": None, "worth": 120, "share": 0.0005, "story": None}]}  # fmt: skip
    html = card(run_js, r, 3)
    old = (datetime.now(UTC) - timedelta(days=60)).astimezone()  # the page writes the day in the viewer's time
    for said in ("2026 Balance of Power: D Senate, D House", "69¢", "Market price now", "Yes", "2 of 3 agree",
                 "BreakTheBank", "$207K", "Sold yesterday", "gopfan2", "$34.3K", f"Bought {old:%b} {old.day}",
                 "Trader 0xee…ee", "86% of the money on this side", "width:86%", "width:2%"):  # fmt: skip
        assert said in html, said
    assert "0x" + "e" * 40 not in re.sub(r"<[^>]+>", "", html)  # never shown as text (it keys the row and its links)
    assert "Check your price" not in html and "Opened" not in html  # all rows closed
    assert html.count('viewBox="0 0 12 12"') == 2  # a move for the two whose trades were read; none for the third

    sold = card(run_js, r, 3, f"0xbop:0|{B}")  # BreakTheBank's, tapped: the facts, and no price check after a sale
    for said in ("Opened", "Paid on average", "66¢", "Bought", "$392K", "Sold", "$72.5K", "Their #5 biggest of 52 open positions",
                 f"#/watch/{B}"):  # fmt: skip
        assert said in sold, said
    assert "Check your price" not in sold
    bought = card(run_js, r, 3, f"0xbop:0|{A}")  # gopfan2's: too many trades to total, so no Opened, Bought or Sold
    assert "Their biggest of 62 open positions" in bought and f"#/check/{A}/0xbop%3A0" in bought
    assert "Opened" not in bought and "<span>Bought</span>" not in bought and "<span>Sold</span>" not in bought


def test_a_disagreement_card_is_each_sides_traders_and_money(run_js: Any) -> None:
    s = {"condition": "0xak", "title": "Will Dan Sullivan win the Alaska Senate race in 2026?", "sides": [
        {"outcome": "Yes", "worth": 30899, "holders": [{"wallet": B, "name": "BreakTheBank"}]},
        {"outcome": "No", "worth": 16079, "holders": [{"wallet": A, "name": "gopfan2"}]}]}  # fmt: skip
    html = run_js(ROW, f"splitCard({json.dumps(s)})")
    for said in ("Will Dan Sullivan win the Alaska Senate race in 2026?", "Yes", "BreakTheBank", "$30.9K", "No", "gopfan2", "$16.1K",
                 "flex:30899", "flex:16079"):  # fmt: skip
        assert said in html, said


LINE = ("esc", "usd", "ADDR", "SHORT_ADDR", "displayName", "dayText", "whenText", "moveText", "leadLine")


def test_a_cards_line_says_whose_money_it_is_how_much_and_what_they_did_last(run_js: Any) -> None:
    def line(lead: dict[str, Any], worth: float, holders: list[dict[str, Any]], outcome: str = "Yes") -> str:
        r = {"outcome": outcome, "worth": worth, "lead": lead, "holders": holders}
        return re.sub(r"<[^>]+>", "", run_js(LINE, f"leadLine({json.dumps(r)})"))

    def h(w: str, name: str, worth: float, action: str | None = None, usd: float = 0, days: float = 0, opened: bool = False,
          since: float | None = None) -> dict[str, Any]:  # fmt: skip
        when = iso(days)
        last = {"action": action, "usd": usd, "from": when if since is None else iso(since), "at": when}
        return {"wallet": w, "name": name, "worth": worth, "story": action and {"last": last, "opened": last["from"] if opened else iso(90)}}

    btb, gop = (B, "BreakTheBank"), (A, "gopfan2")
    assert line({"kind": "mostly", "wallets": [B]}, 241731, [h(*btb, 207481, "sell", 20802, 1), h(*gop, 34250, "buy", 7736, 9)]) == (
        "Mostly BreakTheBank's money: $207K of the $242K on Yes. They sold $20.8K of it yesterday.")
    assert line({"kind": "mostly", "wallets": [B]}, 39972, [h(*btb, 38925, "buy", 40050, 1, opened=True), h(*gop, 1047, "buy", 256, 205)]) == (
        "Mostly BreakTheBank's money: $38.9K of the $40K on Yes. They put it all in yesterday.")
    began = (datetime.now(UTC) - timedelta(days=3)).astimezone()  # a run of buys over days: since when, not "just now"
    assert line({"kind": "mostly", "wallets": [B]}, 49200, [h(*btb, 41600, "buy", 30460, 0.004, since=3), h(*gop, 7600, "buy", 2301, 23)]) == (
        f"Mostly BreakTheBank's money: $41.6K of the $49.2K on Yes. They have added $30.5K since {began:%b} {began.day}.")
    assert line({"kind": "led", "wallets": [B]}, 40379, [h(*btb, 28060, "buy", 43, 0.04), h(*gop, 12319, "buy", 11, 23)], "No") == (
        "Led by BreakTheBank: $28.1K of the $40.4K on No. They added $43 58 minutes ago; gopfan2 last bought 3 weeks ago.")
    assert line({"kind": "shared", "wallets": [B, A]}, 38000, [h(*btb, 20000, "buy", 5000, 2), h(*gop, 18000, "sell", 1000, 5)]) == (
        "Shared evenly: $20K from BreakTheBank, $18K from gopfan2. BreakTheBank added $5K 2 days ago; gopfan2 sold $1K of it 5 days ago.")
    assert line({"kind": "mostly", "wallets": [B]}, 241731, [h(*btb, 207481), h(*gop, 34250)]) == (
        "Mostly BreakTheBank's money: $207K of the $242K on Yes.")  # their trades weren't read: no guess at what they did
