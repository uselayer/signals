"""Breakdowns in PostHog (README, "Analytics"): the page loads PostHog as the main page does, with the key from the
research service's config, and sends the named events; the service sends each run's end itself. The person is their
Clerk id only and their question never leaves: not in an event, a replay's text or the page's address. No network."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("RESEARCH_STORE_DIR", tempfile.mkdtemp(prefix="research-test-"))

from signals.research import analytics, server  # noqa: E402
from signals.research.store import Store  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "signals" / "research" / "static"
APP = (STATIC / "js" / "app.js").read_text()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """What the service queued for PostHog (the sender thread is never started)."""
    monkeypatch.setattr(analytics, "KEY", "phc_test")
    monkeypatch.setattr(analytics, "_state", {"thread": object()})
    analytics._queue.clear()
    yield analytics._queue
    analytics._queue.clear()


class Runs:
    """A fake agent: each run writes its row as the real one does (ended, cost, error) and a finding or two."""

    def __init__(self, store: Store, error: str | None = None) -> None:
        self.store, self.error = store, error

    def ask(self, sid: str, user: str, q: str, emit: Any, **kw: Any) -> None:
        run = self.store.start_run(sid, user)
        emit({"type": "ask.started", "run": run})
        emit({"type": "finding.added", "finding_id": "F1", "counts": True, "run": run})
        emit({"type": "finding.added", "finding_id": "F2", "counts": False, "run": run})  # flagged: doesn't count
        emit({"type": "finding.added", "finding_id": "F0", "counts": True, "run": run - 1})  # an earlier run's
        self.store.update_run(run, ended=time.time() + 90, cost_usd=0.30123, error=self.error)
        emit({"type": "done", "run": run})


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    store = Store(os.path.join(tempfile.mkdtemp(), "a.db"))
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(server, "_queue", [])
    monkeypatch.setattr(server, "_reads", object())
    server.app.dependency_overrides[server.auth.user_of] = lambda: "user_mark"
    yield store, TestClient(server.app)
    server.app.dependency_overrides.clear()


def _wait(cond: Any) -> None:
    for _ in range(300):
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def test_the_page_gets_the_key_from_the_service_config(monkeypatch: pytest.MonkeyPatch) -> None:
    c = TestClient(server.app)
    monkeypatch.setattr(analytics, "KEY", "")
    assert c.get("/api/research/config").json()["posthog_key"] is None
    monkeypatch.setattr(analytics, "KEY", "phc_test")
    assert c.get("/api/research/config").json()["posthog_key"] == "phc_test"


def test_a_start_that_ends_sends_breakdown_finished_with_what_it_cost(svc: Any, sent: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store, c = svc
    monkeypatch.setattr(server, "_agent", Runs(store))
    sid = c.post("/api/research/sessions", json={"title": "How does X trade?"}).json()["id"]
    store.set_scope(sid, {"market_type": "btc-updown-15m", "wallet": "0x" + "a" * 40})
    store.add_event(sid, {"type": "plan.proposed", "plan_id": "plan-1", "steps": [{"id": "s"}]})
    assert c.post(f"/api/research/sessions/{sid}/plan", json={"plan_id": "plan-1", "action": "approve"}).status_code == 202
    _wait(lambda: len(sent) == 1 and not server._running)
    (e,) = sent
    assert e["event"] == "breakdown finished" and e["distinct_id"] == "user_mark"
    p = e["properties"]
    assert p["breakdown_id"] == sid and p["run"] == "start" and p["market"] == "btc-updown-15m"
    assert 89 <= p["seconds"] <= 91 and p["cost_usd"] == 0.3012 and p["findings"] == 1
    assert "error" not in p  # a clean run: no error property at all
    assert p["source"] == "server" and p["service"] == "research"
    assert "How does X" not in json.dumps(list(sent))  # never the question or the breakdown's title


def test_a_run_that_stopped_says_why_never_the_message(svc: Any, sent: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store, c = svc
    monkeypatch.setattr(server, "_agent", Runs(store, error="RuntimeError: details about user_mark's question"))
    sid = c.post("/api/research/sessions", json={"title": "T"}).json()["id"]
    assert c.post(f"/api/research/sessions/{sid}/ask", json={"question": "How does 0xabc trade?"}).status_code == 202
    _wait(lambda: len(sent) == 1 and not server._running)
    p = sent[0]["properties"]
    assert p["run"] == "plan" and p["error"] == "RuntimeError"  # a new breakdown's first question drafts its plan
    assert "details" not in json.dumps(list(sent))
    assert analytics.finished_facts({"id": 1, "started": 0, "ended": 5, "error": "over_time"}, [], None)["error"] == "over_time"
    assert analytics.finished_facts({"id": 1, "started": 0, "ended": None}, [], None) is None  # no end written: nothing


def test_nothing_without_the_key_or_for_the_local_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics, "_state", {"thread": object()})
    analytics._queue.clear()
    monkeypatch.setattr(analytics, "KEY", "")
    analytics.ph("breakdown finished", "user_1", {})
    monkeypatch.setattr(analytics, "KEY", "phc_test")
    analytics.ph("breakdown finished", "local", {})
    analytics.ph("breakdown finished", None, {})
    assert not analytics._queue


def test_each_kind_of_run_is_named() -> None:
    k = analytics.run_kind
    assert k({"plan_id": "p", "action": "approve"}, False) == "start"
    assert k({"plan_id": "p", "action": "edit"}, False) == "plan change"
    assert k({"proposal_id": "x"}, False) == "next step"
    assert (k(None, True), k(None, False), k({"finding_id": "F1"}, False)) == ("plan", "follow-up", "follow-up")


# ---- the page ----

EVENTS = {"breakdown sample opened", "breakdown asked", "breakdown plan shown", "breakdown started",
          "breakdown follow-up asked", "breakdown opened", "breakdown deleted"}  # fmt: skip
ALLOWED = {"breakdown_id", "market", "range_hours", "start", "wallet_from", "plan_id", "estimate_usd", "steps", "first",
           "queued", "options", "from", "pointed_at", "age_days", "running", "undo"}  # fmt: skip


def test_the_page_sends_each_named_event_and_only_facts_about_the_breakdown() -> None:
    calls = re.findall(r"track\('([^']+)'(.*?)\);", APP)
    assert {e for e, _ in calls} | {"breakdown follow-up asked", "breakdown plan shown", "breakdown started"} >= EVENTS
    assert {e for e, _ in calls} <= EVENTS
    keys = set(re.findall(r"\b([a-z_]+): ", " ".join(a for _, a in calls)))
    keys |= set(re.findall(r"\b([a-z_]+): ", re.search(r"const planFacts = pid => (.*?)};", APP, re.S).group(1)))
    keys |= set(re.findall(r"\b([a-z_]+): ", re.search(r"const followUp = (.*?);\n", APP).group(1)))
    assert keys - {"id", "p"} <= ALLOWED, keys - ALLOWED
    for word in ("question", "text", "title", "q:", "name"):  # the question and anything about the person stay here
        assert all(word not in a for _, a in calls), word
    assert "track('breakdown plan shown', planFacts(e.plan_id))" in APP
    assert "track('breakdown started', { ...planFacts(pid)" in APP
    assert APP.count("followUp('") == 2 and "followUp(c && q === 'Why here?' ? 'why_here'" in APP


def test_the_question_from_the_ask_bar_leaves_the_address_before_analytics() -> None:
    assert "u.searchParams.delete('q')" in APP and "history.replaceState" in APP
    assert APP.index("u.searchParams.delete('q')") < APP.index("startAnalytics(")
    for cls in ('<h1 class="ph-sensitive">', 'class="qrun ph-sensitive"', '<a class="ph-sensitive" href=${`#/i/${s.id}`}'):
        assert cls in APP, cls
    agent = (STATIC / "js" / "agent.js").read_text()
    assert 'class="asked ph-sensitive"' in agent and '<span class="ph-sensitive"><b>Earlier question</b>' in agent


def test_analytics_waits_for_posthog_then_knows_the_person_by_clerk_id_only() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node isn't installed: the page's JavaScript can't be run here")
    code = f"""import * as A from {json.dumps((STATIC / 'js' / 'analytics.js').as_uri())};
