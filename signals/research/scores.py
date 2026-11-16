"""A match's live score from Layer's recording of polymarket.com's sports feed (layer#673, docs/tick-recorder.md
there, "Sports scores"), and the score line a match replay draws from it.

The files: ``layer-history/raw/ticks/sports/YYYY/MM/DD/polymarket-sports-ws-<hour>-<start ms>.jsonl.br`` (brotli
JSONL, a file every 10 minutes, every game Polymarket runs live in one stream). A line is
``{"t": <receive ms>, "c": "sp1", "m": {"gameId", "leagueAbbreviation", "homeTeam", "awayTeam", "status", "score",
"elapsed", "period", "live", "ended"}}``, a recorder note (``"ev"``: ``gap`` with ``ms``, ``open``, ``close``,
``file``…) or a heartbeat (``{"ev":"hb",…}``, once a second, the only line not starting ``{"t":``). ``gameId`` is the
Gamma event's ``gameId``: that's how a match joins its markets. Recorded from 2026-11-11 18:26 UTC; the feed has no
history, so nothing earlier exists anywhere.

Soccer, as recorded (checked 15 Nov on Nations League and English League One/Two files; the Premier League had no
match in the first days, an international break): ``score`` "home-away" ("0-1"), ``elapsed`` the minute as a whole
number ("67"; empty at half-time and full time), ``period`` 1H, HT, 2H, FT (then VFT, the result confirmed), POST
(postponed); about one update a minute (the clock), and a score change as its own update, between them. The feed
sends updates, never a snapshot on connecting: after a gap a match's state is known again only from its next update.
Polymarket says the feed can be late, wrong or miss events, so a goal's time here is when the feed said so.

Everything here is read by the server and handed over as data; the model never builds a series.
"""

from __future__ import annotations

import bisect
import json
import re
import threading
from datetime import UTC, datetime
from typing import Any

import brotli
import httpx

SCORES_FROM = 1_794_421_560  # 2026-11-11 18:26 UTC: Layer's first recorded sports file
PREFIX = "raw/ticks/sports"
FILE = re.compile(r"polymarket-sports-ws-\d{4}-\d{2}-\d{2}T\d{2}-(\d{13})\.jsonl\.br$")
FILE_S = 600  # a file every 10 minutes (and one on each restart)
KEPT = 96  # decoded files kept in memory (a matchweek's matches share them)
HB_STALL_S = 15  # heartbeats missing this long inside a file: the recorder itself stalled
BETWEEN_FILES_S = 30  # more than this between one file's last line and the next one's first: the recorder was down
GAP_MIN_S = 5  # a reconnect shorter than this isn't worth drawing
SOCCER = {"1H", "HT", "2H", "FT", "VFT", "ET1", "ET2", "ETHT", "AET", "PEN", "POST"}
IN_PLAY = {"1H", "2H", "ET1", "ET2"}
BREAK = {"HT", "ETHT"}
ENDED = {"FT", "VFT", "AET", "PEN"}
PERIOD_WORD = {"1H": "first half", "HT": "half-time", "2H": "second half", "ET1": "extra time, first half",
               "ETHT": "extra-time break", "ET2": "extra time, second half", "PEN": "penalties", "FT": "full time",
               "VFT": "full time", "AET": "after extra time", "POST": "postponed"}  # fmt: skip


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y/%m/%d")


