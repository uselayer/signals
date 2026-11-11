"""A second breakdown while the first works (Drew, 10 Nov): its plan comes back at once, and its Start waits its turn
and starts by itself when the first ends. A restart turns a waiting Start back into a plan to Start."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("RESEARCH_STORE_DIR", tempfile.mkdtemp(prefix="research-test-"))

from signals.research import server  # noqa: E402
from signals.research.store import Store  # noqa: E402


class Gated:
    """A fake agent: records each run; a run in a session with a gate waits for it."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []
        self.gates: dict[str, threading.Event] = {}

    def ask(self, sid: str, user: str, q: str, emit: Any, **kw: Any) -> None:
        self.asked.append((sid, q))
        emit({"type": "ask.started", "started_at": time.time(), "limit_s": 600})
        if sid in self.gates:
            self.gates[sid].wait(5)
        emit({"type": "done"})


def _wait(cond: Any) -> None:
    for _ in range(300):
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Any:
    agent = Gated()
    monkeypatch.setattr(server, "store", Store(os.path.join(tempfile.mkdtemp(), "q.db")))
    monkeypatch.setattr(server, "_agent", agent)
    monkeypatch.setattr(server, "_queue", [])
    monkeypatch.setattr(server, "_reads", object())  # questions here carry no context: nothing is read for them
    server.app.dependency_overrides[server.auth.user_of] = lambda: "alice"
    yield TestClient(server.app), agent
    for g in agent.gates.values():
        g.set()
    _wait(lambda: not server._running)
    server.app.dependency_overrides.clear()


def _plan(sid: str, plan_id: str = "plan-1") -> None:
    server.store.add_event(sid, {"type": "plan.proposed", "plan_id": plan_id, "steps": [{"id": "s"}]})


def test_a_second_breakdown_plans_now_and_its_start_waits_its_turn(svc: Any) -> None:
    c, agent = svc
    first = c.post("/api/research/sessions", json={"title": "First"}).json()["id"]
    agent.gates[first] = threading.Event()
    _plan(first)
    assert c.post(f"/api/research/sessions/{first}/plan", json={"plan_id": "plan-1", "action": "approve"}).status_code == 202
    _wait(lambda: first in server._running)

    second = c.post("/api/research/sessions", json={"title": "Second"}).json()["id"]
    r = c.post(f"/api/research/sessions/{second}/ask", json={"question": "How does 0xab trade?"})
    assert r.status_code == 202  # a new breakdown's first question drafts its plan beside the first one
    _wait(lambda: second not in server._running)
    assert c.post(f"/api/research/sessions/{second}/ask", json={"question": "And Nov 9?"}).status_code == 409  # not a first question

    _plan(second)
    r = c.post(f"/api/research/sessions/{second}/plan", json={"plan_id": "plan-1", "action": "approve"})
    assert r.status_code == 202 and r.json()["queued"] is True and r.json()["started"] is False
    kinds = [e["type"] for e in server.store.events(second)]
    assert kinds[-1] == "plan.queued" and "plan.answered" not in kinds
    assert c.post(f"/api/research/sessions/{second}/plan", json={"plan_id": "plan-1", "action": "approve"}).status_code == 409
    rows = {x["id"]: x for x in c.get("/api/research/sessions").json()["sessions"]}
    assert rows[second]["queued"] is True and rows[first]["running"] is True

    agent.gates[first].set()  # the first ends: the second's Start begins by itself
    _wait(lambda: (second, "Start the plan.") in agent.asked)
    _wait(lambda: second not in server._running)
    kinds = [e["type"] for e in server.store.events(second)]
    assert kinds.index("plan.queued") < kinds.index("plan.answered") < len(kinds)
    assert server._queue == []


def test_three_waiting_at_most_and_a_restart_puts_them_back_to_start(svc: Any) -> None:
    c, agent = svc
    first = c.post("/api/research/sessions", json={}).json()["id"]
    agent.gates[first] = threading.Event()
    _plan(first)
    c.post(f"/api/research/sessions/{first}/plan", json={"plan_id": "plan-1", "action": "approve"})
    _wait(lambda: first in server._running)
    waiting = []
    for _ in range(server.MAX_QUEUED + 1):
        sid = c.post("/api/research/sessions", json={}).json()["id"]
        _plan(sid)
        waiting.append((sid, c.post(f"/api/research/sessions/{sid}/plan", json={"plan_id": "plan-1", "action": "approve"})))
    assert [r.status_code for _, r in waiting] == [202] * server.MAX_QUEUED + [429]

    server._queue.clear()  # what a restart does to the queue
    assert server.unqueue_stale() == server.MAX_QUEUED
    for sid, _ in waiting[: server.MAX_QUEUED]:
        last = server.store.events(sid)[-1]
        assert last["type"] == "plan.unqueued" and "Press Start again" in last["text"]
    assert server.unqueue_stale() == 0  # told once
    agent.gates[first].set()
    _wait(lambda: not server._running)
    sid = waiting[0][0]  # its plan can be Started again
    assert c.post(f"/api/research/sessions/{sid}/plan", json={"plan_id": "plan-1", "action": "approve"}).status_code == 202
