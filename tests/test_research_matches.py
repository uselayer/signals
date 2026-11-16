"""Breakdowns of Premier League match markets: the live score from Layer's recording (signals/research/scores.py),
the score line on a match replay, each fill's match context and the counts (workspace), match markets in a
Premier League scope whatever min_days says, and the page's match helpers (marketdata.js)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
import subprocess
from pathlib import Path
from typing import Any

import brotli
import pytest

from signals.research import data as D
from signals.research import markets as M
from signals.research import scores as S
from signals.research import workspace
from tests.test_research_markets import EPL_TAGS, MATCH_RULES, W, Binance, Poly, Whales, _act, _store_with_wallet

KO = int(datetime(2026, 11, 21, 15, 0, tzinfo=UTC).timestamp())  # Saturday 3 pm, after the recording began
GAME = 90_114_999
SLUG = "epl-ars-che-2026-11-21-ars"
CID = "0x" + "77" * 32


def _u(t: float, score: str, minute: int | None, period: str, **kw: Any) -> tuple[float, dict[str, Any]]:
    return t, {"gameId": GAME, "leagueAbbreviation": "epl", "homeTeam": "Arsenal FC", "awayTeam": "Chelsea FC",
               "status": "InProgress", "score": score, "elapsed": "" if minute is None else str(minute),
               "period": period, "live": True, "ended": False, **kw}  # fmt: skip


def _match_read() -> dict[str, Any]:
    """Arsenal 1-2 Chelsea as the feed says it: Chelsea score in the 10th and the 50th minute, Arsenal's 60th-minute
    goal is taken back half a minute later and given again in the 62nd, a reconnect gap in the 70th."""
    ups = [_u(KO + 60, "0-0", 1, "1H"), _u(KO + 600, "0-0", 10, "1H"), _u(KO + 615, "0-1", 10, "1H"),
           _u(KO + 2700, "0-1", 45, "1H"), _u(KO + 2900, "0-1", None, "HT", status="Break"),
           _u(KO + 3900, "0-1", 46, "2H"), _u(KO + 6000 - 1200, "0-1", 50, "2H"), _u(KO + 4830, "0-2", 50, "2H"),
           _u(KO + 5400, "1-2", 60, "2H"), _u(KO + 5430, "0-2", 60, "2H"), _u(KO + 5520, "1-2", 62, "2H"),
           _u(KO + 6000, "1-2", 70, "2H"), _u(KO + 7300, "1-2", None, "FT", status="Final", live=False, ended=True)]
    return {"game_id": GAME, "updates": sorted(ups, key=lambda x: x[0]), "spans": [(KO - 3600, KO + 9000)],
            "gaps": [(KO + 6100, KO + 6160, "The recorder's connection dropped and reconnected")],
            "recorded_from": S.SCORES_FROM}  # fmt: skip


def test_the_score_line_has_its_goals_halves_and_a_goal_the_feed_took_back() -> None:
    line = S.match_line(_match_read(), kickoff=KO, start=KO - 3600, end=KO + 4 * 3600)
    assert (line["home"], line["away"], line["league"]) == ("Arsenal FC", "Chelsea FC", "epl")
    g = line["goals"]
    assert [(x["score"], x["minute"], x["by"], x["kind"]) for x in g] == [
        ("0-1", 10, "away", "goal"), ("0-2", 50, "away", "goal"), ("1-2", 60, "home", "goal"),
        ("0-2", 60, None, "correction"), ("1-2", 62, "home", "goal")]  # fmt: skip
    assert g[2]["retracted"] and g[3]["undoes"] == "1-2" and g[4]["reinstated"] and g[4]["first_said"] == KO + 5400
    assert g[0]["since_previous_update_s"] == 15  # a goal is its own update between the clock's
    assert line["coverage"]["goals"] == 3 and line["coverage"]["corrections"] == 1 and line["coverage"]["gap_s"] == 60
    assert [p["period"] for p in line["periods"]] == ["1H", "HT", "2H", "FT"]
    assert line["periods"][1]["from"] == KO + 2900 and line["periods"][1]["to"] == KO + 3900
    assert line["final"] == {"score": "1-2", "t": KO + 7300} and line["first_live_update"] == KO + 60
    at = lambda t: S.state_at(line, t)  # noqa: E731
    assert at(KO - 600)["phase"] == "pre_kickoff" and at(KO - 600)["score"] == "0-0"
    assert at(KO + 640)["since_goal_s"] == 25 and at(KO + 640)["score"] == "0-1"
    assert at(KO + 3000)["phase"] == "half_time" and at(KO + 7400)["phase"] == "after_full_time"
    # right after the feed took the goal back nothing counts as "after a goal"; the reinstated one counts from again
    assert at(KO + 5440)["since_goal_s"] is None and at(KO + 5440)["after_correction_s"] == 10
    assert at(KO + 5530)["since_goal_s"] == 10 and at(KO + 6120)["in_gap"]


def test_a_match_before_the_recording_or_without_a_read_says_why() -> None:
    old = S.match_line(None, kickoff=S.SCORES_FROM - 86_400, start=S.SCORES_FROM - 90_000, end=S.SCORES_FROM - 70_000)
    assert not old["coverage"]["recorded"] and "11 Nov 2026 at 18:26 UTC" in old["coverage"]["why"]
    none = S.match_line(None, kickoff=KO, start=KO - 3600, end=KO + 3600)
    assert not none["coverage"]["recorded"] and "couldn't be read" in none["coverage"]["why"]
    assert S.state_at(none, KO - 10)["phase"] == "pre_kickoff" and S.state_at(none, KO + 10)["phase"] == "unknown"
    assert S.parse_score("000-000|0-1|Bo3") is None and S.parse_score("2-1") == (2, 1)


class R2:
    """Two recorded files: the first with a reconnect gap and a 20-second stall in its heartbeats, the second
    starting two minutes after the first ends (the recorder was down)."""

    def __init__(self) -> None:
        a, b = KO, KO + 600 + 120
        self.files = {
            f"raw/ticks/sports/2026/11/21/polymarket-sports-ws-2026-11-21T15-{a * 1000}.jsonl.br": [
                {"t": a * 1000, "ev": "file"}, {"ev": "hb", "t": (a + 1) * 1000, "last": None},
                {"t": (a + 30) * 1000, "c": "sp1", "m": _u(0, "0-0", 1, "1H")[1]},
                {"t": (a + 31) * 1000, "c": "sp1", "m": {**_u(0, "3-1", None, "Q2")[1], "gameId": 1}},
                {"ev": "hb", "t": (a + 2) * 1000, "last": None}, {"ev": "hb", "t": (a + 22) * 1000, "last": None},
                {"t": (a + 300) * 1000, "c": "sp2", "ev": "gap", "ms": 9000},
                {"t": (a + 301) * 1000, "c": "sp2", "ev": "gap", "ms": 1200},  # too short to draw
                {"t": (a + 600) * 1000, "c": "sp2", "m": _u(0, "0-1", 10, "1H")[1]}],
            f"raw/ticks/sports/2026/11/21/polymarket-sports-ws-2026-11-21T15-{b * 1000}.jsonl.br": [
                {"t": b * 1000, "ev": "file"}, {"t": (b + 60) * 1000, "c": "sp3", "m": _u(0, "0-1", 13, "1H")[1]}],
            "raw/ticks/sports/2026/11/21/not-a-sports-file.txt": [],
        }  # fmt: skip
        self.gets = 0

    def keys(self, prefix: str, limit: int = 100) -> list[str]:
        return [k for k in self.files if k.startswith(prefix)]

    def get(self, key: str) -> bytes:
        self.gets += 1
        lines = [json.dumps(x, separators=(",", ":")) for x in self.files[key]]
        return brotli.compress("\n".join(lines).encode())


def test_recorded_files_give_one_games_updates_and_every_gap_with_why(monkeypatch: pytest.MonkeyPatch) -> None:
    r2 = R2()
    read = S.reader(r2)
    got = read(GAME, KO - 60, KO + 900)
    assert [(round(t - KO), m["score"]) for t, m in got["updates"]] == [(30, "0-0"), (600, "0-1"), (780, "0-1")]
    why = {(round(a - KO), round(b - KO)): w for a, b, w in got["gaps"]}
    assert why[(2, 22)] == "The recorder stalled" and why[(291, 300)].startswith("The recorder's connection dropped")
    assert why[(600, 720)].startswith("Nothing was recorded here") and why[(-60, 0)].startswith("Nothing was recorded")
    assert len(why) == 4  # the 1.2-second reconnect isn't drawn
    read(GAME, KO, KO + 900)
    assert r2.gets == 2  # each file is decoded once


def _match_market() -> dict[str, Any]:
    return {"slug": SLUG, "conditionId": CID, "question": "Will Arsenal FC win on 2026-11-21?", "description": MATCH_RULES,
            "outcomes": '["Yes", "No"]', "clobTokenIds": '["tY", "tN"]', "outcomePrices": '["0", "1"]', "closed": True,
            "closedTime": "2026-11-21 17:30:00+00", "negRisk": True, "groupItemTitle": "Arsenal FC", "tags": EPL_TAGS,
            "startDate": "2026-11-14T15:30:00Z", "endDate": "2026-11-21T15:00:00Z", "gameStartTime": "2026-11-21 15:00:00+00",
            "sportsMarketType": "moneyline",
            "events": [{"slug": "epl-ars-che-2026-11-21", "title": "Arsenal FC vs. Chelsea FC", "gameId": GAME}]}  # fmt: skip


class MatchPoly(Poly):
    def __init__(self) -> None:
        super().__init__()
        self.market = _match_market()
        f = lambda t, a, o, p, n, tx: _act(t, a, o, p, n, tx) | {"conditionId": CID, "slug": SLUG}  # noqa: E731
        self.fills = [f(KO - 2 * 86_400, "buy", "Yes", 0.5, 100, "0x1"),  # two days before kickoff
                      f(KO + 640, "buy", "Yes", 0.3, 200, "0x2"),  # 25 s after Chelsea's first goal, Arsenal behind
                      f(KO + 3000, "buy", "Yes", 0.25, 40, "0x3"),  # half-time
                      f(KO + 4850, "buy", "No", 0.9, 50, "0x4"),  # 20 s after the second goal: not Arsenal
                      f(KO + 6800, "sell", "Yes", 0.1, 100, "0x5")]  # before full time

    def _pages(self, path: str, params: dict[str, Any], limit: int, offset: int, page: int) -> list[dict[str, Any]]:
        return []


def test_a_match_replay_draws_the_score_and_puts_the_match_on_every_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "now", lambda: KO + 2 * 86_400)
    monkeypatch.setattr(workspace, "now", lambda: KO + 2 * 86_400)
    store, sid = _store_with_wallet()
    asked: list[tuple[int, float, float]] = []
    whales = Whales()
    whales._poly = MatchPoly()
    reads = D.Reads(whales, Binance(), scores=lambda g, a, b: asked.append((g, a, b)) or _match_read())  # type: ignore[arg-type]
    r = workspace.build(store, reads, sid, SLUG)
    assert r["market_type"] == "soccer" and r["rule"]["kind"] == "match" and asked[0][0] == GAME
    m = r["match"]
    assert m["side"] == "home" and m["home"] == "Arsenal FC" and m["final"]["score"] == "1-2"
    assert m["axis"]["from"] == KO - 600 and m["axis"]["to"] == KO + 7300 + 600
    ctx = {f["t"] - KO: f["match"] for f in r["trades"]}
    assert ctx[-2 * 86_400]["phase"] == "pre_kickoff" and ctx[-2 * 86_400]["backs"] == "home"
    assert ctx[640] == {"phase": "in_play", "minute": 10, "period": "1H", "score": "0-1", "since_goal_s": 25,
                             "last_goal_by": "away", "in_gap": False, "backs": "home", "margin": -1}  # fmt: skip
    assert ctx[3000]["phase"] == "half_time" and ctx[4850]["backs"] == "not_home" and ctx[4850]["margin"] is None
    c = m["counts"]
    assert c["buys_pre_kickoff"]["fills"] == 1 and c["buys_in_play"]["fills"] == 2 and c["buys_half_time"]["fills"] == 1
    assert c["buys_within_60s_after_goal"] == {"fills": 2, "usd": 105.0} and c["buys_backing_side_behind"]["fills"] == 2
    assert c["sells_before_full_time"]["fills"] == 1 and c["fills_within_60s_of_a_goal"] == 2
    # the match itself at 1 minute, though the replay's span (two days and more) is read every 15 minutes
    cov = r["coverage"]
    assert cov["price_step_s"] == 900 and cov["match_price_step_s"] == 60
    inside = [p["t"] for p in r["prices"]["Yes"] if m["axis"]["from"] <= p["t"] <= KO + 7300]
    assert max(b - a for a, b in zip(inside, inside[1:], strict=False)) == 60
    notes = " ".join(cov["notes"])
    assert "live sports feed (13 updates" in notes and "1 gap during the match (60 s in all)" in notes
    assert "took back a score 1 time" in notes and "2 of its fills came within a minute of a goal" in notes
    assert cov["score"]["goals"] == 3 and cov["outside_none"] is None
    tile = store.summaries(sid)[0]
    assert tile["match"]["final"]["score"] == "1-2" and tile["entries"][1]["match"]["margin"] == -1
    # kept: a finished match isn't read again
    workspace.build(store, reads, sid, SLUG)
    assert len(asked) == 1


def test_match_markets_are_tiled_whatever_min_days_says(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = D.Reads(Whales(), Binance())  # type: ignore[arg-type]
    match = _match_market() | {"conditionId": CID}  # listed a week before kickoff: 6.7 days
    future = match | {"slug": "will-arsenal-be-relegated-short", "conditionId": "0x" + "78" * 32, "gameStartTime": None,
                      "question": "Will Arsenal win the 2026-27 English Premier League (EPL) Championship?",
                      "description": "Premier League at the end of the season.", "events": [{"slug": "x"}]}  # fmt: skip
    rows = [{"ts": KO, "slug": g["slug"], "condition_id": g["conditionId"], "usd": 100.0, "action": "buy", "outcome": "Yes"}
            for g in (match, future)]  # fmt: skip
    monkeypatch.setattr(reads, "_newest_trades", lambda w, a, b: {"trades": rows, "count": 2, "start": a, "complete": True,
                                                                   "read_to": b, "source": "s", "note": ""})  # fmt: skip
    monkeypatch.setattr(reads, "markets_facts", lambda ids: {g["conditionId"]: D.market_facts(g) for g in (match, future)})
    got = reads.wallet_markets(W, KO - 30 * 86_400, KO + 86_400, "premier-league")
    assert [x["slug"] for x in got["markets"]] == [SLUG]  # the short future stays out; the match is in
    assert got["markets"][0]["game_id"] == GAME and got["markets"][0]["kickoff_iso"].startswith("2026-11-21T15:00")
    assert M.SOCCER.score_line and M.premier_league_is_match(D.market_facts(match))
    assert workspace.match_side(SLUG) == "home" and workspace.match_side("epl-ars-che-2026-11-21-che") == "away"
    assert workspace.match_side("epl-ars-che-2026-11-21-draw") == "draw"
    assert workspace.match_side("epl-ars-che-2026-11-21-total-2pt5") is None


def test_the_page_groups_fills_in_a_match_by_the_minute_and_words_the_score() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    js = (Path(__file__).resolve().parent.parent / "signals" / "research" / "static" / "js" / "marketdata.js").as_uri()
    r = {"kind": "market", "window_id": SLUG, "outcomes": ["Yes", "No"], "prices": {"Yes": [], "No": []},
         "axis": {"from": KO - 86_400, "to": KO + 9000}, "position": [], "value": {},
         "trades": [{"trade_id": "a", "t": KO + 640, "side": "Yes", "action": "buy", "shares": 10, "price": 0.3, "usd": 3,
                     "match": {"phase": "in_play", "minute": 10, "score": "0-1", "since_goal_s": 25, "in_gap": False}},
                    {"trade_id": "b", "t": KO + 760, "side": "Yes", "action": "buy", "shares": 10, "price": 0.3, "usd": 3,
                     "match": {"phase": "in_play", "minute": 12, "score": "0-1", "since_goal_s": 145, "in_gap": False}},
                    {"trade_id": "c", "t": KO - 86_000, "side": "Yes", "action": "buy", "shares": 1, "price": 0.5, "usd": 0.5,
                     "match": {"phase": "pre_kickoff"}},
                    {"trade_id": "d", "t": KO - 85_000, "side": "Yes", "action": "buy", "shares": 1, "price": 0.5, "usd": 0.5,
                     "match": {"phase": "pre_kickoff"}}],
         "match": {"home": "Arsenal FC", "away": "Chelsea FC", "axis": {"from": KO - 600, "to": KO + 7900},
                   "clock": [{"t": KO + 60, "minute": 1, "period": "1H", "score": "0-0"},
                             {"t": KO + 615, "minute": 10, "period": "1H", "score": "0-1"}],
                   "goals": [{"t": KO + 5400, "minute": 60, "score": "1-2", "kind": "goal", "retracted": True}],
                   "coverage": {"recorded": True, "updates": 2}}}  # fmt: skip
    code = (f"import {{ prepMarket, matchText, goalLabel }} from '{js}';\n"
            f"const w = prepMarket({json.dumps(r)}, null);\n"
            "console.log(JSON.stringify({bursts: w.bursts.map(b => b.fills.length), at: w.scoreAt(" + str(KO + 700) + "),"
            " before: w.scoreAt(" + str(KO) + "), text: w.trades.map(matchText), goal: goalLabel(w.match.goals[0])}));")
    out = json.loads(subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30,
                                     check=True).stdout)  # fmt: skip
    # two minutes apart in the match: two marks; 1,000 s apart the day before: one (an hour's grouping)
    assert out["bursts"] == [2, 1, 1]
    assert out["at"] == {"minute": 10, "period": "1H", "score": "0-1"} and out["before"] is None
    assert out["text"] == ["Before kick-off", "Before kick-off", "10' · 0–1 · 25 s after a goal", "12' · 0–1 · 2 min after a goal"]
    assert out["goal"] == "1–2 60', taken back"


def test_a_wallet_too_busy_for_a_weeks_read_is_read_a_day_at_a_time_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """16 Nov: an in-play sports wallet made over 30,000 fills a week, so its newest week was never whole and a
    Premier League scope read nothing at all; a smaller step from the same newest end reads its latest days."""
    reads = D.Reads(Whales(), Binance())  # type: ignore[arg-type]
    asked: list[tuple[int, int]] = []

    def wallet_trades(w: str, lo: int, hi: int, prefix: Any) -> dict[str, Any]:
        asked.append((lo, hi))
        whole = hi - lo <= 86_400
        return {"trades": [{"ts": hi - 10, "slug": SLUG}] if whole else [], "complete": whole}

    monkeypatch.setattr(reads, "wallet_trades", wallet_trades)
    got = reads._newest_trades(W, KO - 3 * 86_400, KO)
    assert asked[0] == (KO - 3 * 86_400, KO) and asked[1] == (KO - 86_400, KO)  # the week, then a day from the end
    assert got["complete"] and got["count"] == 3 and got["start"] == KO - 3 * 86_400


# ---- every soccer league (session 5, 16 Nov: "the Premier League is a league, soccer is the sport") ----

UNL_GAME = 90_108_450
UNL_SLUG = "unl-esp-eng-2026-11-15-eng"


def _unl_market(**kw: Any) -> dict[str, Any]:
    """England to win at Spain in the Nations League, as Gamma lists it: the Soccer tag and the league's own, no
    EPL tag, the gameId on its event and the league in the event's series."""
    return {"slug": UNL_SLUG, "conditionId": "0x" + "91" * 32, "question": "Will England win on 2026-11-15?",
            "description": "In the upcoming game, scheduled for November 15, 2026 at 7:45 PM GMT: If England wins, "
                           "this market will resolve to \"Yes\". Otherwise, this market will resolve to \"No\".",
            "outcomes": '["Yes", "No"]', "clobTokenIds": '["uY", "uN"]', "closed": True, "negRisk": True,
            "groupItemTitle": "England", "startDate": "2026-11-08T19:45:00Z", "endDate": "2026-11-15T19:45:00Z",
            "gameStartTime": "2026-11-15 19:45:00+00", "sportsMarketType": "moneyline",
            "tags": [{"label": "Sports"}, {"label": "Games"}, {"label": "Soccer"}, {"label": "UEFA Nations League"}],
            "events": [{"slug": "unl-esp-eng-2026-11-15", "title": "Spain vs. England", "gameId": UNL_GAME,
                        "series": [{"slug": "soccer-unl", "title": "UEFA Nations League"}]}]} | kw  # fmt: skip


