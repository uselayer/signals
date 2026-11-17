"""Breakdowns in PostHog from the research service (README, "Analytics"): what only the service knows, each run's end
(``breakdown finished``: how long it took, what it cost, its findings, and an error if it stopped on one). The page
sends the rest (``static/js/analytics.js``); a tab closed mid-run never loses this one.

The engine's rules (``signals/app.py`` ``ph``): the same SIGNALS_POSTHOG_KEY; the person is their Clerk user id only,
never a name, email or the question they asked. Sent in the background, a batch at a time, and never in the way:
with no key, a full queue or PostHog down, the event is dropped. Copied rather than imported: importing
``signals.app`` here would start the engine.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from collections import deque
from datetime import UTC, datetime
from typing import Any

KEY = os.environ.get("SIGNALS_POSTHOG_KEY", "")
HOST = os.environ.get("SIGNALS_POSTHOG_HOST", "https://us.i.posthog.com")
QUEUE_MAX = 1000
LOCAL_USER = "local"  # auth.LOCAL_USER: the service run without Clerk, on a laptop

_queue: deque[dict[str, Any]] = deque()
_wake = threading.Event()
_state: dict[str, Any] = {"thread": None}


def ph(event: str, uid: str | None, props: dict[str, Any] | None = None) -> None:
    """Queue one server-side event about account ``uid``. Nothing without a key, an id, or for the local user."""
    if not KEY or not uid or uid == LOCAL_USER or len(_queue) >= QUEUE_MAX:
        return
    p = {k: v for k, v in (props or {}).items() if v is not None}
    # source "server": the Product health dashboards' bot filter keeps server events (they have no browser)
    p |= {"source": "server", "service": "research"}
    _queue.append({"event": event, "distinct_id": uid, "properties": p, "timestamp": datetime.now(UTC).isoformat()})
    if _state["thread"] is None:
        _state["thread"] = threading.Thread(target=_loop, daemon=True, name="posthog")
        _state["thread"].start()
    _wake.set()


def _send(batch: list[dict[str, Any]]) -> None:
    req = urllib.request.Request(f"{HOST}/batch/", data=json.dumps({"api_key": KEY, "batch": batch}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")  # fmt: skip
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


def _loop() -> None:
    while True:
        _wake.wait(30)
        _wake.clear()
        batch = [_queue.popleft() for _ in range(min(len(_queue), 100))]
        if not batch:
            continue
        try:
            _send(batch)
        except (urllib.error.URLError, OSError, ValueError):
            pass  # dropped: analytics never holds anything up
        if _queue:
            _wake.set()


def run_kind(context: dict[str, Any] | None, planning: bool) -> str:
    """What a run was: a new breakdown's first question drafting its ``plan``, a plan's ``start``, a ``plan change``,
    an accepted ``next step`` (the agent's proposal), or a ``follow-up`` question."""
    c = context or {}
    if c.get("action") == "approve":
        return "start"
    if c.get("action") == "edit":
        return "plan change"
    if c.get("proposal_id"):
        return "next step"
    return "plan" if planning else "follow-up"


def finished_facts(run: dict[str, Any] | None, events: list[dict[str, Any]], market: str | None) -> dict[str, Any] | None:
    """``breakdown finished``'s properties from the run's row (``store.last_run``) and the breakdown's events: seconds,
    cost_usd, the findings this run added that count, the market type, and ``error`` (``over_budget``/``over_time``,
    or an exception's class name: never its message). None for a run with no end written."""
    if not run or not run.get("ended"):
        return None
    rid = run.get("id")
    found = {e.get("finding_id") for e in events
             if e.get("type") == "finding.added" and e.get("run") == rid and e.get("counts", True)} - {None}  # fmt: skip
    err = run.get("error")
    return {"seconds": round(float(run["ended"]) - float(run["started"]), 1), "cost_usd": round(float(run.get("cost_usd") or 0), 4),
            "findings": len(found), "market": market, "error": str(err).split(":", 1)[0][:80] if err else None}  # fmt: skip
