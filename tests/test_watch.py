"""Watching a trader (the Watchlist): what each of their moves did to their position, worked out from their trades and
what they hold now, and the engine's watch page, Watchlist and "Follow a trader" lookup (no network)."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from uselayer import WhalePosition, WhaleTrade

from signals import app as engine
from signals import watch
from test_follow import FAPI, KEY, Telegram, auth

NOW = datetime.now(UTC).replace(microsecond=0)  # the engine reads the clock: trades are this long before now
W = "0x" + "7c" * 20
LAKERS, FED, CHIEFS, ARSENAL, BTC = "0xlak:0", "0xfed:1", "0xchi:0", "0xars:0", "0xbtc:1"
_n = iter(range(10_000))


def fill(market: str, action: str, usd: float, price: float, ago: timedelta, *, title: str | None = None) -> WhaleTrade:
    return WhaleTrade("polymarket", W, "northpaw", market, "yes", action, price, usd / price, usd,  # type: ignore[arg-type]
                      NOW - ago, f"t{next(_n)}", title=title or market, outcome="Yes", url=f"https://polymarket.com/event/{market}")  # fmt: skip


def held(market: str, size: float, paid: float, now: float) -> WhalePosition:
    return WhalePosition(market, market, "Yes", size, paid, now, size * now, size * (now - paid))


D, H, M = timedelta(days=1), timedelta(hours=1), timedelta(minutes=1)
TRADES = [
    # Lakers: three buys at rising prices; the last one in three fills a few minutes apart (one move)
    fill(LAKERS, "buy", 1700, 0.29, 12 * D), fill(LAKERS, "buy", 2000, 0.30, 6 * D),
    fill(LAKERS, "buy", 1000, 0.31, 10 * M), fill(LAKERS, "buy", 800, 0.31, 7 * M), fill(LAKERS, "buy", 600, 0.31, 4 * M),
    # the Fed: a new position today
    fill(FED, "buy", 1850, 0.62, 38 * M),
    # the Chiefs: bought, then sold half below what they paid
    fill(CHIEFS, "buy", 1800, 0.54, 2 * D), fill(CHIEFS, "sell", 1666.67 * 0.51, 0.51, 3 * H),
    # Arsenal: bought, then sold all of it (not held now)
    fill(ARSENAL, "buy", 2200, 0.24, 35 * D), fill(ARSENAL, "buy", 1, 0.25, 20 * D), fill(ARSENAL, "sell", 9170 * 0.33, 0.33, 1 * D),
    # Bitcoin: bought, and not held now with no sale (it settled, or they redeemed it): only "bought"
    fill(BTC, "buy", 3400, 0.71, 3 * D),
]  # fmt: skip
LAKERS_SIZE = 1700 / 0.29 + 2000 / 0.30 + 2400 / 0.31
POSITIONS = [held(LAKERS, LAKERS_SIZE, 0.30, 0.33), held(FED, 1850 / 0.62, 0.62, 0.62), held(CHIEFS, 1666.67, 0.54, 0.51)]


def the_view(positions: list[WhalePosition] | None = POSITIONS, since: timedelta = 30 * D) -> dict[str, Any]:
    return watch.view(TRADES, positions, since=(NOW - since).timestamp(), now=NOW.timestamp())


def moves_of(v: dict[str, Any], market: str) -> list[dict[str, Any]]:
    return [m for m in v["moves"] if m["market"] == market]


def test_each_move_says_what_it_did_to_their_position_from_what_they_hold_now() -> None:
    v = the_view()
    lakers = moves_of(v, LAKERS)
    assert [m["kind"] for m in lakers] == ["added", "added", "new"]  # newest first
    last = lakers[0]
    assert (last["usd"], last["fills"], last["price"]) == (2400, 3, 0.31)  # three fills minutes apart: one move
    assert last["buy_count"] == 3 and last["rising"] and not last["falling"]  # third buy, each at a higher price
    assert last["opened_at"] == (NOW - 12 * D).isoformat() and last["held_now"] and last["now"] == 0.33
    assert [m["kind"] for m in moves_of(v, FED)] == ["new"]
    chiefs = moves_of(v, CHIEFS)
    assert [m["kind"] for m in chiefs] == ["sold_some", "new"]
    assert chiefs[0]["paid"] == 0.54 and chiefs[0]["price"] == 0.51  # sold below what they paid (Polymarket's average)
    arsenal = moves_of(v, ARSENAL)
    assert [m["kind"] for m in arsenal] == ["closed", "added"]  # their first buy is older than the 30 days shown
    assert arsenal[0]["paid"] == pytest.approx((2200 + 1) / (2200 / 0.24 + 1 / 0.25), abs=1e-4)  # from the buys we read
    assert not arsenal[0]["held_now"] and arsenal[0]["now"] is None
    assert [m["kind"] for m in moves_of(v, BTC)] == ["bought"]  # not held and no sale: never guessed
    assert [m["at"] for m in v["moves"]] == sorted((m["at"] for m in v["moves"]), reverse=True)


def test_fills_far_apart_are_separate_moves_and_a_walk_back_never_goes_below_zero() -> None:
    trades = [fill(FED, "buy", 100, 0.5, 20 * H), fill(FED, "buy", 100, 0.5, 14 * H + 1 * M),  # one move: a resting order
              fill(FED, "buy", 100, 0.5, 8 * H)]  # just over 6 hours later: another  # fmt: skip
    v = watch.view(trades, [held(FED, 600, 0.5, 0.5)], since=(NOW - D).timestamp(), now=NOW.timestamp())
    assert [(m["kind"], m["usd"]) for m in v["moves"]] == [("added", 100), ("new", 200)]
    # a split or merge (not a trade) left them holding less than their buys add up to: zero, never negative
    v = watch.view(trades, [held(FED, 100, 0.5, 0.5)], since=(NOW - D).timestamp(), now=NOW.timestamp())
    assert [m["kind"] for m in v["moves"]] == ["new", "new"] and min(m["before"] for m in v["moves"]) == 0


def test_without_their_positions_a_move_is_only_bought_or_sold() -> None:
    v = the_view(positions=None)
    assert {m["kind"] for m in v["moves"]} == {"bought", "sold"}
    assert v["series"] == [] and v["holdings"] == [] and v["put_in"] is None


def test_the_line_ends_at_what_they_put_in_and_steps_at_each_move_in_what_they_hold() -> None:
    v = the_view()
    total = LAKERS_SIZE * 0.30 + 1850 + 1666.67 * 0.54
    assert v["put_in"] == pytest.approx(total, abs=0.02)
    assert [h["market"] for h in v["holdings"]] == [LAKERS, FED, CHIEFS]  # biggest first
    s = v["series"]
    assert s[0][0] == (NOW - 30 * D).timestamp() and s[-1] == [NOW.timestamp(), pytest.approx(total, abs=0.02)]
    # before the 30 days: none of the Lakers, Fed or Chiefs bought yet, so nothing of what they hold now
    assert s[0][1] == pytest.approx(0, abs=0.02)
    assert [round(t) for t, _ in s[1:-1]] == sorted(round(t) for t, _ in s[1:-1])
    # Arsenal and Bitcoin aren't held: their moves are listed but not in the line
    assert len(s) == 2 + 3 + 2 + 1  # since, Lakers' 3 moves, the Chiefs' 2, the Fed's 1, now
    # a shorter window starts the line at what they already held then
    assert the_view(since=5 * D)["series"][0][1] == pytest.approx((1700 / 0.29 + 2000 / 0.30) * 0.30, abs=0.02)


# ---- the engine ----


class Reads:
    """The checks' SDK client, as far as a watch page reads it."""

    def __init__(self, trades: list[WhaleTrade], positions: list[WhalePosition]) -> None:
        self.trades_, self.positions_ = trades, positions
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def trades(self, venue: str, w: str, **k: Any) -> list[WhaleTrade]:
        self.calls.append(("trades", k))
        return self.trades_

    def positions(self, venue: str, w: str, **k: Any) -> list[WhalePosition]:
        self.calls.append(("positions", k))
        if k.get("market"):
            wanted = k["market"].split(",")
            return [p for p in self.positions_ if p.market.partition(":")[0] in wanted]
        return self.positions_[: k.get("limit", 50)]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    engine._cache.clear()
    monkeypatch.setattr(engine, "STORE_DIR", tmp_path)
    monkeypatch.setattr(engine, "CLERK_KEY", "pk_test_" + base64.b64encode(f"{FAPI}$".encode()).decode().rstrip("="))
    monkeypatch.setattr(engine, "_signing_key", lambda t: KEY.public_key())
    monkeypatch.setattr(engine, "TG_TOKEN", "")
    monkeypatch.setattr(engine, "tg", Telegram())
    monkeypatch.setattr(engine, "_categories", lambda markets: {LAKERS: "Sports", CHIEFS: "Sports", FED: "Economics"})
    return TestClient(engine.app)


