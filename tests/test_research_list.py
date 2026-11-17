"""Your breakdowns (owner, 17 Nov: "can i delete a breakdown? we need better organizational ui"): each row's wallet,
name and market for the page's wallet groups and Market filter, and Delete with Undo."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from test_research import _client, _settle


def test_each_row_says_its_wallet_and_market_from_the_plan_or_the_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    c, server = _client(monkeypatch, None)
    w1, w2 = "0x" + "ab" * 20, "0x" + "CD" * 20
    try:
        named = c.post("/api/research/sessions", json={"title": "How does flawfence make money on politics markets?"}).json()["id"]
        server.store.add_message(named, "user", [{"type": "text", "text": "How does flawfence make money?\n\n"
                                                  f"Wallet: {w1} (flawfence on Polymarket)\n"
                                                  "Market: Politics (market_type politics)\nTime range: the last 90 days"}])  # fmt: skip
        typed = c.post("/api/research/sessions", json={"title": "Analyze it"}).json()["id"]
        server.store.add_message(typed, "user", [{"type": "text", "text": f"Analyze wallet {w2}'s BTC 15-minute trades"}])
        planned = c.post("/api/research/sessions", json={"title": "Planned"}).json()["id"]
        server.store.add_message(planned, "user", [{"type": "text", "text": "Market: Politics (market_type politics)"}])
        server.store.set_scope(planned, {"wallet": w1, "market_type": "btc-long"})  # the plan wins over the ask
        bare = c.post("/api/research/sessions", json={"title": "Nothing asked yet"}).json()["id"]
        rows = {r["id"]: r for r in c.get("/api/research/sessions").json()["sessions"]}
        assert {k: rows[named][k] for k in ("wallet", "name", "market")} == {"wallet": w1, "name": "flawfence", "market": "politics"}
        assert {k: rows[typed][k] for k in ("wallet", "name", "market")} == {"wallet": w2.lower(), "name": None, "market": None}
        assert (rows[planned]["wallet"], rows[planned]["market"]) == (w1, "btc-long")
        assert (rows[bare]["wallet"], rows[bare]["name"], rows[bare]["market"]) == (None, None, None)
        assert "ask" not in rows[named] and "scope" not in rows[planned]  # the question itself stays on the service
    finally:
        server.app.dependency_overrides.clear()


def test_delete_hides_a_breakdown_undo_brings_it_back_and_a_running_one_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    class Slow:
        def ask(self, sid: str, user: str, q: str, emit: Any, **kw: Any) -> None:
            emit({"type": "ask.started", "started_at": 1.0, "typical_s": None, "limit_s": 600})
            gate.wait(5)
            emit({"type": "done"})

    c, server = _client(monkeypatch, Slow())
    try:
        sid = c.post("/api/research/sessions", json={"title": "Mine"}).json()["id"]
        other = c.post("/api/research/sessions", json={"title": "Also mine"}).json()["id"]
        assert c.delete(f"/api/research/sessions/{sid}").status_code == 200
        assert [r["id"] for r in c.get("/api/research/sessions").json()["sessions"]] == [other]
        assert c.get(f"/api/research/sessions/{sid}").status_code == 404  # its page too
        assert c.post(f"/api/research/sessions/{sid}/ask", json={"question": "Go"}).status_code == 404
        server.app.dependency_overrides[server.auth.user_of] = lambda: "bob"
        assert c.post(f"/api/research/sessions/{sid}/restore").status_code == 404  # only the owner's
        assert c.delete(f"/api/research/sessions/{other}").status_code == 404
        server.app.dependency_overrides[server.auth.user_of] = lambda: "alice"
        assert c.post(f"/api/research/sessions/{sid}/restore").status_code == 200  # Undo
        assert c.get(f"/api/research/sessions/{sid}").status_code == 200

        assert c.post(f"/api/research/sessions/{other}/ask", json={"question": "Go"}).status_code == 202
        assert c.delete(f"/api/research/sessions/{other}").status_code == 409  # running: nothing stops a run yet
        gate.set()
        _settle(server)
        assert c.delete(f"/api/research/sessions/{other}").status_code == 200
    finally:
        gate.set()
        server.app.dependency_overrides.clear()
