"""The research service's HTTP API, under /api/research/ (usesignals.app forwards it here: README, "Research agent").

An investigation is a session: create one, ask in it, follow its events. Asking starts the run in a thread and
returns at once; ``/events`` streams (server-sent events) everything from a position on and follows the run live,
so a page that reloads or loses its connection picks up where it was. Every event is kept (``store.events``).

Signed in only (Clerk, as the engine); a session, its events and charts are only ever its owner's. At most
``RESEARCH_AT_ONCE`` investigations run at once (default 2), one per person.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from signals.research import auth
from signals.research.store import Store

HOSTED = os.environ.get("RESEARCH_HOSTED") == "1"
AT_ONCE = int(os.environ.get("RESEARCH_AT_ONCE", "2"))
HEARTBEAT_S = 15.0
if HOSTED and not auth.clerk_frontend_api(auth.CLERK_KEY):
    raise SystemExit("research: RESEARCH_HOSTED=1 needs CLERK_PUBLISHABLE_KEY (sign-in), refusing to start open.")

app = FastAPI(title="Signals research", docs_url=None, redoc_url=None)
store = Store()
_agent: Any = None
_running: dict[str, str] = {}  # session -> user, while a run is going
_lock = threading.Lock()
_changed = threading.Condition()


def agent() -> Any:
    global _agent
    if _agent is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise HTTPException(503, detail="Research isn't switched on here (no model key).")
        from signals.research.agent import Agent
        from signals.research.data import reads

        _agent = Agent(reads(), store)
    return _agent


def _private(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"cache-control": "no-store"})


class NewSession(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@app.get("/api/research/health")
def health() -> dict[str, Any]:
    return {"ok": True, "model_key": bool(os.environ.get("ANTHROPIC_API_KEY")), "running": len(_running)}


@app.post("/api/research/sessions")
def new_session(body: NewSession, user: str = Depends(auth.user_of)) -> JSONResponse:
    return _private({"id": store.new_session(user, body.title)}, 201)


@app.get("/api/research/sessions")
def sessions(user: str = Depends(auth.user_of)) -> JSONResponse:
    return _private({"sessions": store.sessions(user)})


def _own(sid: str, user: str) -> dict[str, Any]:
    s = store.session(sid, user)
    if not s:
        raise HTTPException(404, detail="No such investigation.")
    return s


@app.get("/api/research/sessions/{sid}")
def session(sid: str, user: str = Depends(auth.user_of)) -> JSONResponse:
    s = _own(sid, user)
    return _private({"id": sid, "title": s["title"], "created": s["created"], "running": sid in _running,
                     "events": store.events(sid)})  # fmt: skip


@app.post("/api/research/sessions/{sid}/ask")
def ask(sid: str, body: Ask, user: str = Depends(auth.user_of)) -> JSONResponse:
    _own(sid, user)
    a = agent()
    with _lock:
        if sid in _running or user in _running.values():
            raise HTTPException(409, detail="An investigation of yours is still running. Wait for it to finish.")
        if len(_running) >= AT_ONCE:
            raise HTTPException(429, detail="Research is busy right now. Try again in a minute.")
        _running[sid] = user
    after = (store.events(sid)[-1:] or [{"seq": -1}])[0]["seq"]

    def emit(event: dict[str, Any]) -> None:
        store.add_event(sid, event)
        with _changed:
            _changed.notify_all()

    def go() -> None:
        try:
            a.ask(sid, user, body.question, emit)
        finally:
            with _lock:
                _running.pop(sid, None)
            with _changed:
                _changed.notify_all()

    threading.Thread(target=go, name=f"research-{sid}", daemon=True).start()
    return _private({"started": True, "after": after}, 202)


@app.get("/api/research/sessions/{sid}/events")
def events(sid: str, request: Request, after: int = -1, user: str = Depends(auth.user_of)) -> StreamingResponse:
    """Server-sent events from ``after`` on; follows a running investigation until its ``done``."""
    _own(sid, user)

    def follow() -> Iterator[str]:
        at, last_sent = after, time.monotonic()
        while True:
            for e in store.events(sid, at):
                at = e["seq"]
                yield f"id: {at}\ndata: {json.dumps(e, default=str)}\n\n"
                last_sent = time.monotonic()
            if sid not in _running and not store.events(sid, at):
                return
            with _changed:
                _changed.wait(timeout=1.0)
            if time.monotonic() - last_sent > HEARTBEAT_S:
                yield ": still working\n\n"
                last_sent = time.monotonic()

    return StreamingResponse(follow(), media_type="text/event-stream",
                             headers={"cache-control": "no-store", "x-accel-buffering": "no"})  # fmt: skip


@app.get("/api/research/charts/{cid}")
def chart(cid: str, user: str = Depends(auth.user_of)) -> JSONResponse:
    c = store.chart(cid, user)
    if not c:
        raise HTTPException(404, detail="No such chart.")
    return _private({"id": c["id"], "title": c["title"], "caption": c["caption"], "spec": c["spec"]})


@app.get("/api/research/runs")
def runs(request: Request) -> JSONResponse:
    """The owner's: what investigations cost (tokens, dollars, rounds), locally or with RESEARCH_METRICS_KEY."""
    key = os.environ.get("RESEARCH_METRICS_KEY")
    if HOSTED and (not key or request.headers.get("authorization") != f"Bearer {key}"):
        raise HTTPException(404)
    return _private({"runs": store.runs(), "spent_today_usd": round(store.spent_today(), 4)})


@app.get("/api/research/dev", response_class=HTMLResponse)
def dev_page() -> HTMLResponse:
    """A bare page for trying the agent locally. Not the Research tab: that waits on the design."""
    if HOSTED:
        raise HTTPException(404)
    return HTMLResponse((Path(__file__).parent / "dev.html").read_text())


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("RESEARCH_PORT", "8791")))