def test_any_leagues_soccer_match_is_soccer_and_names_its_league() -> None:
    f = D.market_facts(_unl_market())
    assert f["game_id"] == UNL_GAME and f["series_title"] == "UEFA Nations League"
    assert M.of_market(UNL_SLUG, f) is M.SOCCER and M.soccer_is_match(f) and not M.premier_league_matches(UNL_SLUG, f)
    assert M.soccer_league(f) == "UEFA Nations League" and M.SOCCER.rule(f)["kind"] == "match"
    # the series' year is dropped; without a series, the league's own tag names it
    assert M.soccer_league(f | {"series_title": "La Liga 2 2026"}) == "La Liga 2"
    assert M.soccer_league(f | {"series_title": None}) == "UEFA Nations League"
    # the Premier League's markets say so, whatever Gamma's series is called
    assert M.soccer_league(D.market_facts(_match_market())) == "Premier League"
    # its slug is read first in a busy wallet; another sport's game isn't
    assert M.soccer_hint(UNL_SLUG) and M.soccer_hint("es2-leg-bur-2026-11-13-leg") and M.soccer_hint("epl-ars-che-2026-11-21")
    assert not M.soccer_hint("nba-was-ind-2026-11-11") and not M.soccer_hint("ufc-ale14-die4-2026-01-31")


