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
from typing import Any

from signals.research import trace, workspace
from signals.research.data import ReadError
from signals.research.tools import CALLER

STAGES = ("windows", "window", "trades")
STATUSES = ("queued", "running", "done", "warning", "failed")

_obj = {"type": "object"}
CASE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "propose_plan",
        "description": (
            "Shows the user your plan for this investigation and waits for them to press Start (or change it): "
            "always first in a new investigation, and before a follow-up that widens the scope (more windows, a "
            "longer range, another wallet). After calling it, end your turn without more text. steps: what you'll "
            "do, each with a short id, a title in plain words, its source in plain words ('Polymarket trades', "
            "'Layer's recorded order books', 'Binance') and estimate_s. scope: {wallet, family "
            "('btc-updown-15m'), from, to}. scope_options: choices the user can tick, e.g. "
            "{id: 'october', text: 'Also look at October with 1-minute prices'}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "scope": _obj,
                "steps": {"type": "array", "items": _obj}, "scope_options": {"type": "array", "items": _obj},
                "estimate_usd": {"type": "number"},
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
            "Call it from code for many windows at once."
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
        scope = inp.get("scope") or {}
        if scope.get("wallet"):
            self.store.set_wallet(self.sid, str(scope["wallet"]).lower())
        plan = {"type": "plan.proposed", "plan_id": f"plan-{self.ask_id}", "ask_id": self.ask_id,
                "title": inp.get("title"), "scope": scope, "steps": steps,
                "scope_options": inp.get("scope_options") or [], "estimate_usd": inp.get("estimate_usd"),
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
        for slug in ids:
            try:
                r = workspace.build(self.store, self.reads, self.sid, slug, tags.get(slug))
            except ReadError as e:
                failed.append({"window_id": slug, "why": str(e)})
                continue
            s = workspace.summary(r)
            self.emit({"type": "window.summary", **s})
            briefs.append(_brief(s))
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

    def _propose(self, inp: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
        n = sum(e.get("type") == "proposal" for e in self.store.events(self.sid)) + 1
        pid = f"P{n}"
        self.emit({"type": "proposal", "proposal_id": pid, "ask_id": self.ask_id, "text": inp.get("text"),
                   "accept_label": inp.get("accept_label") or "Yes, do that"})  # fmt: skip
        return json.dumps({"proposal_id": pid}), False, {"proposal_id": pid}
