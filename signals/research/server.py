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
import signal
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from signals.research import auth
from signals.research.store import Store

HOSTED = os.environ.get("RESEARCH_HOSTED") == "1"
AT_ONCE = int(os.environ.get("RESEARCH_AT_ONCE", "2"))
HEARTBEAT_S = 15.0
if HOSTED and not auth.clerk_frontend_api(auth.CLERK_KEY):
    raise SystemExit("research: RESEARCH_HOSTED=1 needs CLERK_PUBLISHABLE_KEY (sign-in), refusing to start open.")

store = Store()


def recover() -> int:
    """Runs the store still has as running died with the last process (a deploy replaced the container): each ends
    as interrupted, its findings so far kept as a partial answer (``agent.recover``)."""
    from signals.research.agent import recover as close_unfinished

    return close_unfinished(store)


def interrupt_all() -> int:
    """Shutdown: every running breakdown writes where it got to and ends now, so its page never stays "Working"."""
    return _agent.stop_all() if _agent is not None else 0


def _on_sigterm() -> None:
    """Before uvicorn's own SIGTERM handling (which waits for open event streams), end the running breakdowns: their
    streams then close at once. Bounded, so a stuck write can't hold up the exit; a run the process dies in anyway is
    closed by ``recover`` at the next start."""
    if threading.current_thread() is not threading.main_thread():
        return
    previous = signal.getsignal(signal.SIGTERM)

    def handle(sig: int, frame: Any) -> None:
        from signals.research.agent import STOP_WAIT_S

        t = threading.Thread(target=interrupt_all, name="research-shutdown", daemon=True)
        t.start()
        t.join(timeout=STOP_WAIT_S + 1)
        if callable(previous):
            previous(sig, frame)
        else:  # nothing else was listening: exit as the signal would have
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, handle)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    n = recover()
    if n:
        print(f"research: closed {n} breakdowns the last process was running", flush=True)
    _on_sigterm()  # uvicorn has installed its handlers by now: this one runs first, then hands over
    yield


app = FastAPI(title="Signals research", docs_url=None, redoc_url=None, lifespan=lifespan)
_agent: Any = None
_reads: Any = None  # the service's reads when no agent is running yet (tests set it)
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
    context: dict[str, Any] | None = None  # {trade_id} | {window_id, t} | {finding_id[, stat]}
    origin: str | None = Field(default=None, max_length=40)  # where it started: pasted wallet, trader page, alert…


class PlanAnswer(BaseModel):
    plan_id: str
    action: Literal["approve", "edit"]
    text: str | None = Field(default=None, max_length=2000)
    scope_option_ids: list[str] | None = None


class ProposalAnswer(BaseModel):
    action: Literal["accept", "decline"]


@app.get("/api/research/health")
def health() -> dict[str, Any]:
    return {"ok": True, "model_key": bool(os.environ.get("ANTHROPIC_API_KEY")), "running": len(_running)}


@app.get("/api/research/config")
def config() -> dict[str, Any]:
    """What the research page needs before it draws: Clerk's publishable key (the engine's, same domain) and the
    event version it speaks."""
    from signals.research.agent import EVENT_VERSION

    return {"clerk_key": auth.CLERK_KEY or None, "event_version": EVENT_VERSION}


@app.post("/api/research/sessions")
def new_session(body: NewSession, user: str = Depends(auth.user_of)) -> JSONResponse:
    return _private({"id": store.new_session(user, body.title)}, 201)


@app.get("/api/research/sessions")
def sessions(user: str = Depends(auth.user_of)) -> JSONResponse:
    return _private({"sessions": store.sessions(user)})


def _own(sid: str, user: str) -> dict[str, Any]:
    s = store.session(sid, user)
    if not s:
        raise HTTPException(404, detail="No such breakdown.")
    return s


@app.get("/api/research/sessions/{sid}")
def session(sid: str, user: str = Depends(auth.user_of)) -> JSONResponse:
    s = _own(sid, user)
    return _private({"id": sid, "title": s["title"], "created": s["created"], "running": sid in _running,
                     "events": store.events(sid)})  # fmt: skip


def _emit(sid: str, event: dict[str, Any]) -> None:
    from signals.research.agent import EVENT_VERSION

    store.add_event(sid, {"v": EVENT_VERSION, "run": None, **event})
    with _changed:
        _changed.notify_all()


def start_run(sid: str, user: str, text: str, *, context: dict[str, Any] | None = None,
              facts: dict[str, Any] | None = None, origin: str | None = None) -> JSONResponse:  # fmt: skip
    """Starts one run (a question, a Start, an accepted proposal) in a thread; 202 with the event position."""
    a = agent()
    with _lock:
        if sid in _running or user in _running.values():
            raise HTTPException(409, detail="A breakdown of yours is still running. Wait for it to finish.")
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
            a.ask(sid, user, text, emit, context=context, facts=facts, origin=origin)
        finally:
            with _lock:
                _running.pop(sid, None)
            with _changed:
                _changed.notify_all()

    threading.Thread(target=go, name=f"research-{sid}", daemon=True).start()
    return _private({"started": True, "after": after}, 202)


