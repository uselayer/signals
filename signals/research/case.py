"""The case file's tools: how the agent drives the workspace instead of writing into a chat. Each one emits an
event the page draws (docs/research-contract.md); the server builds every series and checks every number, the
agent only decides what to show, in what order, and what it means.

Text the agent writes into the workspace (a walkthrough step, later a finding or an answer) is number-checked when
the tool is called: a number that doesn't trace to the data returns an error naming it, so the agent fixes it in
the same run; a second miss is accepted and shown flagged (``number_check``).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from signals.research import trace, workspace
from signals.research.data import (
    PRE_OPEN_READ_S,
    ReadError,
    complete_slugs,
    in_scope,
    iso,
    scope_time,
    window_length,
)
from signals.research.tools import CALLER

STAGES = ("windows", "window", "trades")
SHOW_AT_ONCE = 6  # windows built at once by show_windows
STATUSES = ("queued", "running", "done", "warning", "failed")

_obj = {"type": "object"}
CASE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "propose_plan",
        "description": (
            "Shows the user your plan for this breakdown and waits for them to press Start (or change it): "
            "always first in a new breakdown, and before a follow-up that widens the scope (more windows, a "
            "longer range, another wallet). After calling it, end your turn without more text. steps: what you'll "
            "do, each with a short id, a title in plain words, its source in plain words ('Polymarket trades', "
            "'Layer's recorded order books', 'Binance') and estimate_s. scope: {wallet, family "
            "('btc-updown-15m'), from, to}, from and to as ISO times in UTC (2026-11-10T05:30:00Z), or to: 'now'. "
            "scope_options: choices the user can tick, e.g. "
            "{id: 'october', text: 'Also look at October with 1-minute prices'}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "scope": _obj,
                "steps": {"type": "array", "items": _obj}, "scope_options": {"type": "array", "items": _obj},
            },  # fmt: skip
            "required": ["title", "scope", "steps"],
        },
    },
    {
        "name": "step_status",
        "description": (
            "Updates one plan step on the page: status queued|running|done|warning|failed, progress {done, total}, "
            "a one-line summary of what it found, warnings [{kind, text, window_ids}] (e.g. partial history, a "
            "recording gap). Call it from your code inside loops too."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"step_id": {"type": "string"}, "status": {"type": "string", "enum": list(STATUSES)},
                           "progress": _obj, "summary": {"type": "string"}, "warnings": {"type": "array", "items": _obj}},
            "required": ["step_id", "status"],
        },  # fmt: skip
    },
    {
        "name": "show_windows",
        "description": (
            "Puts windows on the page as overview tiles. The server builds each window's replay from what you read "
            "(prices, the wallet's fills, its position, coverage), so pass only window ids (slugs) and, if you "
            "like, tags per window ({slug: {...}}: e.g. the moment BTC cleared the price to beat). Returns JSON "
            "{windows: [{window_id, result, fills, first_entry_s, cost, profit, coverage}], coverage totals}. "
            "Call it once with every window: the server builds them in parallel and each tile appears on the page "
            "as soon as it's ready (no need to batch or report progress yourself)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"window_ids": {"type": "array", "items": {"type": "string"}}, "tags": _obj},
            "required": ["window_ids"],
        },
    },
    {
        "name": "focus",
        "description": (
            "Moves the workspace: stage 'windows' (the overview; highlight some with highlight_window_ids), "
            "'window' (one window's replay, at a walkthrough step) or 'trades'. label: one plain sentence saying "
            "why ('I've opened the clearest example')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"stage": {"type": "string", "enum": list(STAGES)}, "window_id": {"type": "string"},
                           "step_index": {"type": "integer"}, "highlight_window_ids": {"type": "array", "items": {"type": "string"}},
                           "label": {"type": "string"}},
            "required": ["stage"],
        },  # fmt: skip
    },
    {
        "name": "walkthrough",
        "description": (
            "A step-through of one window shown on its replay. steps: [{t (unix s), title, observed (what the data "
            "shows there, with its numbers), inferred (your reading, or null), trade_ids (the fills it's about), "
            "annotations [{kind: point|span|region, t0, t1, panel: btc|prices|position, label}]}]. Every number in "
            "the text must be one your code printed or a tool returned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"window_id": {"type": "string"}, "steps": {"type": "array", "items": _obj}},
            "required": ["window_id", "steps"],
        },
    },
    {
        "name": "finding",
        "description": (
            "Adds an evidence card, or updates one (pass its finding_id; the previous version is kept). label: "
            "'observed' (it's in the data) or 'inferred' (your reading of why; based_on: the observed finding ids "
            "it rests on, and would_change_mind: what would refute it). kind: pattern|read|unsure|data|change. stat: "
            "{count, out_of, unit, text}: always fill count, out_of and unit (the page headlines '65 of 94 windows'), "
            "and make text one plain sentence with the detail. rule: how you counted, in one plain sentence. "
            "evidence: {supporting_window_ids, against_window_ids, trade_ids}. example: {window_id, step_index} to "
            "step through. Every number must be one your code printed or a tool returned; a flagged finding doesn't "
            "count and can't support an inferred one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string"}, "kind": {"type": "string"},
                "label": {"type": "string", "enum": ["observed", "inferred"]}, "title": {"type": "string"},
                "stat": _obj, "rule": {"type": "string"}, "evidence": _obj, "example": _obj,
                "based_on": {"type": "array", "items": {"type": "string"}}, "would_change_mind": {"type": "string"},
            },  # fmt: skip
            "required": ["label", "title"],
        },
    },
    {
        "name": "answer",
        "description": (
            "Answers the user's question as a card: label (a few words), observed: [lines with the data's "
            "numbers], inferred: [your readings, each saying what would confirm it], annotations: [{window_id, kind: "
            "point|span|region, t0, t1, panel: btc|prices|position, label}] to draw on the replay, focus: {stage, "
            "window_id, step_index, label} to move the workspace, finding_ids it rests on or changed. The card sits "
            "on top of the findings, so keep it to two or three plain sentences in all; the detail lives in the "
            "findings. Call it once at the end of every answer, then end your turn."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string"}, "observed": {"type": "array", "items": {"type": "string"}},
                "inferred": {"type": "array", "items": {"type": "string"}},
                "annotations": {"type": "array", "items": _obj}, "focus": _obj,
                "finding_ids": {"type": "array", "items": {"type": "string"}},
            },  # fmt: skip
            "required": ["label", "observed"],
        },
    },
    {
        "name": "propose",
        "description": "Offers the user a next step as a card ('Next, I'd look at…') with a button; they accept or decline.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "accept_label": {"type": "string"}},
            "required": ["text"],
        },
    },
]
for _t in CASE_TOOLS:  # step_status and show_windows from code as well; the rest are the agent's own moves
    _t["allowed_callers"] = ["direct", CALLER] if _t["name"] in ("step_status", "show_windows") else ["direct"]
NAMES = {t["name"] for t in CASE_TOOLS}
WAITS = "propose_plan"  # after this one the run ends: the user starts the plan


def _at(points: list[dict[str, Any]], t: float) -> dict[str, Any] | None:
    """The last point at or before ``t`` (series are sorted by ``t``)."""
    best = None
    for p in points or []:
        if p["t"] > t:
            break
        best = p
    return best


def resolve_context(store: Any, reads: Any, sid: str, context: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the user pointed at, as facts from the data (never the page's word for them): a fill, a moment in a
    window, or a finding. None for no context; ReadError when it doesn't exist in this investigation."""
    if not context:
        return None
    if context.get("trade_ids"):  # a burst of fills clicked together
        ids = [str(t) for t in context["trade_ids"]][:50]
        each = [resolve_context(store, reads, sid, {"trade_id": t}) for t in ids]
        return {"kind": "trades", "window_id": each[0]["window_id"] if each else None,
                "trades": [e["trade"] for e in each if e], "count": len(each)}  # fmt: skip
    if context.get("trade_id"):
        fill = store.trade(sid, str(context["trade_id"]))
        if not fill:
            raise ReadError("That trade isn't one of this breakdown's fills.")
        slug = fill.get("slug")
        ready = store.window(sid, slug)["ready"] if slug else None
        drawn = next((t for t in (ready or {}).get("trades") or [] if t["trade_id"] == fill["id"]), None)
        return {"kind": "trade", "trade": fill, "window_id": slug,
                "as_drawn": drawn, "seconds_after_start": fill["ts"] - int(ready["start"]) if ready else None}  # fmt: skip
    if context.get("window_id"):
        slug = str(context["window_id"])
        ready = store.window(slug=slug, sid=sid)["ready"] or workspace.build(store, reads, sid, slug)
        t = context.get("t")
        out: dict[str, Any] = {"kind": "moment" if t is not None else "window", "window_id": slug,
                               "start": ready["start"], "end": ready["end"], "price_to_beat": ready["price_to_beat"],
                               "result": ready["result"]}  # fmt: skip
        if t is not None:
            t = int(t)
            out |= {"t": t, "seconds_after_start": t - ready["start"], "binance": _at(ready["binance"], t),
                    "chainlink": _at(ready["chainlink"] or [], t), "up": _at(ready["up"], t), "down": _at(ready["down"], t),
                    "position": _at(ready["position"], t),
                    "fills_within_10s": [f for f in ready["trades"] if abs(f["t"] - t) <= 10]}  # fmt: skip
        return out
    if context.get("finding_id"):
        f = store.finding(sid, str(context["finding_id"])) if hasattr(store, "finding") else None
        if not f:
            raise ReadError("That finding isn't in this breakdown.")
        return {"kind": "finding", "finding": f, "stat": context.get("stat")}
    raise ReadError("Point at a trade (trade_id), a moment (window_id and t) or a finding (finding_id).")