def test_another_sports_game_or_a_soccer_season_market_isnt_a_soccer_tile() -> None:
    nba = D.market_facts(_unl_market(slug="nba-was-ind-2026-11-11", tags=[{"label": "Sports"}, {"label": "NBA"},
                                                                          {"label": "Basketball"}]))  # fmt: skip
    esports = D.market_facts(_unl_market(slug="lol-t1-hle-2026-11-11", tags=[{"label": "Esports"}, {"label": "Games"}]))
    assert nba["game_id"] and not M.soccer_matches(nba["slug"], nba) and not M.soccer_near(nba)
    assert not M.soccer_matches(esports["slug"], esports) and M.of_market(nba["slug"], nba) is None
    # another league's season market (no game): soccer, read and left out, never a tile
    ucl = D.market_facts(_unl_market(slug="will-arsenal-win-the-2026-27-champions-league", events=[{"slug": "ucl-2027"}],
                                     question="Will Arsenal win the 2026-27 Champions League?", gameStartTime=None,
                                     tags=[{"label": "Soccer"}, {"label": "Sports"}, {"label": "UCL"}]))  # fmt: skip
    assert not M.soccer_matches(ucl["slug"], ucl) and M.soccer_near(ucl)


def test_a_saved_premier_league_breakdown_still_opens_as_soccer() -> None:
    # plans, saved breakdowns and links from before soccer name premier-league: the same type, its markets all in it
    for old in ("premier-league", "epl", "Premier-League"):
        assert M.by_id(old) is M.SOCCER and M.of_scope({"market_type": old}) is M.SOCCER
    t = next(x for x in M.described() if x["id"] == "soccer")
    assert t["label"] == "Soccer" and "premier-league" in t["aliases"]  # the page opens ?market=premier-league as Soccer
    assert "premier-league" not in [x["id"] for x in M.described()]  # one Market pill, not two