def test_a_watch_page_needs_no_account_and_reads_twice_kept_for_everyone(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = Reads(TRADES, POSITIONS)
    monkeypatch.setattr(engine, "checker", lambda: r)
    d = api.get(f"/api/watch/{W.upper().replace('0X', '0x')}").json()
    assert d["wallet"] == W and d["name"] == "northpaw" and d["trades_read"] == len(TRADES)
    assert [c[0] for c in r.calls] == ["trades", "positions"] and r.calls[0][1]["limit"] == engine.WATCH_TRADES
    lakers = next(m for m in d["moves"] if m["market"] == LAKERS)
    assert (lakers["kind"], lakers["category"], lakers["status"]) == ("added", "Sports", "in")  # 33¢, they paid 31¢
    assert next(m for m in d["moves"] if m["market"] == ARSENAL)["status"] == "closed"
    assert not d["short"] and not d["positions_cut"]
    api.get(f"/api/watch/{W}")
    assert len(r.calls) == 2  # kept: one read for everyone looking within WATCH_TTL_S
    assert api.get("/api/watch/0x123").status_code == 400


def test_a_busy_trader_s_window_is_as_far_back_as_their_trades_read(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    busy = [fill(FED, "buy", 10, 0.5, i * 10 * M) for i in range(engine.WATCH_TRADES)]  # 500 trades: about 3.5 days
    monkeypatch.setattr(engine, "checker", lambda: Reads(busy, [held(FED, 10_000, 0.5, 0.5)]))
    d = api.get(f"/api/watch/{W}").json()
    assert d["short"] and d["since"] == (NOW - (engine.WATCH_TRADES - 1) * 10 * M).timestamp()


def test_a_full_positions_list_reads_the_outcomes_they_traded_that_it_left_out(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "POSITIONS_READ", 2)
    r = Reads(TRADES, [held("0xa:0", 5, 0.5, 0.5), held("0xb:0", 5, 0.5, 0.5), *POSITIONS])
    monkeypatch.setattr(engine, "checker", lambda: r)
    d = api.get(f"/api/watch/{W}").json()
    assert d["positions_cut"]
    assert [c for c, k in r.calls if k.get("market")] == ["positions"]  # one more read, for the outcomes left out
    assert next(m for m in d["moves"] if m["market"] == LAKERS)["kind"] == "added"  # found by that read: still held


def test_follow_a_trader_finds_a_pasted_wallet_or_link_or_a_name(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    for text in (W, W.upper().replace("0X", "0x"), f"https://polymarket.com/profile/{W}?tab=activity"):
        assert api.get("/api/find", params={"q": text}).json()["wallet"] == W
    from uselayer import Trader, VenueError

    asked: list[str] = []
    searched: list[str] = []
    on_polymarket: list[Trader] = []

    class Dir:
        def leaderboard(self, *a: Any, q: str = "", **k: Any) -> dict[str, Any]:
            asked.append(q)
            return {"rows": [{"wallet": W, "name": "northpaw", "periods": {"30d": {"trading_pnl": 6200.0}}}]}

        def wallet(self, w: str) -> None:
            return None

    class Search:  # uselayer 0.17's search_traders: Polymarket's own username search
        def search_traders(self, name: str, *, limit: int = 5) -> list[Trader]:
            searched.append(name)
            if name == "down":
                raise VenueError("http_error", "Polymarket didn't answer.", venue="polymarket")
            return on_polymarket

    monkeypatch.setattr(engine, "directory", lambda: Dir())
    monkeypatch.setattr(engine, "checker", lambda: Search())
    # nobody by that name on Polymarket: the directory's matches
    for text in ("northpaw", "https://polymarket.com/@northpaw", "@northpaw"):
        d = api.get("/api/find", params={"q": text}).json()
        assert d["wallet"] is None and d["results"] == [{"wallet": W, "name": "northpaw", "profit_30d": 6200.0}]
    assert asked == searched == ["northpaw"]  # kept: the same name isn't searched again
    assert api.get("/api/find", params={"q": "n"}).status_code == 400
    # Polymarket's usernames first, then the directory's, each wallet once (with the directory's profit)
    on_polymarket[:] = [Trader(venue="polymarket", id="0x" + "EE" * 20, name="NorthPaw"),
                        Trader(venue="polymarket", id=W, name="northpaw")]  # fmt: skip
    engine._cache.clear()
    d = api.get("/api/find", params={"q": "https://polymarket.com/@NorthPaw?tab=positions"}).json()
    assert d["results"] == [{"wallet": "0x" + "ee" * 20, "name": "NorthPaw", "profit_30d": None},
                            {"wallet": W, "name": "northpaw", "profit_30d": 6200.0}]  # fmt: skip
    assert searched[-1] == "NorthPaw"
    # Polymarket not answering: the directory's matches still show
    assert api.get("/api/find", params={"q": "down"}).json()["results"] == [{"wallet": W, "name": "northpaw", "profit_30d": 6200.0}]


def test_the_watchlist_is_yours_and_reads_nothing(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert api.get("/api/me/watchlist").status_code == 401
    other = "0x" + "ab" * 20
    for w in (W, other):
        assert api.post("/api/me/follows", json={"wallet": w}, headers=auth()).status_code == 200
    monkeypatch.setattr(engine, "checker", lambda: Reads(TRADES, POSITIONS))
    api.get(f"/api/watch/{W}")  # someone looked at W's watch page: the card knows what each move did
    from uselayer import Trader, TraderDetail

    engine._cache[f"live:{other}"] = (engine.time.monotonic(), TraderDetail(
        Trader(venue="polymarket", id=other, name="quietfox"), "visible", {}, [],
        [replace(fill(FED, "buy", 600, 0.4, 1 * H), trader=other, name="quietfox")]))  # fmt: skip
    monkeypatch.setattr(engine, "checker", lambda: pytest.fail("the Watchlist never reads"))
    r = api.get("/api/me/watchlist", headers=auth())
    assert r.headers["cache-control"] == "private, no-store"
    d = r.json()
    assert d["max"] == engine.MAX_FOLLOWS and [t["wallet"] for t in d["traders"]] == [W, other]
    mine, theirs = d["traders"]
    assert mine["name"] == "northpaw" and mine["moves"][0]["kind"] == "added" and mine["held"]["count"] == 3
    assert len(mine["moves"]) == engine.WATCH_CARD_MOVES
    assert theirs["name"] == "quietfox" and [m["kind"] for m in theirs["moves"]] == ["bought"] and theirs["held"] is None
    assert api.get("/api/me/watchlist", headers=auth(engine_token("user_2"))).json()["traders"] == []  # not yours


def engine_token(sub: str) -> str:
    from test_follow import token

    return token(sub)


# ---- the page ----

CARD = ("esc", "plural", "tenths", "cents", "usd", "pl", "ago", "ADDR", "SHORT_ADDR", "displayName", "hash32", "avatar",
        "WIN_MIN", "KIND", "SEEN_KEY", "seenVisit", "seenMap", "seenAt", "isNew", "winText", "wl", "wlCard")  # fmt: skip
EXPLAIN = ("esc", "plural", "tenths", "cents", "usd", "pl", "ago", "UNCATEGORISED", "KIND", "ordinal", "span", "wt",
           "moveHeadline", "moveFacts")  # fmt: skip


def js(value: Any) -> str:
    import json

    return json.dumps(value)


def test_a_watchlist_card_says_their_record_what_they_hold_and_their_latest_changes(run_js: Any) -> None:
    now = datetime.now(UTC)
    t = {"wallet": W, "name": "northpaw", "held": {"put_in": 38900, "worth": 40100, "count": 7},
         "record": {"win": {"won": 58, "closed": 100, "days": 90}, "paid_30d": 0.54, "typical_usd": 900, "profit_30d": 6200},
         "moves": [{"kind": "added", "usd": 2400, "title": "Lakers win the 2027 NBA title", "at": (now - 4 * M).isoformat()},
                   {"kind": "sold_some", "usd": 900, "title": "Chiefs beat the Bills", "at": (now - 3 * H).isoformat()}]}  # fmt: skip
    html = run_js(CARD, f"wlCard({js(t)}, 2)")
    for said in ("northpaw", "Win rate 58% (paid 54¢ on average)", "usual trade $900", "+$6.2K", "2 new", "$38.9K",
                 "worth $40.1K", "7 positions", "Bought more", "Sold some", "Lakers win the 2027 NBA title", "#/watch/" + W):  # fmt: skip
        assert said in html, said
    assert "0x7c" not in html.replace("#/watch/" + W, "")  # no wallet address on screen
    # a trader with no record read yet and no trades lately says so, never a "—"
    bare = run_js(CARD, f"wlCard({js({'wallet': W, 'name': None, 'held': None, 'record': None, 'moves': []})}, 0)")
    assert "Record not read yet" in bare and "No trades in the last 30 days yet." in bare and "—" not in bare


def test_a_change_is_explained_from_its_facts_only(run_js: Any) -> None:
    now = datetime.now(UTC)
    m = {"market": LAKERS, "kind": "added", "action": "buy", "usd": 2400, "price": 0.31, "fills": 3, "outcome": "Yes",
         "buy_count": 3, "opened_at": (now - 12 * D).isoformat(), "rising": True, "falling": False, "category": "Sports",
         "held_now": True, "now": 0.33, "at": now.isoformat(), "first_at": (now - 6 * M).isoformat()}  # fmt: skip
    ctx = {"d": {"holdings": [{"market": LAKERS, "put_in": 6100, "paid": 0.30, "value": 6710}]}, "s": {"typical_usd": 900},
           "cats": {"rows": [{"category": "Sports", "usd": 22100}, {"category": "Politics", "usd": -300}]}}  # fmt: skip
    head, facts = run_js(EXPLAIN, f"(Object.assign(wt, {js(ctx)}), [moveHeadline({js(m)}), moveFacts({js(m)})])")
    assert head == "Their 3rd buy of this in 12 days, each at a higher price"
    said = dict(facts)
    assert said["What they did"] == "Bought $2.4K of Yes at 31¢, in 3 trades"
    assert said["Their position now"] == "$6.1K put in at 30¢ · worth $6.7K"
    assert said["Size"] == "2.7× their usual trade of $900, last 30 days"
    assert "+$22.1K" in said["Their record in Sports"] and said["Their record in Sports"].endswith("their best category")
    assert said["Price now"] == "33¢ · they paid 30¢"
    # a sale below what they paid, and a move we can't place: said as it is, never guessed
    sold = m | {"kind": "closed", "action": "sell", "price": 0.51, "paid": 0.54, "held_now": False}
    assert run_js(EXPLAIN, f"moveHeadline({js(sold)})") == "Sold all of it, below what they paid"
    assert run_js(EXPLAIN, "moveHeadline({kind: 'bought'})") == "Bought"


def test_a_trader_in_one_category_still_shows_it_and_best_is_only_said_of_several(run_js: Any) -> None:
    names = ("esc", "plural", "tenths", "cents", "usd", "pl", "WIN_MIN", "winText", "profitOf", "UNCATEGORISED", "watchTiles")
    d = {"put_in": 164800, "worth": 170000}
    one = {"rows": [{"category": "Sports", "usd": 361605.8}]}
    tiles = run_js(names, f"watchTiles({js(d)}, null, {js(one)})")
    assert tiles[-1][:2] == ["Category", "Sports"] and "+$362K" in tiles[-1][2]
    several = {"rows": [{"category": "Sports", "usd": 2000}, {"category": "Politics", "usd": 14100},
                        {"category": "Uncategorised", "usd": 99999}]}  # fmt: skip
    assert run_js(names, f"watchTiles({js(d)}, null, {js(several)})")[-1][:2] == ["Best category", "Politics"]
    lost = {"rows": [{"category": "Sports", "usd": -500}, {"category": "Politics", "usd": -100}]}
    assert run_js(names, f"watchTiles({js(d)}, null, {js(lost)})")[-1][0] == "Holding now"  # no "best" of losses
