"""The research agent's loop: Claude Opus 5.5 with code execution, its five tools called from its code.

One ``ask`` is one question in an investigation (a session). It replays the session's conversation and code
container, so follow-ups can use what earlier turns read and computed, and streams what happens as events (see
``EVENTS``) for the page to draw as they arrive. Before the answer is shown, every number in it is checked against
what the agent read and printed (``trace``); a miss gets one chance to fix it, then the numbers still unmatched are
shown flagged, never silently.

Limits (env): ``RESEARCH_MAX_USD`` per question (default 3), ``RESEARCH_DAILY_USD`` for everyone per UTC day
(default 30), ``RESEARCH_USER_DAILY_USD`` per person (default 10), ``RESEARCH_MAX_ROUNDS`` model calls per question (default 100; each tool call from code is one)
(default 40). Costs are list prices for Opus 5.5 (code execution's container time isn't included).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from signals.research import tools as T
from signals.research import trace
from signals.research.case import CASE_TOOLS, Case, prebuild
from signals.research.case import NAMES as CASE_NAMES
from signals.research.data import Reads
from signals.research.store import Store

MODEL = os.environ.get("RESEARCH_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("RESEARCH_EFFORT", "high")
TASK_BUDGET = int(os.environ.get("RESEARCH_TASK_TOKENS", "400000"))  # Opus paces itself to this per question
MAX_TOKENS = 64_000
MAX_ROUNDS = int(os.environ.get("RESEARCH_MAX_ROUNDS", "100"))  # each call from code is a round; $ caps bind first
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
REBUILT = ("The code sandbox from earlier in this breakdown has expired, so its variables and files are gone. "
           "Read again with the tools whatever you need from earlier turns before you answer.")  # fmt: skip
BETAS = ["server-side-fallback-2026-07-01", "task-budgets-2026-03-13", "thinking-display-updates-2026-08-18"]
STDOUT_SHOWN = 4_000  # characters of a code run's output put in its event

EVENT_VERSION = 2  # 2: the case file's events (docs/research-contract.md)
WALLET_IN = re.compile(r"0x[0-9a-fA-F]{40}")
MAX_SECONDS = int(os.environ.get("RESEARCH_MAX_SECONDS", "600"))  # a question's wall-time budget
WRAP_AT = 0.8  # at this share of it the agent is told to answer from what it has
WRAP_UP = ("Time is nearly up for this question. Stop exploring: finish any finding you've counted, then call answer "
           "now from the findings so far, saying in one line what you didn't get to.")  # fmt: skip
# The phases a run's usage reports (seconds from its start): the targets for a 1-day investigation are plan < 15 s,
# all tiles < 60 s after Start, the first finding < 3 min, the answer < 8 min.
PHASES = {"plan.proposed": "plan", "window.summary": "first_tile", "finding.added": "first_finding",
          "walkthrough.ready": "walkthrough", "answer.card": "answer"}  # fmt: skip
PREBUILD_NOTE = ("\n\n(The server is already putting every window of the approved scope on the page, built from the "
                 "wallet's trades: you don't need show_windows for them; it returns their tiles at once if you want the "
                 "figures.)")  # fmt: skip
REQUEST_TIMEOUT_S = 300.0  # no bytes for this long ends a model request (streams send pings while it thinks)
SLOW_REQUEST_S = 120.0
CHECK_NOTE = "Signals' number check:"  # starts the note sent back for an untraced number; never itself a source
# The case file draws everything from data; Vega-Lite charts wait for the later "+ New view" (make_chart stays built).
DATA_TOOLS = [t for t in T.TOOLS if t["name"] != "make_chart"]


def short_title(text: str) -> str:
    """A title for the investigations list: wallets shortened (0xb945…db68), at most 120 characters."""
    return WALLET_IN.sub(lambda m: f"{m.group(0)[:6]}…{m.group(0)[-4:]}", text)[:120]
EVENTS = """start, progress (the agent's notes between steps), code (what it runs), tool_call, tool_result (a
summary: counts, coverage, errors), code_result (output), chart (a Vega-Lite spec), check (the number check),
answer, usage, error, done"""

SYSTEM = """You are Signals' research agent. Signals (usesignals.app) shows Polymarket traders' track records. A \
signed-in trader asks you to investigate a wallet, usually its trades in Bitcoin 15-minute Up/Down markets: what it \
does, when, at what prices, and what pattern explains it.