@app.post("/api/research/sessions/{sid}/ask")
def ask(sid: str, body: Ask, user: str = Depends(auth.user_of)) -> JSONResponse:
    """A question, optionally about something on the page (``context``: {trade_id} | {window_id, t} |
    {finding_id[, stat]}), which the server turns into facts from the data before the agent sees it."""
    from signals.research.case import resolve_context
    from signals.research.data import ReadError

    _own(sid, user)
    try:
        facts = resolve_context(store, _reads or agent().reads, sid, body.context)
    except ReadError as e:
        raise HTTPException(404, detail=str(e)) from e
    return start_run(sid, user, body.question, context=body.context, facts=facts, origin=body.origin)


def _latest(sid: str, kind: str, key: str, value: str) -> dict[str, Any] | None:
    return next((e for e in reversed(store.events(sid)) if e.get("type") == kind and e.get(key) == value), None)


@app.post("/api/research/sessions/{sid}/plan")
def plan(sid: str, body: PlanAnswer, user: str = Depends(auth.user_of)) -> JSONResponse:
    """Start a proposed plan (``approve``, with any scope options ticked) or ask for a different one (``edit``)."""
    _own(sid, user)
    p = _latest(sid, "plan.proposed", "plan_id", body.plan_id)
    if p is None:
        raise HTTPException(404, detail="No such plan.")
    if _latest(sid, "plan.answered", "plan_id", body.plan_id):
        raise HTTPException(409, detail="This plan was already started or changed.")
    if body.action == "edit" and not (body.text or "").strip():
        raise HTTPException(400, detail="Say what to change.")
    chosen = [o for o in p.get("scope_options") or [] if o.get("id") in set(body.scope_option_ids or [])]
    if body.action == "approve":
        text = "Start the plan." + "".join(f"\nAlso: {o.get('text')}" for o in chosen)
    else:
        text = f"Change the plan: {body.text}"
    started = start_run(sid, user, text, context={"plan_id": body.plan_id, "action": body.action})
    _emit(sid, {"type": "plan.answered", "plan_id": body.plan_id, "action": body.action,
                "scope_option_ids": [o.get("id") for o in chosen], "text": body.text})  # fmt: skip
    return started


@app.post("/api/research/sessions/{sid}/proposals/{pid}")
def proposal(sid: str, pid: str, body: ProposalAnswer, user: str = Depends(auth.user_of)) -> JSONResponse:
    """Accept a proposal (a run) or decline it (no run)."""
    _own(sid, user)
    p = _latest(sid, "proposal", "proposal_id", pid)
    if p is None:
        raise HTTPException(404, detail="No such proposal.")
    if _latest(sid, "proposal.answered", "proposal_id", pid):
        raise HTTPException(409, detail="This proposal was already answered.")
    if body.action == "decline":
        _emit(sid, {"type": "proposal.answered", "proposal_id": pid, "action": "decline"})
        return _private({"started": False}, 200)
    started = start_run(sid, user, f"Yes, go ahead: {p.get('text')}", context={"proposal_id": pid})
    _emit(sid, {"type": "proposal.answered", "proposal_id": pid, "action": "accept"})
    return started


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


@app.get("/api/research/sessions/{sid}/findings")
def findings(sid: str, user: str = Depends(auth.user_of)) -> JSONResponse:
    """The investigation's evidence cards, latest version each (with ``history``), and how many count."""
    _own(sid, user)
    fs = store.findings(sid)
    return _private({"findings": fs, "counted": sum(bool(f.get("counts")) for f in fs)})


@app.get("/api/research/sessions/{sid}/windows")
def windows(sid: str, user: str = Depends(auth.user_of)) -> JSONResponse:
    """The investigation's window tiles (``window.summary``) and its coverage per source."""
    from signals.research import workspace

    _own(sid, user)
    tiles = store.summaries(sid)
    readies = [store.window(sid, t["window_id"])["ready"] or {} for t in tiles]
    for t, r in zip(tiles, readies, strict=True):  # tiles kept before they carried Chainlink: from the kept replay
        if "chainlink_spark" not in t and r:
            t["chainlink_spark"] = workspace.chainlink_spark(r)
    covs = [r for r in readies if r]
    return _private({"windows": tiles, "coverage": workspace.totals([r["coverage"] for r in covs])})


@app.get("/api/research/sessions/{sid}/windows/{slug}")
def window(sid: str, slug: str, user: str = Depends(auth.user_of)) -> JSONResponse:
    """One window's full replay (``window.ready``): kept, else built now from what the investigation read."""
    from signals.research import workspace

    _own(sid, user)
    kept = store.window(sid, slug)["ready"]
    if kept is None:
        if not (store.session_any(sid) or {}).get("wallet"):
            raise HTTPException(404, detail="This breakdown hasn't read a wallet yet.")
        from signals.research.data import ReadError, reads

        try:
            kept = workspace.build(store, _reads or reads(), sid, slug)
        except ReadError as e:
            raise HTTPException(404, detail=str(e)) from e
    return _private(kept)


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


# The research UI (signals/research/static/), at /research on usesignals.app through Vercel rewrites (README).
app.mount("/research", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="research")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("RESEARCH_PORT", "8791")))
