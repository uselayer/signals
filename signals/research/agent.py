"""The research agent's loop: Claude Opus 5.5 with code execution, its five tools called from its code.

One ``ask`` is one question in an investigation (a session). It replays the session's conversation and code
container, so follow-ups can use what earlier turns read and computed, and streams what happens as events (see
``EVENTS``) for the page to draw as they arrive. Before the answer is shown, every number in it is checked against
what the agent read and printed (``trace``); a miss gets one chance to fix it, then the numbers still unmatched are
shown flagged, never silently.

Limits (env): ``RESEARCH_MAX_USD`` per question (default 3), ``RESEARCH_DAILY_USD`` for everyone per UTC day
(default 30), ``RESEARCH_USER_DAILY_USD`` per person (default 10), ``RESEARCH_MAX_ROUNDS`` model calls per question
(default 40). Costs are list prices for Opus 5.5 (code execution's container time isn't included).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from signals.research import tools as T
from signals.research import trace
from signals.research.data import Reads
from signals.research.store import Store

MODEL = os.environ.get("RESEARCH_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("RESEARCH_EFFORT", "high")
TASK_BUDGET = int(os.environ.get("RESEARCH_TASK_TOKENS", "400000"))  # Opus paces itself to this per question
MAX_TOKENS = 64_000
MAX_ROUNDS = int(os.environ.get("RESEARCH_MAX_ROUNDS", "40"))
MAX_USD = float(os.environ.get("RESEARCH_MAX_USD", "3"))
DAILY_USD = float(os.environ.get("RESEARCH_DAILY_USD", "30"))
USER_DAILY_USD = float(os.environ.get("RESEARCH_USER_DAILY_USD", "10"))
# Opus 5.5 list prices, dollars per million tokens: input, output, cache read, cache write (5 min).
PRICE = {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0}
# Code execution is billed by execution time, 5 minutes at least, $0.05 an hour per container after the
# organization's 1,550 free hours a month (counted here at the list rate, free hours ignored).
CONTAINER_USD_PER_HOUR = 0.05
CONTAINER_MIN_S = 300
CONTAINER_MAX_AGE_S = 29 * 86_400  # containers expire 30 days after they're made: start a new one a day before
REBUILT = ("The code sandbox from earlier in this investigation has expired, so its variables and files are gone. "
           "Read again with the tools whatever you need from earlier turns before you answer.")  # fmt: skip
BETAS = ["server-side-fallback-2026-07-01", "task-budgets-2026-03-13", "thinking-display-updates-2026-08-18"]
STDOUT_SHOWN = 4_000  # characters of a code run's output put in its event

EVENT_VERSION = 1
EVENTS = """start, progress (the agent's notes between steps), code (what it runs), tool_call, tool_result (a
summary: counts, coverage, errors), code_result (output), chart (a Vega-Lite spec), check (the number check),
answer, usage, error, done"""

SYSTEM = """You are Signals' research agent. Signals (usesignals.app) shows Polymarket traders' track records. A \
signed-in trader asks you to investigate a wallet, usually its trades in Bitcoin 15-minute Up/Down markets: what it \
does, when, at what prices, and what pattern explains it.

# How you work
You have a Python sandbox (code_execution). Your data tools are async functions inside it, each taking one dict \
and returning a JSON string: `data = json.loads(await wallet_trades({"wallet": w, "start": a, "end": b}))`. Their \
results go to your code, not to you: you only see what your code prints. So do the work in code (group, join, \
count, compute) and print compact, labelled results, never raw dumps. Run several tool calls at once with \
asyncio.gather when they don't depend on each other. Variables persist between your code runs and between the \
user's questions in one investigation: reuse them instead of reading again.