const calls = [];
globalThis.window = {{ posthog: {{ init: (k, o) => calls.push(['init', k, o.api_host, o.session_recording.maskAllInputs]),
  capture: (e, p) => calls.push(['capture', e, p]), identify: u => calls.push(['identify', u]), reset: () => calls.push(['reset']) }} }};
A.track('breakdown asked', {{ breakdown_id: 'x' }});        // off: dropped
A.startAnalytics(null);                                       // no key: stays off
let done; const loaded = new Promise(r => {{ done = r; }});
A.startAnalytics('phc_k', src => {{ calls.push(['load', src]); return loaded; }});
A.track('breakdown sample opened');                           // while it loads: waits
A.accountIs('user_1');
done(); await loaded; await new Promise(r => setTimeout(r, 0));
A.accountIs('user_1'); A.accountIs(null); A.accountIs(null);
const e = A.scrub({{ properties: {{ title: '(1/4) How does X trade · Breakdowns', $title: 't', $current_url: 'u' }} }});
console.log(JSON.stringify({{ calls, e, mask: A.OPTIONS.session_recording.maskTextSelector, block: A.OPTIONS.session_recording.blockSelector }}));"""
    r = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["calls"] == [["load", "/lyr/static/array.js"], ["init", "phc_k", "/lyr", True],
                            ["identify", "user_1"], ["capture", "breakdown sample opened", None], ["reset"]]  # fmt: skip
    assert got["e"] == {"properties": {"$current_url": "u"}}  # the tab's title (it names the breakdown) never leaves
    assert ".ph-sensitive" in got["mask"] and "title" in got["mask"]
    assert all(s in got["block"] for s in (".brow > a", ".qrun", ".asked"))  # their tooltips carry the question
