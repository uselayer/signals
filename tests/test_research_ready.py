"""A breakdown that finished while you were away (Drew, 10 Nov): the research service's list says which ended and how,
and a Started plan that ran to its end asks the engine to send "Your breakdown is ready" on Telegram."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("RESEARCH_STORE_DIR", tempfile.mkdtemp(prefix="research-test-"))

from signals import app as engine  # noqa: E402
from signals.research import server  # noqa: E402
from signals.research.store import Store  # noqa: E402


class Telegram:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, **p: Any) -> dict[str, Any]:
        self.calls.append({"method": method} | p)
        return {}


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> Telegram:
    t = Telegram()
    monkeypatch.setattr(engine, "tg", t)
    monkeypatch.setattr(engine, "TG_TOKEN", "token")
    monkeypatch.setattr(engine, "RESEARCH_NOTIFY_KEY", "k-123")
    (engine.STORE_DIR / "follows.json").write_text(json.dumps({"users": {
        "user_a": {"follows": [], "chat": 4242}, "user_b": {"follows": [], "chat": None}}}))  # fmt: skip
    return t


def _ready(c: TestClient, key: str | None, **body: Any) -> Any:
    headers = {"authorization": f"Bearer {key}"} if key else {}
    return c.post("/api/research-ready", json={"user": "user_a", "id": "Tmkt3YXx4-2Yp0Ny", "title": "How <b>X</b> trades",
                                               "findings": 3, **body}, headers=headers)  # fmt: skip


def test_the_engine_sends_ready_only_with_the_key_and_a_connected_chat(bot: Telegram, monkeypatch: pytest.MonkeyPatch) -> None:
    c = TestClient(engine.app)
    assert _ready(c, None).status_code == 404 and _ready(c, "wrong").status_code == 404  # looks like nothing's here
    assert bot.calls == []
    r = _ready(c, "k-123")
    assert r.status_code == 200 and r.json() == {"sent": True}
    (call,) = bot.calls
    assert call["method"] == "sendMessage" and call["chat_id"] == "4242"
    assert call["text"] == "<b>Your breakdown is ready ✓</b>\nHow &lt;b&gt;X&lt;/b&gt; trades\n3 findings"
    button = call["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Open breakdown", "url": f"{engine.SITE}/breakdowns/#/i/Tmkt3YXx4-2Yp0Ny"}
    assert _ready(c, "k-123", user="user_b").json() == {"sent": False}  # no Telegram connected: nothing sent
    assert _ready(c, "k-123", user="nobody").json() == {"sent": False}
    assert _ready(c, "k-123", id="../../x").status_code == 400
    assert len(bot.calls) == 1
    assert engine.ready_text("", 1) == "<b>Your breakdown is ready ✓</b>\n1 finding"
    assert engine.ready_text("T", 0) == "<b>Your breakdown is ready ✓</b>\nT"
    monkeypatch.setattr(engine, "RESEARCH_NOTIFY_KEY", "")
    assert _ready(c, "").status_code == 404  # off without the key, whatever is sent


def test_the_list_says_when_each_ended_and_a_clean_start_asks_for_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store(os.path.join(tempfile.mkdtemp(), "s.db"))
    monkeypatch.setattr(server, "store", store)
    clean, failed, never = (store.new_session("u1", t) for t in ("Clean", "Failed", "Never ran"))
    for sid, error in ((clean, None), (failed, "over_budget")):
        run = store.start_run(sid, "u1")
        store.update_run(run, ended=1794300000.0 + (run * 10), error=error)
    store.add_event(clean, {"type": "finding.added", "finding_id": "F1", "counts": True})
    store.add_event(clean, {"type": "finding.added", "finding_id": "F2", "counts": False})  # flagged: not counted
    store.add_event(clean, {"type": "finding.updated", "finding_id": "F1"})
    last = store.last_runs("u1")
    assert last[clean]["error"] is None and last[failed]["error"] == "over_budget" and never not in last

    server.app.dependency_overrides[server.auth.user_of] = lambda: "u1"
    try:
        rows = {r["id"]: r for r in TestClient(server.app).get("/api/research/sessions").json()["sessions"]}
    finally:
        server.app.dependency_overrides.clear()
    assert rows[clean]["ended"] and "stopped" not in rows[clean]
    assert rows[failed]["stopped"] == "over_budget"
    assert "ended" not in rows[never] and "running" not in rows[never]

    sent: list[Any] = []

    class Answer:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

        def read(self) -> bytes:
            return b'{"sent": true}'

    def urlopen(req: Any, timeout: float) -> Answer:
        sent.append((req.full_url, dict(req.header_items()), json.loads(req.data)))
        return Answer()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.delenv("RESEARCH_NOTIFY_KEY", raising=False)
    assert server.tell_ready(clean, "u1") is False and sent == []  # off without the key
    monkeypatch.setenv("RESEARCH_NOTIFY_KEY", "k-123")
    assert server.tell_ready(failed, "u1") is False and server.tell_ready(never, "u1") is False and sent == []
    assert server.tell_ready(clean, "u1") is True
    ((url, headers, body),) = sent
    assert url.endswith("/api/research-ready") and headers["Authorization"] == "Bearer k-123"
    assert body == {"user": "u1", "id": clean, "title": "Clean", "findings": 1}