# The markets
A BTC 15-minute window's slug is btc-updown-15m-<start unix seconds>; it runs 900 seconds. "Up" pays $1 a \
contract if Chainlink's BTC/USD price at the end is above the window's price to beat (Chainlink at the start), \
"Down" otherwise; the window tool gives price_to_beat, final_price and result, so never work the result out \
yourself. A contract's price (0 to 1) is the market's chance. Binance (BTCUSDT spot) is a different market from \
Chainlink and usually differs by some dollars: call each by its name, never one the other. Order books aren't \
connected yet: say so if the question needs depth.

# A wallet investigation, usually
1. wallet_profile for who it is and its all-time record (every market, Polymarket's figures).
2. wallet_trades over the range asked (default: the last 7 days; a busy wallet a day at a time). Group by window.
3. Per window: side(s) bought, entry time in seconds after the window's start, prices paid, size, sells, the \
position over time (running contracts per outcome), what was held at the end and the result, and the window's \
profit (held winning contracts pay $1; minus what was paid, plus what sells brought in). Look for: buying both \
sides (Up + Down costing under $1 together is a locked profit; over $1 a locked loss), entries late in the window \
when the outcome is nearly decided, entries at a fixed time, size that scales with price, selling before the end.
4. For the windows that show the pattern (or that the user names): window + outside_prices for that span, then \
BTC's distance from the price to beat at each entry.
5. make_chart for what makes the pattern visible. For one window, a vconcat sharing the time axis: (a) BTC on \
Binance as a line, Chainlink if available, the price to beat as a horizontal rule, the wallet's entries as points \
(colour = side); (b) Up and Down prices with the entries; (c) the position as a step line per outcome. Across \
windows: e.g. win rate or profit by entry minute, entry price vs result.

# Every number traces to data
Every number you write must come from a tool result or from your code's printed output. Before your final answer, \
print every figure you'll state. A checker rejects answers with numbers it can't find in that data. Don't round \
in your head: print the rounded figure.

# How you answer
- Lead with one or two plain sentences: the pattern in short.
- Then the findings, each marked Observed (it's in the data: say what, with the numbers) or Inferred (your reading \
of why they trade this way: intent is always a guess, so say what would confirm or refute it).
- Then what the data doesn't show or covers only partly: trades cut off (complete false), coverage gaps, Chainlink \
or order books not available, maker vs taker unknown. Never fill a gap with a guess.
- Plain words, short. Say "trade", never "bet". No advice on what to trade, no predictions, never that copying \
anyone makes money. Other wallets appear only shortened (0x91…76). Times in UTC.
"""


def _d(x: Any) -> Any:
    """An API object as plain JSON (what the API accepts back); dicts pass through."""
    if hasattr(x, "to_dict"):
        return x.to_dict(mode="json")
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json", exclude_none=True)
    return x


def _cost(u: dict[str, Any]) -> float:
    return (
        (u.get("input_tokens") or 0) * PRICE["input"] + (u.get("output_tokens") or 0) * PRICE["output"]
        + (u.get("cache_read_input_tokens") or 0) * PRICE["cache_read"]
        + (u.get("cache_creation_input_tokens") or 0) * PRICE["cache_write"]
    ) / 1e6  # fmt: skip


def _code_output(block: dict[str, Any]) -> dict[str, Any] | None:
    """A code run's result (code_execution_tool_result or the bash variant): stdout, stderr, return code."""
    if not str(block.get("type", "")).endswith("code_execution_tool_result"):
        return None
    c = block.get("content") or {}
    return {"stdout": c.get("stdout") or "", "stderr": c.get("stderr") or "", "return_code": c.get("return_code"),
            "error": c.get("error_code")}  # fmt: skip


def sources_of(messages: list[dict[str, Any]], system: str = SYSTEM) -> trace.Sources:
    """What numbers in an answer may trace to: the instructions, what the user wrote, every tool result and every
    code run's output. Not the agent's own text, thinking or code (it would vouch for itself)."""
    s = trace.Sources([system])
    for m in messages:
        content = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        for b in content:
            t = b.get("type")
            if m["role"] == "user" and t == "text":
                s.add(b.get("text") or "")
            elif t == "tool_result":
                c = b.get("content")
                s.add(c if isinstance(c, str) else json.dumps(c))
            elif (out := _code_output(b)) is not None:
                s.add(out["stdout"])
    return s


class OverBudget(Exception):
    pass


class ContainerGone(Exception):
    """The API refused the session's code container (expired or unknown)."""


_container_error_logged = False


def _container_refused(e: Exception) -> bool:
    """An API error saying the container named can't be used (a 400 or 404 about the container)."""
    return getattr(e, "status_code", None) in (400, 404) and "container" in str(e).lower()


class Agent:
    def __init__(self, reads: Reads, store: Store, client: Any = None, *, model: str = MODEL) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic(max_retries=3)
        self.reads, self.store, self.client, self.model = reads, store, client, model
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="research-tool")

    def _request(self, messages: list[dict[str, Any]], container: str | None) -> dict[str, Any]:
        kw: dict[str, Any] = dict(
            model=self.model, max_tokens=MAX_TOKENS, system=SYSTEM, messages=messages,
            tools=[T.CODE_EXECUTION, *T.TOOLS], thinking={"type": "adaptive", "display": "updates"},
            output_config={"effort": EFFORT, "task_budget": {"type": "tokens", "total": TASK_BUDGET}},
            cache_control={"type": "ephemeral"}, betas=BETAS, fallbacks="default",
        )  # fmt: skip
        if container:
            kw["container"] = container
        try:
            with self.client.beta.messages.stream(**kw) as stream:
                return _d(stream.get_final_message())  # type: ignore[no-any-return]
        except Exception as e:
            if container and _container_refused(e):
                global _container_error_logged
                if not _container_error_logged:  # the API's exact words, once, to tighten _container_refused
                    _container_error_logged = True
                    print(f"research: container refused, first time: status {getattr(e, 'status_code', None)} "
                          f"body {json.dumps(getattr(e, 'body', None), default=str)[:2000]}", flush=True)  # fmt: skip
                raise ContainerGone(str(e)) from e
            raise

    def ask(self, sid: str, user: str, question: str, emit: Callable[[dict[str, Any]], None]) -> None:
        """Answers ``question`` in session ``sid``, calling ``emit`` with each event as it happens. Every event has
        ``type`` and ``v`` (EVENT_VERSION: a page can tell a shape it doesn't know) and the question's ``run``."""
        run = self.store.start_run(sid, user)
        out = emit

        def emit(e: dict[str, Any]) -> None:  # noqa: F811 - each event stamped
            out({**e, "v": EVENT_VERSION, "run": run})

        totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        # container_from: when this question's code container was first in use (its time is billed from then).
        state = {"rounds": 0, "tool_calls": 0, "cost": 0.0, "code_runs": 0, "container_from": None}
        emit({"type": "start", "question": question})
        try:
            if self.store.spent_today() >= DAILY_USD or self.store.spent_today(user) >= USER_DAILY_USD:
                raise OverBudget("Research has reached today's limit. It resets at 00:00 UTC.")
            ok = self._ask(sid, question, emit, totals, state)
            self.store.update_run(run, check_ok=int(ok))
        except OverBudget as e:
            emit({"type": "error", "message": str(e)})
            self.store.update_run(run, error="over_budget")
        except Exception as e:  # noqa: BLE001 - the page gets a sentence, the log the detail
            print(f"research: run {run} failed: {type(e).__name__}: {e}", flush=True)
            emit({"type": "error", "message": "The investigation stopped on an error. Try again in a minute."})
            self.store.update_run(run, error=f"{type(e).__name__}: {e}"[:500])
        finally:
            # Container time: from its first use in this question to the end, at least the billed 5 minutes. An
            # estimate (Anthropic bills execution time; a paused container waiting on our tools may count).
            used = state["container_from"] is not None
            container_s = max(CONTAINER_MIN_S, round(time.time() - state["container_from"])) if used else 0
            container_usd = container_s / 3600 * CONTAINER_USD_PER_HOUR
            usage = {**totals, "token_usd": round(state["cost"], 4), "code_runs": state["code_runs"],
                     "container_s": container_s, "container_usd": round(container_usd, 4),
                     "cost_usd": round(state["cost"] + container_usd, 4), "rounds": state["rounds"],
                     "tool_calls": state["tool_calls"]}  # fmt: skip
            emit({"type": "usage", **usage})
            self.store.update_run(
                run, ended=time.time(), input_tokens=totals["input_tokens"], output_tokens=totals["output_tokens"],
                cache_read=totals["cache_read_input_tokens"], cache_write=totals["cache_creation_input_tokens"],
                cost_usd=state["cost"] + container_usd, rounds=state["rounds"], tool_calls=state["tool_calls"],
                code_runs=state["code_runs"], container_s=container_s, container_usd=container_usd,
            )  # fmt: skip
            print(f"research: run {run} session {sid} {json.dumps(usage)}", flush=True)
            emit({"type": "done"})

    def _ask(self, sid: str, question: str, emit: Callable[[dict[str, Any]], None],
             totals: dict[str, int], state: dict[str, Any]) -> bool:  # fmt: skip
        session = self.store.session_any(sid) or {}
        container = session.get("container")
        messages = self.store.messages(sid)
        if not messages:
            self.store.set_title(sid, question[:120])
        user_msg = {"role": "user", "content": [{"type": "text", "text": question}]}
        messages.append(user_msg)
        self.store.add_message(sid, "user", user_msg["content"])

        def rebuild() -> None:
            """A new container: the old one expired. Say so, and tell the agent to read again what it needs."""
            nonlocal container
            container = None
            self.store.set_container(sid, None)
            emit({"type": "notice", "text": "This investigation's earlier working state had expired, so it's being "
                                             "rebuilt from the data: earlier figures are read again."})  # fmt: skip
            note = {"role": "system", "content": REBUILT}  # right after the question: a mid-conversation system message
            messages.append(note)
            self.store.add_message(sid, "system", REBUILT, hidden=True)

        if container and time.time() - (session.get("container_at") or time.time()) > CONTAINER_MAX_AGE_S:
            rebuild()
        retried = False
        while True:
            if state["rounds"] >= MAX_ROUNDS:
                raise OverBudget(f"The investigation used its {MAX_ROUNDS} steps without finishing. Ask a narrower question.")
            if state["cost"] >= MAX_USD:
                raise OverBudget(f"The investigation reached its ${MAX_USD:.2f} limit without finishing. Ask a narrower question.")
            try:
                resp = self._request(messages, container)
            except ContainerGone:
                last = messages[-1]["content"]
                if isinstance(last, list) and last and all(b.get("type") == "tool_result" for b in last):
                    # Code was waiting on our tool results in it: that step can't be resumed anywhere else.
                    container = None
                    self.store.set_container(sid, None)
                    raise
                print(f"research: session {sid} container expired; starting a new one", flush=True)
                rebuild()
                continue
            state["rounds"] += 1
            u = resp.get("usage") or {}
            for k in totals:
                totals[k] += int(u.get(k) or 0)
            state["cost"] = _cost(totals)
            state["code_runs"] += int((u.get("server_tool_use") or {}).get("code_execution_requests") or 0)
            if (resp.get("container") or {}).get("id"):
                if state["container_from"] is None:
                    state["container_from"] = time.time()
                if resp["container"]["id"] != container:
                    container = resp["container"]["id"]
                    self.store.set_container(sid, container)
            content = resp.get("content") or []
            messages.append({"role": "assistant", "content": content})
            self.store.add_message(sid, "assistant", content)
            self._emit_blocks(content, emit)
            stop = resp.get("stop_reason")
            if stop == "refusal":
                emit({"type": "error", "message": "The model declined this request."})
                return False
            if stop == "pause_turn":
                continue
            pending = [b for b in content if b.get("type") == "tool_use"]
            if stop == "tool_use" and pending:
                results = self._run_tools(sid, pending, emit, state)
                messages.append({"role": "user", "content": results})
                self.store.add_message(sid, "user", results, hidden=True)
                continue
            # The turn's answer: its text after the last code run or tool call.
            last = max((i for i, b in enumerate(content) if b.get("type") != "text"), default=-1)
            answer = "\n\n".join(b.get("text") or "" for b in content[last + 1 :] if b.get("type") == "text").strip()
            check = trace.check(answer, sources_of(messages))
            if not check["ok"] and not retried:
                retried = True
                emit({"type": "check", **check, "retrying": True})
                note = ("Signals' number check: these numbers in your answer aren't in any tool result or printed "
                        f"output: {', '.join(check['unmatched'])}. Print each figure you state from your code (or "
                        "drop it), then give the whole answer again.")  # fmt: skip
                fix = {"role": "user", "content": [{"type": "text", "text": note}]}
                messages.append(fix)
                self.store.add_message(sid, "user", fix["content"], hidden=True)
                continue
            emit({"type": "check", **check, "retrying": False})
            emit({"type": "answer", "text": answer, "unverified": check["unmatched"], "truncated": stop == "max_tokens"})
            return bool(check["ok"])

    def _emit_blocks(self, content: list[dict[str, Any]], emit: Callable[[dict[str, Any]], None]) -> None:
        for b in content:
            t = b.get("type")
            if t == "thinking" and (b.get("thinking") or "").strip():
                emit({"type": "progress", "text": b["thinking"]})
            elif t == "server_tool_use":
                inp = b.get("input") or {}
                emit({"type": "code", "id": b.get("id"), "code": inp.get("code") or inp.get("command") or json.dumps(inp)})
            elif (out := _code_output(b)) is not None:
                emit({"type": "code_result", "id": b.get("tool_use_id"), **out,
                      "stdout": out["stdout"][:STDOUT_SHOWN], "cut": len(out["stdout"]) > STDOUT_SHOWN})  # fmt: skip

    def _run_tools(self, sid: str, pending: list[dict[str, Any]], emit: Callable[[dict[str, Any]], None],
                   state: dict[str, Any]) -> list[dict[str, Any]]:  # fmt: skip
        """Runs the tool calls the agent's code is waiting on, at once, and returns their results in order. A result
        answering code's call must be text only (programmatic tool calling)."""
        charts: list[dict[str, Any]] = []

        def save(title: str, spec: dict[str, Any], caption: str | None) -> str:
            cid = self.store.add_chart(sid, title, spec, caption)
            charts.append({"type": "chart", "chart_id": cid, "title": title, "caption": caption, "spec": spec})
            return cid

        for b in pending:
            emit({"type": "tool_call", "id": b.get("id"), "name": b.get("name"),
                  "input": {k: v for k, v in (b.get("input") or {}).items() if k != "spec"}})  # fmt: skip
        futures = [self.pool.submit(T.run, b.get("name", ""), b.get("input") or {}, self.reads, save,
                                    store=self.store, sid=sid) for b in pending]  # fmt: skip
        results = []
        for b, f in zip(pending, futures, strict=True):
            text, failed, summary = f.result()
            state["tool_calls"] += 1
            emit({"type": "tool_result", "id": b.get("id"), "name": b.get("name"), "ok": not failed, **summary})
            r: dict[str, Any] = {"type": "tool_result", "tool_use_id": b["id"], "content": text}
            if failed:
                r["is_error"] = True
            results.append(r)
        for c in charts:
            emit(c)
        return results


def stream(agent: Agent, sid: str, user: str, question: str) -> Iterator[dict[str, Any]]:
    """``ask`` as a generator (the CLI and tests); the server runs ``ask`` in a thread instead."""
    out: list[dict[str, Any]] = []
    agent.ask(sid, user, question, out.append)
    yield from out