def prebuild(store: Any, reads: Any, sid: str, scope: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> int:
    """On Start, the approved scope's tiles before the agent asks for them: every window that starts in the range
    and the wallet traded, with all its fills (``in_scope``), built SHOW_AT_ONCE at a time, each window.summary sent
    as soon as it's built, then the coverage. Everything is kept, so the agent's own show_windows (and the page's GETs) find it ready. Returns the
    number of windows shown; 0 when the scope doesn't name a wallet and a range."""
    wallet, a, b = scope.get("wallet"), scope.get("from"), scope.get("to")
    if not (wallet and a and b):
        return 0
    family = str(scope.get("family") or "btc-updown-15m").rstrip("-") + "-"
    # The scope's windows are the ones that start in it, each with all its fills: read from PRE_OPEN_READ_S before
    # the range (a first window's pre-open buys) to just after its last window closes. A read of the range alone
    # cut both ends: it left out a buy 2 s before 05:30 and tiled the 06:45 window from 2 early fills (10 Nov).
    a_s, b_s = scope_time(a), scope_time(b)
    lo, hi = a_s - PRE_OPEN_READ_S, b_s + window_length(family.rstrip("-")) + 60
    got = reads.wallet_trades(wallet, lo, hi, family)
    mine = [t for t in got["trades"] if in_scope(t.get("slug"), a_s, b_s)]
    store.set_wallet(sid, str(got.get("wallet") or wallet).lower())
    store.add_trades(sid, mine)
    store.mark_complete(sid, complete_slugs({**got, "trades": mine}, lo, hi))
    slugs = sorted({t["slug"] for t in mine if t.get("slug")})
    covs = []
    with ThreadPoolExecutor(max_workers=SHOW_AT_ONCE) as pool:
        futures = {pool.submit(workspace.build, store, reads, sid, s): s for s in slugs}
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001 - a window that can't be read is left for the agent to retry
                print(f"research: prebuild {futures[fut]} failed: {type(e).__name__}: {e}", flush=True)
                continue
            emit({"type": "window.summary", **workspace.summary(r)})
            covs.append(r["coverage"])
    covs.sort(key=lambda c: c["window_id"] or "")
    emit({"type": "coverage", "per_source": workspace.totals(covs), "windows": covs})
    return len(covs)


def scope_ok(scope: dict[str, Any] | None) -> bool:
    """Whether Start can build this scope's tiles: a wallet and a range it can read."""
    if not (scope and scope.get("wallet") and scope.get("from") and scope.get("to")):
        return False
    try:
        return scope_time(scope["from"]) <= scope_time(scope["to"])
    except ReadError:
        return False


MAX_FILL = 120  # tiles the end-of-run sweep builds at most


def fill_tiles(store: Any, reads: Any, sid: str, emit: Callable[[dict[str, Any]], None]) -> int:
    """At the end of a run: a tile for every window the agent read where the wallet traded but that has no tile yet
    (Start's prebuild couldn't read the scope, or the agent read windows without show_windows), so the Windows tab
    holds the windows the answer counts. Returns the number of tiles added."""
    traded = {t["slug"] for t in store.trades(sid) if t.get("slug")}
    slugs = [s for s in store.unshown(sid) if s in traded][:MAX_FILL]
    added = 0
    with ThreadPoolExecutor(max_workers=SHOW_AT_ONCE) as pool:
        futures = {pool.submit(workspace.build, store, reads, sid, s): s for s in slugs}
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001 - a window that can't be built leaves the others
                print(f"research: tile {futures[fut]} failed: {type(e).__name__}: {e}", flush=True)
                continue
            emit({"type": "window.summary", **workspace.summary(r)})
            added += 1
    if added:  # the page's coverage is replaced whole: every tile's, not just the new ones
        covs = [ready["coverage"] for s in store.summaries(sid)
                if (ready := store.window(sid, s["window_id"])["ready"]) and ready.get("coverage")]  # fmt: skip
        emit({"type": "coverage", "per_source": workspace.totals(covs), "windows": covs})
    return added


def _brief(s: dict[str, Any]) -> dict[str, Any]:
    return {"window_id": s["window_id"], "result": s["result"], "fills": len(s["entries"]),
            "first_entry_s": s["first_entry_s"], "cost": s["cost"], "profit": s["profit"], "coverage": s["coverage"]}  # fmt: skip


class Case:
    """One run's view of the investigation: emits workspace events and keeps what the page was sent."""

    def __init__(self, sid: str, ask_id: int, store: Any, reads: Any, emit: Callable[[dict[str, Any]], None],
                 sources: Callable[[], trace.Sources]) -> None:  # fmt: skip
        self.sid, self.ask_id, self.store, self.reads, self.emit, self.sources = sid, ask_id, store, reads, emit, sources
        self.failed_checks: set[str] = set()  # cards whose numbers failed once (the second time they're shown)
        self.sent_ready: set[str] = set()
        self.waiting = False  # a plan is shown and waits for Start
        self.answered = False  # the answer tool ran: closing text isn't another card

    def check(self, key: str, texts: dict[str, str | None]) -> tuple[str | None, dict[str, Any]]:
        """Number-checks a card's texts: (an error for the agent on a first miss, else None; the number_check)."""
        src = self.sources()
        flagged = {k: trace.flagged(v, src) for k, v in texts.items() if v}
        flagged = {k: v for k, v in flagged.items() if v}
        if flagged and key not in self.failed_checks:
            self.failed_checks.add(key)
            said = "; ".join(f"{k}: " + ", ".join(
                f"{f['value_text']}" + (f" (closest in the data: {f['data_value']:g})" if f["data_value"] is not None else "")
                for f in fs) for k, fs in flagged.items())  # fmt: skip
            return (f"Error: these numbers aren't in any tool result or printed output: {said}. Print each figure "
                    "from your code (or drop it), then call this tool again."), {}  # fmt: skip
        return None, {"passed": not flagged, "flagged": flagged}

    def handle(self, name: str, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        try:
            return getattr(self, f"_{name}")(inp)
        except ReadError as e:
            return f"Error: {e}", True, {"error": str(e)}

    # ---- the tools ----

    def _propose_plan(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        steps = [{"id": str(s.get("id") or i + 1), "title": s.get("title"), "source": s.get("source"),
                  "estimate_s": s.get("estimate_s")} for i, s in enumerate(inp.get("steps") or [])]  # fmt: skip
        if not steps:
            raise ReadError("A plan needs at least one step.")
        scope = dict(inp.get("scope") or {})
        for k in ("from", "to"):  # kept as a time Start can read ("now" stays "now": it's read at Start)
            v = scope.get(k)
            if isinstance(v, str) and v.strip().lower() != "now":
                try:
                    scope[k] = iso(scope_time(v))
                except ReadError as e:
                    raise ReadError(f"scope.{k} {v!r} isn't a time: give an ISO time in UTC like "
                                    "2026-11-10T05:30:00Z (or 'now' for to).") from e  # fmt: skip
        if scope.get("wallet"):
            self.store.set_wallet(self.sid, str(scope["wallet"]).lower())
        self.store.set_scope(self.sid, scope)  # Start builds this scope's tiles at once (prebuild)
        plan = {"type": "plan.proposed", "plan_id": f"plan-{self.ask_id}", "ask_id": self.ask_id,
                "title": inp.get("title"), "scope": scope, "steps": steps,
                # the server's figure, never the model's guess: what recent Starts cost (None until there are enough)
                "scope_options": inp.get("scope_options") or [], "estimate_usd": self.store.start_cost(),
                "estimate_s": self.store.typical_seconds(start=True),  # likewise how long recent Starts took
                "needs_approval": True}  # fmt: skip
        self.store.set_title(self.sid, str(inp.get("title") or "")[:120])
        self.emit(plan)
        self.waiting = True
        return ("Plan shown. The user will press Start or change it: end your turn now, without more text.", False,
                {"steps": len(steps)})  # fmt: skip

    def _step_status(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        if inp.get("status") not in STATUSES:
            raise ReadError(f"status must be one of {', '.join(STATUSES)}.")
        self.emit({"type": "step.status", "step_id": str(inp.get("step_id")), "status": inp["status"],
                   "progress": inp.get("progress"), "summary": inp.get("summary"),
                   "warnings": inp.get("warnings") or []})  # fmt: skip
        return "ok", False, {"step_id": inp.get("step_id"), "status": inp["status"]}

    def _show_windows(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        ids = [str(w) for w in inp.get("window_ids") or []]
        if not ids:
            raise ReadError("Give the window ids (slugs) to show.")
        tags = inp.get("tags") or {}
        briefs, covs, failed = [], [], []

        def one(slug: str) -> dict[str, Any] | str:
            try:
                return workspace.build(self.store, self.reads, self.sid, slug, tags.get(slug))
            except Exception as e:  # noqa: BLE001 - a window that can't be read is named, the rest still show
                return f"{type(e).__name__}: {e}"[:200]

        # Built SHOW_AT_ONCE at a time (a call from code must answer within about 4 minutes); each tile goes to the
        # page as soon as it's built, so the overview fills in while the rest are read.
        got: dict[str, dict[str, Any] | str] = {}
        with ThreadPoolExecutor(max_workers=SHOW_AT_ONCE) as pool:
            futures = {pool.submit(one, slug): slug for slug in ids}
            for fut in as_completed(futures):
                slug, r = futures[fut], fut.result()
                got[slug] = r
                if not isinstance(r, str):
                    self.emit({"type": "window.summary", **workspace.summary(r)})
        for slug in ids:  # the agent's answer in the order it asked
            r = got[slug]
            if isinstance(r, str):
                failed.append({"window_id": slug, "why": r})
                continue
            briefs.append(_brief(workspace.summary(r)))
            covs.append(r["coverage"])
        totals = workspace.totals(covs)
        self.emit({"type": "coverage", "per_source": totals, "windows": covs})
        out = {"windows": briefs, "coverage": totals, "failed": failed}
        return json.dumps(out, separators=(",", ":")), False, {"rows": len(briefs), "failed": len(failed)}

    def _ready(self, slug: str) -> None:
        """Sends a window's full replay once per run (the page may also fetch it)."""
        if slug in self.sent_ready:
            return
        r = self.store.window(self.sid, slug)["ready"] or workspace.build(self.store, self.reads, self.sid, slug)
        self.emit({"type": "window.ready", **r})
        self.sent_ready.add(slug)

    def _focus(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        stage = inp.get("stage")
        if stage not in STAGES:
            raise ReadError(f"stage must be one of {', '.join(STAGES)}.")
        if stage == "window":
            if not inp.get("window_id"):
                raise ReadError("Focusing on a window needs its window_id.")
            self._ready(str(inp["window_id"]))
        self.emit({"type": "view.focus", "stage": stage, "window_id": inp.get("window_id"),
                   "step_index": inp.get("step_index"),
                   "highlight_window_ids": inp.get("highlight_window_ids") or [], "label": inp.get("label")})  # fmt: skip
        return "ok", False, {"stage": stage}

    def _walkthrough(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        slug = str(inp.get("window_id") or "")
        steps = inp.get("steps") or []
        if not slug or not steps:
            raise ReadError("A walkthrough needs window_id and steps.")
        known = {t["id"] for t in self.store.trades(self.sid, slug)}
        unknown = sorted({str(i) for s in steps for i in s.get("trade_ids") or []} - known)
        if unknown:
            raise ReadError(f"These trade ids aren't the wallet's fills in {slug}: {', '.join(unknown[:5])}.")
        texts = {f"step {i + 1} {k}": s.get(k) for i, s in enumerate(steps) for k in ("title", "observed", "inferred")}
        err, check = self.check(f"walkthrough:{slug}", texts)
        if err:
            return err, True, {"number_check": "failed once"}
        out = []
        for i, s in enumerate(steps):
            mine = {k.split(" ", 2)[2]: v for k, v in check["flagged"].items() if k.startswith(f"step {i + 1} ")}
            out.append({"index": i, "t": s.get("t"), "title": s.get("title"), "observed": s.get("observed"),
                        "inferred": s.get("inferred"), "trade_ids": s.get("trade_ids") or [],
                        "annotations": s.get("annotations") or [],
                        "number_check": {"passed": not mine, "flagged": mine}})  # fmt: skip
        self._ready(slug)
        self.emit({"type": "walkthrough.ready", "window_id": slug, "steps": out})
        return "ok", False, {"steps": len(out), "number_check": check["passed"]}

    def _finding(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        label = inp.get("label")
        if label not in ("observed", "inferred"):
            raise ReadError("label must be observed or inferred.")
        fid = inp.get("finding_id")
        old = self.store.finding(self.sid, str(fid)) if fid else None
        if fid and old is None:
            raise ReadError(f"There's no finding {fid} in this breakdown.")
        ev = inp.get("evidence") or {}
        trades = [str(t) for t in ev.get("trade_ids") or []]
        unknown = [t for t in trades if not self.store.trade(self.sid, t)]
        if unknown:
            raise ReadError(f"These trade ids aren't the wallet's fills: {', '.join(unknown[:5])}.")
        windows = {w for k in ("supporting_window_ids", "against_window_ids") for w in ev.get(k) or []}
        missing = sorted(w for w in windows if self.store.window(self.sid, str(w))["read"] is None
                         and not self.store.trades(self.sid, str(w)))  # fmt: skip
        if missing:
            raise ReadError(f"These windows weren't read in this breakdown: {', '.join(missing[:5])}.")
        based_on = [str(b) for b in inp.get("based_on") or []]
        if label == "inferred":
            if not based_on:
                raise ReadError("An inferred finding needs based_on: the observed finding ids it rests on.")
            for b in based_on:
                f = self.store.finding(self.sid, b)
                if f is None:
                    raise ReadError(f"There's no finding {b} to rest on.")
                if not (f.get("number_check") or {}).get("passed", False):
                    raise ReadError(f"{b} has numbers that didn't check out, so nothing can rest on it until it's fixed.")
        stat = inp.get("stat") or {}
        stat_nums = " ".join(str(stat[k]) for k in ("count", "out_of") if stat.get(k) is not None)
        texts = {"title": inp.get("title"), "stat": " ".join(x for x in (stat.get("text"), stat_nums) if x),
                 "rule": inp.get("rule"), "would_change_mind": inp.get("would_change_mind")}  # fmt: skip
        err, check = self.check(f"finding:{fid or inp.get('title')}", texts)
        if err:
            return err, True, {"number_check": "failed once"}
        card = {"kind": inp.get("kind") or ("read" if label == "inferred" else "pattern"), "label": label,
                "title": inp.get("title"), "stat": stat or None, "rule": inp.get("rule"),
                "evidence": {"supporting_window_ids": ev.get("supporting_window_ids") or [],
                             "against_window_ids": ev.get("against_window_ids") or [], "trade_ids": trades},
                "example": inp.get("example"), "based_on": based_on, "would_change_mind": inp.get("would_change_mind"),
                "number_check": check, "counts": check["passed"], "ask_id": self.ask_id}  # fmt: skip
        if old is None:
            fid = self.store.add_finding(self.sid, card)
            self.emit({"type": "finding.added", "finding_id": fid, **card})
        else:
            prev = {k: old.get(k) for k in ("title", "stat", "rule", "label", "number_check")}
            card["history"] = [*(old.get("history") or []), prev]
            self.store.update_finding(self.sid, str(fid), card)
            self.emit({"type": "finding.updated", "finding_id": fid, "previous": prev, **card})
        return json.dumps({"finding_id": fid, "number_check": check["passed"]}), False, {"finding_id": fid}

    def _answer(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        observed = [str(x) for x in inp.get("observed") or []]
        inferred = [str(x) for x in inp.get("inferred") or []]
        texts = {"label": inp.get("label"), **{f"observed {i + 1}": t for i, t in enumerate(observed)},
                 **{f"inferred {i + 1}": t for i, t in enumerate(inferred)}}  # fmt: skip
        err, check = self.check(f"answer:{self.ask_id}", texts)
        if err:
            return err, True, {"number_check": "failed once"}
        focus = inp.get("focus")
        if focus and focus.get("stage") in STAGES:
            self._focus(focus)
        self.emit({"type": "answer.card", "ask_id": self.ask_id, "label": inp.get("label"), "observed": observed,
                   "inferred": inferred, "annotations": inp.get("annotations") or [], "focus": focus,
                   "finding_ids": inp.get("finding_ids") or [], "number_check": check})  # fmt: skip
        self.answered = True
        return "Answer shown. End your turn now.", False, {"number_check": check["passed"]}

    def _propose(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        n = sum(e.get("type") == "proposal" for e in self.store.events(self.sid)) + 1
        pid = f"P{n}"
        self.emit({"type": "proposal", "proposal_id": pid, "ask_id": self.ask_id, "text": inp.get("text"),
                   "accept_label": inp.get("accept_label") or "Yes, do that"})  # fmt: skip
        return json.dumps({"proposal_id": pid}), False, {"proposal_id": pid}