You work in a case file the trader watches: a plan, tiles for the windows, a replay of one window at a time, \
evidence cards and answer cards. You don't write a report; you drive that workspace with your tools. The server \
builds every chart and series from the data you read: you choose what to show and what it means.

# How you work
You have a Python sandbox (code_execution). The data tools (wallet_trades, wallet_profile, window, \
outside_prices) and step_status and show_windows are async functions inside it, each taking one dict and \
returning a JSON string: `data = json.loads(await wallet_trades({"wallet": w, "start": a, "end": b}))`. Their \
results go to your code, not to you: you only see what your code prints. Do the work in code and print compact, \
labelled results, never raw dumps. Run independent reads together with asyncio.gather. Variables persist between \
your code runs and between the trader's questions: reuse them instead of reading again. The workspace tools \
(propose_plan, focus, walkthrough, finding, answer, propose) you call yourself.

# The flow
- A new investigation: call propose_plan first, before reading anything, and end your turn. The trader presses \
Start (or asks for changes; then propose a new plan).
- After Start: work through the plan, marking each step running and done with step_status. The server puts the \
approved scope's windows on the page itself as soon as Start is pressed; read the wallet's trades in your code and \
group them by window for your own counting. Use show_windows only for windows outside the approved scope. Add each finding the moment you've counted it, one at a time (count one pattern, call finding, then the next; \
never save them up for a batch at the end), so the trader reads while you work: observed \
first, then inferred readings resting on them. Aim to answer within about 8 minutes; if you're told time is \
nearly up, answer at once from what you have. Pick the clearest example window: walkthrough it step by step (each step at a moment, with the fills it's \
about) and focus on it. Offer what you'd look at next with propose. Always finish with answer: the pattern in one \
or two lines, the observed and inferred lines, and the finding ids.
- If a code run comes back with an error such as "unavailable" or a timeout, that's a passing fault, not the end: \
run it again (its variables may be gone, so read again what you need). Give up only after a second failure, and \
then say so.
- Every call from your code is a round trip, so keep them few: one show_windows for all windows, step_status for \
a step's start and end, not every item. Call the workspace tools after your code has finished, never in the same \
step as a code run.
- A follow-up: answer it directly with answer (and annotations or focus when it's about a moment). If it widens \
the scope (more windows, a longer range, another wallet), call propose_plan instead and wait.
- When the trader points at something, the message carries what they pointed at, read from the data: a fill, a \
moment in a window (prices, position and nearby fills), or a finding. Answer about that. "Fix this finding" means \
rewrite it from the data with finding and its finding_id.

# The markets
A BTC 15-minute window's slug is btc-updown-15m-<start unix seconds>; it runs 900 seconds and is listed about a \
day ahead, so fills before the start are real (pre_open). "Up" pays $1 a share if Chainlink's BTC/USD at the end \
is above the window's price to beat, "Down" otherwise; the window tool gives price_to_beat, final_price and result: \
never work the result out yourself. A share's price (0 to 1) is the market's chance.
Units: Chainlink and the price to beat are US dollars (the price to beat is a 60-second average). Binance is BTC \
in USDT (Tether), usually about 0.1% away. Never compare a Binance price to the price to beat. To judge whether \
BTC was above the start, use Chainlink where it was recorded (from 10 Nov 2026 05:27 UTC); before that, measure \
Binance against its own value at the window's start and say so in plain words.
Fills: paid_ask true (liquidity "taker") means it paid the ask; false ("maker") means its resting order was \
filled below the ask: not a worse price. null means it couldn't be checked (no recorded book, a recording gap, or \
a sell). Order books exist only where Layer recorded the window (coverage.book). coverage.book_status says why \
there isn't one: "not_processed" means Layer recorded it but hasn't built it yet (say "the order book isn't \
processed yet", never that it wasn't recorded); "not_recorded" means before 2 Nov 17:00 UTC. Chainlink can come \
from Layer's raw recording even when the book isn't processed (coverage.chainlink_source). Many recorded windows have \
seconds without a book (coverage.seconds_without_book, lost): use every window for trades, fills and positions, \
and book facts only where there was a book. A finding that uses the book says how many windows or fills had one \
behind it ("in the 37 windows with a recorded book").

# A wallet's patterns, worth checking
Buying both sides (Up + Down under $1 together locks a profit; over $1 a loss); which side ends heavier and \
whether it wins; entries late in the window when the outcome is nearly decided; entries at a fixed time or before \
the open; size that scales with price; selling before the end; maker vs taker share. A window's profit: held \
winning shares pay $1, minus what was paid (the fills' usd), plus what sells brought in.

# Every number traces to data
Every number you write anywhere (findings, walkthrough steps, answers) must come from a tool result or your \
code's printed output. Print each figure before you use it, rounded the way you'll write it. The server checks at \
once and sends back any number it can't find; fix it from the data, never by guessing again.

# Wording
- Every finding and line is Observed (it's in the data, with its numbers) or Inferred (a reading of why, with what \
would confirm or refute it). Intent is never fact: no "it's a bot", "it front-runs", "it knows".
- Every number names its period and unit ("over 10 Nov 00:00–24:00 UTC"); dollars to whole cents, prices in \
cents a share (tenths only under 1¢). A figure you didn't read is left out, never estimated; one the server marks \
unverified stays marked, never hidden. Prices by their names: "Chainlink BTC/USD", "Binance BTCUSDT", "the price \
to beat", "the Up price on Polymarket"; "Binance BTCUSDT fell $74.20 below its price at the start", never a bare \
"-74.2" or "the BTC price" alone. Never "mid": say "the middle of the best bid and ask", or compare with the best \
bid or ask.
- Say what's missing in one plain sentence where it matters: a partial history, recording gaps, no Chainlink \
before 10 Nov 05:27 UTC, no order book, maker vs taker unknown. Never a disclaimer block.
- Profit is the window's or the period's, worked out from fills ("made $212 on these 52 windows after what it \
paid"). Never "ROI", "edge", "alpha", "smart money", "win streak". A past profit is never framed as something the \
trader could repeat.
- No advice, no predictions, no copying: no "you could", "worth following", "likely to keep winning", "buy when". \
"Trade", never "bet". Nothing about placing orders.
- The wallet asked about by its Polymarket name, else "Trader 0x91…76"; its full address only where the trader \
typed it. Other wallets only shortened, never named as the same person as anyone (say "likely" or "possible", \
with the evidence). No judgments of people: no "genius", "reckless", "manipulating".
- Shape: the pattern in one or two plain sentences first, then findings, then what the data doesn't show. How a \
figure was worked out only when asked, or in one clause.
- A chart or view title says plainly what's shown ("Window 10 Nov 04:30 UTC: Chainlink BTC/USD and its entries"), \
with units, and a one-sentence caption. Up and Down are sides, never good or bad; gains and losses are.
- Plain words, short paragraphs, sentence case. Times in UTC.
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
    s = trace.Sources([system], data=False)
    for m in messages:
        content = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        for b in content:
            t = b.get("type")
            if m["role"] == "user" and t == "text" and not (b.get("text") or "").startswith(CHECK_NOTE):
                s.add(b.get("text") or "", data=False)  # (the check's own note quotes the bad numbers: never a source)
            elif t == "tool_result" and not b.get("is_error"):  # an error (e.g. a bounced number) is never data
                c = b.get("content")
                s.add(c if isinstance(c, str) else json.dumps(c))
            elif (out := _code_output(b)) is not None:
                s.add(out["stdout"])
    return s


class OverBudget(Exception):
    pass


def _code_waiting(messages: list[dict[str, Any]]) -> bool:
    """True when the agent's code is paused on our tool results (then the next message may hold only those)."""
    if len(messages) < 2 or messages[-2]["role"] != "assistant" or not isinstance(messages[-2]["content"], list):
        return False
    return any(b.get("type") == "tool_use" and str((b.get("caller") or {}).get("type", "")).startswith("code_execution")
               for b in messages[-2]["content"])  # fmt: skip


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

            client = anthropic.Anthropic(max_retries=2, timeout=REQUEST_TIMEOUT_S)
        self.reads, self.store, self.client, self.model = reads, store, client, model
        self.pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="research-tool")

    def _request(self, messages: list[dict[str, Any]], container: str | None) -> dict[str, Any]:
        kw: dict[str, Any] = dict(
            model=self.model, max_tokens=MAX_TOKENS, system=SYSTEM, messages=messages,
            tools=[T.CODE_EXECUTION, *DATA_TOOLS, *CASE_TOOLS], thinking={"type": "adaptive", "display": "updates"},
            output_config={"effort": EFFORT, "task_budget": {"type": "tokens", "total": TASK_BUDGET}},
            cache_control={"type": "ephemeral"}, betas=BETAS, fallbacks="default",
        )  # fmt: skip
        if container:
            kw["container"] = container
        t0 = time.monotonic()
        try:
            with self.client.beta.messages.stream(**kw) as stream:
                out = _d(stream.get_final_message())
            took = time.monotonic() - t0
            if took > SLOW_REQUEST_S:  # 10 Nov: one resume took ~37 min (timeouts + retries); see what it was
                print(f"research: slow model request {took:.0f} s, {len(messages)} messages, "
                      f"container {container}, stop {out.get('stop_reason')}", flush=True)  # fmt: skip
            return out  # type: ignore[no-any-return]
        except Exception as e:
            if container and _container_refused(e):
                global _container_error_logged
                if not _container_error_logged:  # the API's exact words, once, to tighten _container_refused
                    _container_error_logged = True
                    print(f"research: container refused, first time: status {getattr(e, 'status_code', None)} "
                          f"body {json.dumps(getattr(e, 'body', None), default=str)[:2000]}", flush=True)  # fmt: skip
                raise ContainerGone(str(e)) from e
            raise

    def ask(self, sid: str, user: str, question: str, emit: Callable[[dict[str, Any]], None], *,
            context: dict[str, Any] | None = None, facts: dict[str, Any] | None = None,
            origin: str | None = None) -> None:  # fmt: skip
        """Answers ``question`` in session ``sid``, calling ``emit`` with each event as it happens. Every event has
        ``type`` and ``v`` (EVENT_VERSION: a page can tell a shape it doesn't know) and the question's ``run``."""
        run = self.store.start_run(sid, user)
        out = emit
        t0 = time.time()
        phases: dict[str, float] = {}  # seconds from the start to each phase (PHASES), for the usage event and logs

        def emit(e: dict[str, Any]) -> None:  # noqa: F811 - each event stamped, its phase timed
            at = round(time.time() - t0, 1)
            phase = PHASES.get(e.get("type", ""))
            if phase and phase not in phases:
                phases[phase] = at
            if e.get("type") == "window.summary":
                phases["tiles_done"] = at  # the last tile so far
            out({**e, "v": EVENT_VERSION, "run": run})

        totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        # container_from: when this question's code container was first in use (its time is billed from then).
        state = {"rounds": 0, "tool_calls": 0, "cost": 0.0, "code_runs": 0, "container_from": None, "t0": t0,
                 "wrapped": False}  # fmt: skip
        if not self.store.messages(sid):  # the investigation's first question
            w = WALLET_IN.search(question)
            emit({"type": "investigation.created", "id": sid, "title": short_title(question), "question": question,
                  "subject": {"wallet": w.group(0).lower() if w else None, "name": None}, "scope": None,
                  "origin": origin})  # fmt: skip
        emit({"type": "ask.started", "ask_id": run, "text": question, "context": context})
        pre: threading.Thread | None = None
        try:
            if self.store.spent_today() >= DAILY_USD or self.store.spent_today(user) >= USER_DAILY_USD:
                raise OverBudget("Research has reached today's limit. It resets at 00:00 UTC.")
            said = question
            if facts:  # what the user pointed at, as the server read it from the data
                said += "\n\nThe user is pointing at this (from the data):\n" + json.dumps(facts, default=str)
            scope = self.store.scope(sid) if (context or {}).get("action") == "approve" else None
            if scope and scope.get("wallet") and scope.get("from") and scope.get("to"):
                # Start: the server builds the approved scope's tiles at once, while the agent is still thinking.
                pre = threading.Thread(target=self._prebuild, args=(sid, scope, emit), name=f"prebuild-{sid}",
                                       daemon=True)  # fmt: skip
                pre.start()
                said += PREBUILD_NOTE
            ok = self._ask(sid, run, said, emit, totals, state)
            self.store.update_run(run, check_ok=int(ok))
        except OverBudget as e:
            # Never end on an error with findings and no answer: the answer is then what the findings say.
            if not self._fallback_answer(sid, run, str(e), phases, emit):
                emit({"type": "error", "message": str(e)})
            self.store.update_run(run, error="over_budget")
        except Exception as e:  # noqa: BLE001 - the page gets a sentence, the log the detail
            print(f"research: run {run} failed: {type(e).__name__}: {e}", flush=True)
            if not self._fallback_answer(sid, run, "It stopped on an error.", phases, emit):
                emit({"type": "error", "message": "The breakdown stopped on an error. Try again in a minute."})
            self.store.update_run(run, error=f"{type(e).__name__}: {e}"[:500])
        finally:
            if pre is not None and pre.is_alive():  # its tiles belong to this run's events
                pre.join(timeout=60)
            # Container time: from its first use in this question to the end, at least the billed 5 minutes. An
            # estimate (Anthropic bills execution time; a paused container waiting on our tools may count).
            used = state["container_from"] is not None
            container_s = max(CONTAINER_MIN_S, round(time.time() - state["container_from"])) if used else 0
            container_usd = container_s / 3600 * CONTAINER_USD_PER_HOUR
            usage = {**totals, "token_usd": round(state["cost"], 4), "code_runs": state["code_runs"],
                     "container_s": container_s, "container_usd": round(container_usd, 4),
                     "cost_usd": round(state["cost"] + container_usd, 4), "rounds": state["rounds"],
                     "tool_calls": state["tool_calls"], "seconds": round(time.time() - t0, 1),
                     "phases": dict(phases)}  # fmt: skip
            emit({"type": "usage", **usage})
            self.store.update_run(
                run, ended=time.time(), input_tokens=totals["input_tokens"], output_tokens=totals["output_tokens"],
                cache_read=totals["cache_read_input_tokens"], cache_write=totals["cache_creation_input_tokens"],
                cost_usd=state["cost"] + container_usd, rounds=state["rounds"], tool_calls=state["tool_calls"],
                code_runs=state["code_runs"], container_s=container_s, container_usd=container_usd,
            )  # fmt: skip
            print(f"research: run {run} session {sid} {json.dumps(usage)}", flush=True)
            emit({"type": "done"})

    def _ask(self, sid: str, run: int, question: str, emit: Callable[[dict[str, Any]], None],
             totals: dict[str, int], state: dict[str, Any]) -> bool:  # fmt: skip
        session = self.store.session_any(sid) or {}
        container = session.get("container")
        messages = self.store.messages(sid)
        if not messages:
            self.store.set_title(sid, short_title(question))
        text = {"type": "text", "text": question}
        last = messages[-1] if messages else None
        if last and last["role"] == "user" and isinstance(last["content"], list) and last["content"] \
                and all(b.get("type") == "tool_result" for b in last["content"]):  # fmt: skip
            # The last run ended on a tool's result (a plan waiting for Start): the user's words join that turn.
            last["content"].append(text)
            self.store.replace_last_message(sid, last["content"])
        else:
            messages.append({"role": "user", "content": [text]})
            self.store.add_message(sid, "user", [text])
        case = Case(sid, run, self.store, self.reads, emit, lambda: sources_of(messages))

        def rebuild() -> None:
            """A new container: the old one expired. Say so, and tell the agent to read again what it needs."""
            nonlocal container
            container = None
            self.store.set_container(sid, None)
            emit({"type": "notice", "text": "This breakdown's earlier working state had expired, so it's being "
                                             "rebuilt from the data: earlier figures are read again."})  # fmt: skip
            note = {"role": "system", "content": REBUILT}  # right after the question: a mid-conversation system message
            messages.append(note)
            self.store.add_message(sid, "system", REBUILT, hidden=True)

        if container and time.time() - (session.get("container_at") or time.time()) > CONTAINER_MAX_AGE_S:
            rebuild()
        retried = False
        while True:
            elapsed = time.time() - state["t0"]
            if elapsed >= MAX_SECONDS:
                raise OverBudget(f"The breakdown reached its {MAX_SECONDS // 60}-minute limit.")
            if elapsed >= WRAP_AT * MAX_SECONDS and not state["wrapped"] and not _code_waiting(messages):
                state["wrapped"] = True  # once: stop exploring, answer from the findings so far
                messages.append({"role": "system", "content": WRAP_UP})
                self.store.add_message(sid, "system", WRAP_UP, hidden=True)
            if state["rounds"] >= MAX_ROUNDS:
                raise OverBudget(f"The breakdown used its {MAX_ROUNDS} steps without finishing. Ask a narrower question.")
            if state["cost"] >= MAX_USD:
                raise OverBudget(f"The breakdown reached its ${MAX_USD:.2f} limit without finishing. Ask a narrower question.")
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
            # code runs: the response's own code blocks (usage.server_tool_use isn't sent for every tool version)
            state["code_runs"] += sum(b.get("type") == "server_tool_use" for b in resp.get("content") or [])
            if (resp.get("container") or {}).get("id"):
                if state["container_from"] is None:
                    state["container_from"] = time.time()
                if resp["container"]["id"] != container:
                    container = resp["container"]["id"]
                    self.store.set_container(sid, container)
            content = resp.get("content") or []
            messages.append({"role": "assistant", "content": content})
            self.store.add_message(sid, "assistant", content)
            self._emit_blocks(run, content, emit)
            stop = resp.get("stop_reason")
            if stop == "refusal":
                emit({"type": "error", "message": "The model declined this request."})
                return False
            if stop == "pause_turn":
                continue
            pending = [b for b in content if b.get("type") == "tool_use"]
            if stop == "tool_use" and pending:
                results = self._run_tools(sid, case, pending, emit, state)
                messages.append({"role": "user", "content": results})
                self.store.add_message(sid, "user", results, hidden=True)
                if case.waiting or case.answered:  # a plan waits for Start, or the answer card is out: the run ends
                    return True
                continue
            if case.answered:  # the answer tool made the card; any closing words aren't a second answer
                return True
            # No answer tool: the turn's answer is its text after the last code run or tool call (a plain card).
            last_i = max((i for i, b in enumerate(content) if b.get("type") != "text"), default=-1)
            answer = "\n\n".join(b.get("text") or "" for b in content[last_i + 1 :] if b.get("type") == "text").strip()
            src = sources_of(messages)
            flags = trace.flagged(answer, src)
            if flags and not retried:
                retried = True
                note = (f"{CHECK_NOTE} these numbers in your answer aren't in any tool result or printed "
                        f"output: {', '.join(f['value_text'] for f in flags)}. Print each figure you state from your "
                        "code (or drop it), then give the whole answer again.")  # fmt: skip
                fix = {"role": "user", "content": [{"type": "text", "text": note}]}
                messages.append(fix)
                self.store.add_message(sid, "user", fix["content"], hidden=True)
                continue
            if answer:
                emit({"type": "answer.card", "ask_id": run, "text": answer, "truncated": stop == "max_tokens",
                      "number_check": {"passed": not flags, "flagged": {"text": flags} if flags else {}}})  # fmt: skip
            return not flags

    def _prebuild(self, sid: str, scope: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> None:
        t0 = time.monotonic()
        try:
            n = prebuild(self.store, self.reads, sid, scope, emit)
            print(f"research: prebuilt {n} windows for {sid} in {time.monotonic() - t0:.1f} s", flush=True)
        except Exception as e:  # noqa: BLE001 - the agent can still show them itself
            print(f"research: prebuild for {sid} failed: {type(e).__name__}: {e}", flush=True)

    def _fallback_answer(self, sid: str, run: int, why: str, phases: dict[str, float],
                         emit: Callable[[dict[str, Any]], None]) -> bool:  # fmt: skip
        """When a run stops (time, steps, money, an error) with findings but no answer: an answer card made from the
        findings that counted (their numbers already checked), saying it stopped. False when there's nothing to say."""
        if "answer" in phases:
            return True
        fs = [f for f in self.store.findings(sid) if f.get("counts")]
        if not fs:
            return False
        def line(f: dict[str, Any]) -> str:
            stat = (f.get("stat") or {}).get("text")
            return f"{f['title']}: {stat}" if stat else str(f["title"])

        emit({"type": "answer.card", "ask_id": run, "label": "Where the breakdown got to", "partial": True,
              "observed": [line(f) for f in fs if f.get("label") == "observed"],
              "inferred": [line(f) for f in fs if f.get("label") == "inferred"],
              "annotations": [], "focus": None, "finding_ids": [f["finding_id"] for f in fs],
              "number_check": {"passed": True, "flagged": {}}})  # fmt: skip
        emit({"type": "notice", "text": f"{why} This answer is built from the findings so far; ask a narrower "
                                        "question to go further."})  # fmt: skip
        return True

    def _emit_blocks(self, run: int, content: list[dict[str, Any]], emit: Callable[[dict[str, Any]], None]) -> None:
        """The agent's notes and its code runs, as they appear in a response."""
        for b in content:
            t = b.get("type")
            if t == "thinking" and (b.get("thinking") or "").strip():
                emit({"type": "answer.progress", "ask_id": run, "text": b["thinking"]})
            elif t == "server_tool_use":
                inp = b.get("input") or {}
                emit({"type": "tool.call", "id": b.get("id"), "tool": "code", "started_at": time.time(),
                      "args": {"code": inp.get("code") or inp.get("command") or json.dumps(inp)}})  # fmt: skip
            elif (out := _code_output(b)) is not None:
                emit({"type": "tool.result", "id": b.get("tool_use_id"), "tool": "code",
                      "ok": out["return_code"] in (0, None) and not out["error"], **out,
                      "stdout": out["stdout"][:STDOUT_SHOWN], "cut": len(out["stdout"]) > STDOUT_SHOWN})  # fmt: skip

    def _run_tools(self, sid: str, case: Case, pending: list[dict[str, Any]], emit: Callable[[dict[str, Any]], None],
                   state: dict[str, Any]) -> list[dict[str, Any]]:  # fmt: skip
        """Runs the tool calls the agent (or its code) is waiting on, at once, and returns their results in order. A
        result answering code's call must be text only (programmatic tool calling)."""
        charts: list[dict[str, Any]] = []

        def save(title: str, spec: dict[str, Any], caption: str | None) -> str:
            cid = self.store.add_chart(sid, title, spec, caption)
            charts.append({"type": "chart", "chart_id": cid, "title": title, "caption": caption, "spec": spec})
            return cid

        def one(b: dict[str, Any]) -> tuple[str, bool, dict[str, Any]]:
            name, inp = b.get("name", ""), b.get("input") or {}
            if name in CASE_NAMES:
                return case.handle(name, inp)
            return T.run(name, inp, self.reads, save, store=self.store, sid=sid)

        for b in pending:
            emit({"type": "tool.call", "id": b.get("id"), "tool": b.get("name"), "started_at": time.time(),
                  "args": {k: v for k, v in (b.get("input") or {}).items() if k not in ("spec", "steps")}})  # fmt: skip
        futures = [self.pool.submit(one, b) for b in pending]
        results = []
        for b, f in zip(pending, futures, strict=True):
            text, failed, summary = f.result()
            state["tool_calls"] += 1
            emit({"type": "tool.result", "id": b.get("id"), "tool": b.get("name"), "ok": not failed,
                  "rows": summary.get("rows"), "limit_hit": summary.get("limit_hit"), "ms": summary.get("ms"),
                  "summary": summary})  # fmt: skip
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