class RawScores:
    """Reads one game's updates out of the recorded files, with the spans the recording didn't cover."""

    def __init__(self, r2: Any) -> None:
        self.r2 = r2
        self._files: dict[str, dict[str, Any]] = {}
        self._keys: dict[str, tuple[float, list[str]]] = {}
        self._lock = threading.Lock()

    def _day_keys(self, day: str, fresh: bool) -> list[str]:
        with self._lock:
            got = self._keys.get(day)
            if got and (not fresh or datetime.now(UTC).timestamp() - got[0] < 120):
                return got[1]
        keys = [k for k in self.r2.keys(f"{PREFIX}/{day}/", 1000) if FILE.search(k)]
        with self._lock:
            self._keys[day] = (datetime.now(UTC).timestamp(), keys)
        return keys

    def _file(self, key: str) -> dict[str, Any]:
        """One file, decoded once: every game's updates (seconds, the message), the reconnect gaps, the heartbeat
        stalls and the span its lines cover."""
        with self._lock:
            if key in self._files:
                return self._files[key]
        games: dict[int, list[tuple[float, dict[str, Any]]]] = {}
        gaps: list[tuple[float, float, str]] = []
        first = last = None
        hb_prev = None
        body = self.r2.get(key) or b""
        for line in brotli.decompress(body).decode(errors="replace").splitlines() if body else []:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            t = e.get("t")
            if not isinstance(t, (int, float)):
                continue
            s = t / 1000
            first = s if first is None else min(first, s)
            last = s if last is None else max(last, s)
            if e.get("ev") == "hb":
                if hb_prev is not None and s - hb_prev >= HB_STALL_S:
                    gaps.append((hb_prev, s, "The recorder stalled"))
                hb_prev = s
                continue
            if e.get("ev") == "gap" and e.get("ms"):
                ms = float(e["ms"])
                if ms >= GAP_MIN_S * 1000:
                    gaps.append((s - ms / 1000, s, "The recorder's connection dropped and reconnected"))
                continue
            m = e.get("m")
            if isinstance(m, dict) and m.get("gameId") is not None:
                try:
                    gid = int(m["gameId"])
                except (TypeError, ValueError):
                    continue
                games.setdefault(gid, []).append((s, m))
        out = {"games": games, "gaps": gaps, "first": first, "last": last}
        with self._lock:
            self._files[key] = out
            while len(self._files) > KEPT:
                self._files.pop(next(iter(self._files)))
        return out

    def game(self, game_id: int, start: float, end: float) -> dict[str, Any]:
        """``game_id``'s updates from ``start`` to ``end`` (unix seconds), oldest first, and what the recording
        covered: ``spans`` (each file's first to last line), ``gaps`` (reconnects, stalls and time between files,
        with why), ``recorded_from`` (SCORES_FROM)."""
        a, b = max(float(start), SCORES_FROM - FILE_S), float(end)
        days = sorted({_day(t) for t in (a - FILE_S, b)} | {_day(t) for t in range(int(a), int(b), 86_400)})
        recent = b > datetime.now(UTC).timestamp() - 2 * FILE_S
        files = []
        for day in days:
            for key in self._day_keys(day, recent):
                m = FILE.search(key)
                at = int(m.group(1)) / 1000 if m else None
                if at is not None and a - 2 * FILE_S <= at <= b:
                    files.append((at, key))
        ups: list[tuple[float, dict[str, Any]]] = []
        spans: list[tuple[float, float]] = []
        gaps: list[tuple[float, float, str]] = []
        for _at, key in sorted(files):
            f = self._file(key)
            if f["first"] is None:
                continue
            spans.append((f["first"], f["last"]))
            gaps += [g for g in f["gaps"] if g[1] >= a and g[0] <= b]
            ups += [(s, m) for s, m in f["games"].get(int(game_id), []) if a <= s <= b]
        spans.sort()
        # the recorder down: before the first file, between files, after the last (up to now)
        edge = max(a, SCORES_FROM)
        for lo, hi in spans:
            if lo - edge > BETWEEN_FILES_S and hi >= a:
                gaps.append((edge, min(lo, b), "Nothing was recorded here (the recorder was down)"))
            edge = max(edge, hi)
        stop = min(b, datetime.now(UTC).timestamp())
        if stop - edge > BETWEEN_FILES_S and edge < b:
            gaps.append((edge, stop, "Nothing was recorded here (the recorder was down)"))
        ups.sort(key=lambda x: x[0])
        return {"game_id": int(game_id), "updates": ups, "gaps": sorted(g for g in gaps if g[1] > g[0]),
                "spans": spans, "recorded_from": SCORES_FROM, "files": len(files)}


def reader(r2: Any) -> Any:
    """``Reads``' ``scores(game_id, start, end)``: Layer's recording, or None without a token or when unreadable."""
    if r2 is None:
        return lambda game_id, start, end: None
    raw = RawScores(r2)

    def read(game_id: int, start: float, end: float) -> dict[str, Any] | None:
        try:
            return raw.game(game_id, start, end)
        except (httpx.HTTPError, brotli.error) as e:
            print(f"research: recorded scores for game {game_id} unreadable: {type(e).__name__}", flush=True)
            return None

    return read