def test_a_soccer_scope_tiles_every_leagues_matches_and_counts_the_season_markets_left_out(
        monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    reads = D.Reads(Whales(), Binance())  # type: ignore[arg-type]
    epl = _match_market()
    unl = _unl_market()
    nba = _unl_market(slug="nba-was-ind-2026-11-11", conditionId="0x" + "92" * 32,
                      tags=[{"label": "Sports"}, {"label": "NBA"}])  # fmt: skip
    ucl = _unl_market(slug="will-arsenal-win-the-2026-27-champions-league", conditionId="0x" + "93" * 32,
                      events=[{"slug": "ucl-2027"}], gameStartTime=None, endDate="2027-06-01T00:00:00Z",
                      tags=[{"label": "Soccer"}, {"label": "UCL"}])  # fmt: skip
    usd = {epl["conditionId"]: 100.0, unl["conditionId"]: 400.0, nba["conditionId"]: 900.0, ucl["conditionId"]: 250.5}
    gs = (epl, unl, nba, ucl)
    rows = [{"ts": KO, "slug": g["slug"], "condition_id": g["conditionId"], "usd": usd[g["conditionId"]],
             "action": "buy", "outcome": "Yes"} for g in gs]  # fmt: skip
    monkeypatch.setattr(reads, "_newest_trades", lambda w, a, b: {"trades": rows, "count": len(rows), "start": a,
                                                                   "complete": True, "read_to": b, "source": "s", "note": ""})
    monkeypatch.setattr(reads, "markets_facts", lambda ids: {g["conditionId"]: D.market_facts(g) for g in gs})
    got = reads.wallet_markets(W, KO - 30 * 86_400, KO + 86_400, "soccer")
    assert [(x["slug"], x["league"]) for x in got["markets"]] == [(UNL_SLUG, "UEFA Nations League"),
                                                                  (SLUG, "Premier League")]  # the most money first
    assert all(x["game_id"] for x in got["markets"])
    assert got["near_left_out"]["markets"] == 1 and got["near_left_out"]["usd_in_range"] == 250.5
    assert "1 soccer markets read weren't matches or the Premier League's ($250.50 traded" in got["note"]
    assert got["not_this_type"] == 2  # the NBA game and the Champions League winner


def test_a_soccer_match_replay_and_tile_name_the_league() -> None:
    reads = D.Reads(Whales(), Binance())  # type: ignore[arg-type]
    poly = MatchPoly()
    poly.market = _unl_market() | {"outcomePrices": '["1", "0"]', "closedTime": "2026-11-15 21:45:00+00"}
    reads.whales._poly = poly
    reads.scores = lambda g, a, b: None
    store, sid = _store_with_wallet()
    r = workspace.build(store, reads, sid, UNL_SLUG)
    assert r["market_type"] == "soccer" and r["league"] == "UEFA Nations League" and r["rule"]["kind"] == "match"
    assert store.summaries(sid)[0]["league"] == "UEFA Nations League"