# ---- the score line: goals, periods and the clock, from the updates ----


def parse_score(s: Any) -> tuple[int, int] | None:
    """"2-1" → (2, 1); anything else (an esports or tennis score) → None."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", str(s or ""))
    return (int(m[1]), int(m[2])) if m else None


def _minute(m: dict[str, Any]) -> int | None:
    e = str(m.get("elapsed") or "").split(":")[0]
    return int(e) if e.isdigit() else None


def _in_gap(gaps: list[dict[str, Any]], a: float, b: float) -> bool:
    return any(g["from"] < b and a < g["to"] for g in gaps)


def match_line(read: dict[str, Any] | None, *, kickoff: float | None, start: float, end: float) -> dict[str, Any]:
    """The score line of one match for a replay from ``start`` to ``end``: ``goals`` (each score change: when the
    feed said so, the minute, the score after, which side, and whether a recording gap came just before it, so its
    time is only known to fall in that gap), ``periods`` (first half, half-time, second half… from the first update
    in each to the first of the next), ``clock`` (every update: time, minute, period, score), ``final``, and
    ``coverage`` (recorded or not, gaps, how many updates)."""
    gaps = [{"from": round(a, 1), "to": round(b, 1), "why": why} for a, b, why in (read or {}).get("gaps") or []]
    not_recorded = end < SCORES_FROM
    cov: dict[str, Any] = {"source": "Layer's recording of polymarket.com's live sports feed", "recorded_from": SCORES_FROM,
                           "recorded": bool(read) and not not_recorded, "updates": 0, "gaps": gaps,
                           "gap_s": round(sum(min(g["to"], end) - max(g["from"], start) for g in gaps
                                              if g["to"] > start and g["from"] < end), 1)}  # fmt: skip
    if not_recorded:
        cov["why"] = ("Layer began recording live scores on 11 Nov 2026 at 18:26 UTC; this match was before that, and "
                      "the feed keeps no history.")  # fmt: skip
    elif read is None:
        cov["why"] = "The recorded scores couldn't be read (no recording token here, or the files were unreadable)."
    ups = [(s, m) for s, m in (read or {}).get("updates") or [] if start <= s <= end]
    cov["updates"] = len(ups)
    if read is not None and not not_recorded and not ups:
        cov["why"] = ("The recording has no update for this match: the feed never sent one (Polymarket didn't run it "
                      "live) or it fell in a recording gap.")  # fmt: skip
    clock, goals, periods = [], [], []
    prev: tuple[int, int] | None = None
    prev_t = None
    last_period = None
    team = {"home": None, "away": None, "league": None}
    for s, m in ups:
        sc, p, mn = parse_score(m.get("score")), str(m.get("period") or ""), _minute(m)
        team = {"home": m.get("homeTeam") or team["home"], "away": m.get("awayTeam") or team["away"],
                "league": m.get("leagueAbbreviation") or team["league"]}  # fmt: skip
        clock.append({"t": round(s, 1), "minute": mn, "period": p, "score": m.get("score"), "status": m.get("status")})
        if p and p != last_period:
            if periods:
                periods[-1]["to"] = round(s, 1)
            periods.append({"period": p, "word": PERIOD_WORD.get(p, p), "from": round(s, 1), "to": None,
                            "minute": mn})  # fmt: skip
            last_period = p
        if sc is not None and prev is not None and sc != prev:
            dh, da = sc[0] - prev[0], sc[1] - prev[1]
            kind = "goal" if dh >= 0 and da >= 0 and dh + da == 1 else "correction" if dh < 0 or da < 0 else "goals"
            goals.append({"t": round(s, 1), "minute": mn, "period": p, "score": f"{sc[0]}-{sc[1]}", "home": sc[0],
                          "away": sc[1], "by": "home" if dh > 0 and da <= 0 else "away" if da > 0 and dh <= 0 else None,
                          "kind": kind, "after_gap": prev_t is not None and _in_gap(gaps, prev_t, s),
                          "since_previous_update_s": None if prev_t is None else round(s - prev_t, 1)})  # fmt: skip
        if sc is not None:
            prev = sc
        prev_t = s
    # a score the feed took back (a goal ruled out on review, or the feed fixing itself): the goal it undid is marked
    # retracted, and the same score said again later is that goal reinstated (first said at the retracted time)
    for i, g in enumerate(goals):
        if g["kind"] != "correction":
            continue
        undone = next((x for x in reversed(goals[:i]) if x["kind"] != "correction" and not x.get("retracted")), None)
        if undone:
            undone["retracted"] = True
            g["undoes"] = undone["score"]
            again = next((x for x in goals[i + 1 :] if x["score"] == undone["score"] and x["kind"] != "correction"), None)
            if again:
                again["reinstated"] = True
                again["first_said"] = undone["t"]
    if periods:
        last = ups[-1][0]
        if periods[-1]["period"] not in ENDED:
            periods[-1]["to"] = round(last, 1)
    ended = next((x for x in reversed(ups) if x[1].get("ended") or str(x[1].get("period")) in ENDED), None)
    first_live = next((s for s, m in ups if str(m.get("period")) in IN_PLAY), None)
    final = None
    if ended:
        final = {"score": ended[1].get("score"), "t": round(next(s for s, m in ups if m.get("ended")
                                                                 or str(m.get("period")) in ENDED), 1)}  # fmt: skip
    cov["first_update"] = round(ups[0][0], 1) if ups else None
    cov["last_update"] = round(ups[-1][0], 1) if ups else None
    cov["corrections"] = sum(g["kind"] == "correction" for g in goals)
    cov["goals"] = sum(g["kind"] != "correction" and not g.get("retracted") for g in goals)
    return {"game_id": (read or {}).get("game_id"), "league": team["league"], "home": team["home"],
            "away": team["away"], "kickoff": kickoff, "first_live_update": round(first_live, 1) if first_live else None,
            "goals": goals, "periods": periods, "clock": clock, "final": final, "coverage": cov}  # fmt: skip


def state_at(line: dict[str, Any], t: float) -> dict[str, Any]:
    """The match at ``t`` as the feed had said by then: ``phase`` (pre_kickoff, in_play, half_time, after_full_time,
    unknown), minute, period, score, the last goal and how long before ``t`` the feed said it (``since_goal_s``), and
    ``in_gap`` (``t`` fell in a recording gap: the state may be stale)."""
    clock = line.get("clock") or []
    times = [c["t"] for c in clock]
    i = bisect.bisect_right(times, t) - 1
    gaps = (line.get("coverage") or {}).get("gaps") or []
    in_gap = any(g["from"] <= t <= g["to"] for g in gaps)
    ko = line.get("kickoff")
    if not (line.get("coverage") or {}).get("recorded") or not clock:
        phase = "pre_kickoff" if ko and t < ko else "unknown"
        return {"phase": phase, "minute": None, "period": None, "score": None, "since_goal_s": None, "last_goal": None,
                "in_gap": in_gap, "known": False}  # fmt: skip
    if i < 0:
        phase = "pre_kickoff" if (ko is None or t < ko) and t < clock[0]["t"] else "unknown"
        return {"phase": phase, "minute": None, "period": None, "score": "0-0" if phase == "pre_kickoff" else None,
                "since_goal_s": None, "last_goal": None, "in_gap": in_gap, "known": phase == "pre_kickoff"}  # fmt: skip
    c = clock[i]
    p = c["period"]
    phase = ("in_play" if p in IN_PLAY else "half_time" if p in BREAK else "after_full_time" if p in ENDED
             else "pre_kickoff" if p in ("", "NS") else "unknown")  # fmt: skip
    # the last goal the feed had said by ``t`` (a goal it later took back counts until it did: that's what was showing)
    said = [g for g in line.get("goals") or [] if g["t"] <= t]
    goal = next((g for g in reversed(said) if g["kind"] != "correction"), None)
    taken_back = bool(said) and said[-1]["kind"] == "correction"
    return {"phase": phase, "minute": c["minute"], "period": p, "score": c["score"],
            "since_goal_s": round(t - goal["t"], 1) if goal and not taken_back else None,
            "last_goal": {**{k: goal[k] for k in ("t", "minute", "score", "by", "kind")},
                          "retracted": bool(goal.get("retracted"))} if goal else None,
            "after_correction_s": round(t - said[-1]["t"], 1) if taken_back else None,
            "in_gap": in_gap, "known": True}  # fmt: skip
