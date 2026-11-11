"""The research page (signals/research/static/): served by the research service at /research, its recorded
fixtures match docs/research-contract.md, and its sample event log is the one tests/research_sample.py writes (so
every number in it is worked out from the real windows)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from typing import Any

import pytest
from fastapi.testclient import TestClient

import research_sample
from signals.research.server import app

STATIC = Path(__file__).resolve().parent.parent / "signals" / "research" / "static"
FIX = STATIC / "fixtures"
SLUG_EX = "btc-updown-15m-1794285000"
CONTRACT = (Path(__file__).resolve().parent.parent / "docs" / "research-contract.md").read_text()


def test_the_sample_event_log_is_current() -> None:
    assert (FIX / "events.sample.json").read_text() == research_sample.text(), (
        "events.sample.json is out of date: run `uv run python tests/research_sample.py`"
    )


def test_the_service_serves_the_page_its_code_and_fixtures() -> None:
    c = TestClient(app)
    page = c.get("/research/")
    assert page.status_code == 200 and '<div id="root">' in page.text and "./js/app.js" in page.text
    for path in ["js/app.js", "js/chart.js", "js/store.js", "js/api.js", "research.css", "vendor/htm-preact-3.1.1.module.js",
                 "fixtures/events.sample.json"]:
        assert c.get(f"/research/{path}").status_code == 200, path


def test_a_shared_breakdowns_link_shows_its_card() -> None:
    """usesignals.app/breakdowns (web/vercel.json: /breakdowns and /research redirect to /breakdowns/, which forwards
    here) shows a title, a line and a 1200x630 image on X, iMessage, Slack. The image's URL has to be absolute."""
    c = TestClient(app)
    page = c.get("/research/").text
    assert '<meta property="og:image" content="https://usesignals.app/breakdowns/og.png">' in page
    assert '<meta name="twitter:card" content="summary_large_image">' in page
    assert '<meta property="og:url" content="https://usesignals.app/breakdowns">' in page
    png = c.get("/research/og.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content[16:24] == (1200).to_bytes(4, "big") + (630).to_bytes(4, "big")  # PNG header: width, height
    vercel = json.loads((STATIC.parents[2] / "web" / "vercel.json").read_text())
    redirects = {r["source"]: r["destination"] for r in vercel["redirects"]}
    assert redirects == {"/breakdowns": "/breakdowns/", "/research": "/breakdowns/", "/research/": "/breakdowns/"}
    rewrites = {r["source"]: r["destination"] for r in vercel["rewrites"]}
    assert rewrites["/breakdowns/(.*)"] == "https://signals-research-production.up.railway.app/research/$1"
    sources = [r["source"] for r in vercel["rewrites"]]
    assert sources.index("/breakdowns/(.*)") < sources.index("/(.*)")  # above the engine's catch-all


def test_the_page_imports_only_its_own_files() -> None:
    """No CDN or other host in the page's code: the vendored bundle is pinned and served with it."""
    for js in (STATIC / "js").glob("*.js"):
        for spec in re.findall(r"""from\s+['"]([^'"]+)['"]""", js.read_text()):
            assert spec.startswith("./") or spec.startswith("../vendor/"), f"{js.name} imports {spec}"


def test_window_fixtures_have_what_the_replay_reads() -> None:
    ready = sorted(FIX.glob("window.ready.*.json"))
    assert ready
    for p in ready:
        r = json.loads(p.read_text())
        for k in ["window_id", "start", "end", "axis", "price_to_beat", "final_price", "result", "binance", "chainlink", "up",
                  "down", "minute_fallback", "trades", "position", "coverage"]:
            assert k in r, f"{p.name} has no {k}"
        assert r["window_id"] == f"btc-updown-15m-{r['start']}"
        ids = [t["trade_id"] for t in r["trades"]]
        assert len(ids) == len(set(ids)), f"{p.name}: trade ids repeat"
        assert all(re.fullmatch(r"[0-9a-f]{12}", i) for i in ids)
        for t in r["trades"]:
            assert t["liquidity"] in ("taker", "maker", None)
            assert t["pre_open"] == (t["t"] < r["start"])
        # without a recorded book the replay draws Polymarket's once-a-minute prices instead
        assert r["up"] or r["minute_fallback"], p.name
        s = json.loads((FIX / p.name.replace("window.ready", "window.summary")).read_text())
        assert round(sum(t["usd"] for t in r["trades"] if t["action"] == "buy"), 2) == s["cost"], "the tile's cost is the fills' usd"


def test_the_sample_uses_only_events_the_contract_names() -> None:
    sample = json.loads((FIX / "events.sample.json").read_text())
    types = {e["type"] for run in sample["runs"] for e in run} | {e["type"] for evs in sample["asks"].values() for e in evs}
    for t in types:
        assert f"`{t}`" in CONTRACT, f"{t} isn't in docs/research-contract.md"


def test_the_sample_shows_one_flagged_number_and_says_so() -> None:
    sample = json.loads((FIX / "events.sample.json").read_text())
    findings = [e for e in sample["runs"][1] if e["type"] == "finding.added"]
    flagged = [f for f in findings if not f["number_check"]["passed"]]
    assert len(flagged) == 1 and flagged[0].get("sample_note")
    f = flagged[0]
    assert f["counts"] is False, "a finding whose numbers didn't check out isn't counted"
    for field, flags in f["number_check"]["flagged"].items():
        for flag in flags:
            assert f[field][flag["start"]:flag["end"]] == flag["value_text"]


def test_sample_findings_have_the_contracts_fields() -> None:
    sample = json.loads((FIX / "events.sample.json").read_text())
    for f in (e for e in sample["runs"][1] if e["type"] == "finding.added"):
        for k in ["finding_id", "ask_id", "kind", "label", "title", "stat", "rule", "evidence", "example", "based_on",
                  "would_change_mind", "number_check", "counts"]:
            assert k in f, f"{f['finding_id']} has no {k}"
        assert set(f["evidence"]) == {"supporting_window_ids", "against_window_ids", "trade_ids"}
        assert "body" not in f, "findings have no body in the contract"


def test_example_questions_teach_without_running_anything() -> None:
    """The cards under the ask box (owner, 10 Nov): four, each naming its wallet (one of two sample traders, mixed across
    the cards, or the wallet typed above), each a different kind of answer (explain, chart, replay, compare), BTC
    15-minute only, research wording, and a click only fills the form: Break it down still shows the plan first. A
    sample trader's full address is never on a card."""
    js = (STATIC / "js" / "app.js").read_text()
    traders = re.search(r"const SAMPLE_TRADERS = \[(.*?)\n\];", js, re.S).group(1)
    assert len(re.findall(r"wallet: '0x[0-9a-f]{40}', name: '[^']+'", traders)) == 2
    block = re.search(r"const EXAMPLES = \[.*?\n(.*?)\n\];", js, re.S).group(1)
    cards = re.findall(r"\[([01]), w => `([^`]+)`, w => `([^`]+)`\]", block)
    assert len(cards) == 4
    assert {t for t, _, _ in cards} == {"0", "1"}  # both traders appear
    kinds = [label.split()[0] for _, label, _ in cards]
    assert kinds == ["How", "Chart", "Replay", "Compare"], kinds  # explain, chart, replay, compare
    pairs = [(label, question) for _, label, question in cards]
    for label, question in pairs:
        assert "${w}" in label and "${w}" in question and "BTC 15-minute" in question, (label, question)
        for text in (label, question):
            low = text.lower()
            assert not re.search(r"this wallet|0x[0-9a-f]{6}|\bbets?\b|you could|worth following|\broi\b|\bedge\b", low), text
    assert "SAMPLE_TRADERS[EXAMPLES[i][0]].name : shortWallets(w.trim())" in js  # a name or a short wallet, never a full one
    assert "onInput=${e => onWallet(e.target.value)}" in js  # a picked question follows the wallet field
    pick = re.search(r"const pick = (.*?);\n", js).group(1)
    assert "start" not in pick and "ask(" not in pick and "create(" not in pick
    assert "if (isSample(wallet)) setWallet(SAMPLE_TRADERS[EXAMPLES[i][0]].wallet)" in pick  # a typed wallet is kept
    assert "!w.trim() || SAMPLE_TRADERS.some(" in js  # only an empty field or a sample wallet is swapped for a card's trader
    assert "${!SAMPLE && html`<div class=\"examples\"" in js  # the locked sample plays one recorded question only


def _page_store(run_js_module: str) -> Any:
    """Runs ``run_js_module`` (a module body with ``S`` = the page's store.js) in Node; returns what it prints."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("Node isn't installed: the page's JavaScript can't be run here")
    code = f"import * as S from {json.dumps((STATIC / 'js' / 'store.js').as_uri())};\n{run_js_module}"
    r = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_the_activity_log_words_each_tools_summary_never_an_object() -> None:
    """10 Nov: the log read "finding: [object Object]" and "Read its trades: [object Object] (24.4 s)". A tool
    result's summary is the tool's figures as an object (contract, tool.result): the page words it."""
    results = [
        {"tool": "wallet_trades", "ok": True, "rows": 412, "limit_hit": False, "ms": 24400,
         "summary": {"rows": 412, "windows": 37, "complete": True, "limit_hit": False, "ms": 24400}},
        {"tool": "finding", "ok": True, "summary": {"finding_id": "F3"}},
        {"tool": "step_status", "ok": True, "summary": {"step_id": "trades", "status": "done"}},
        {"tool": "propose_plan", "ok": True, "summary": {"steps": 3}},
        {"tool": "window", "ok": True, "summary": {"slug": SLUG_EX, "result": "Up", "coverage": {"book": "full"}}},
        {"tool": "show_windows", "ok": True, "summary": {"rows": 1, "failed": 0}},
        {"tool": "walkthrough", "ok": True, "summary": {"steps": 4, "number_check": False}},
        {"tool": "answer", "ok": True, "summary": {"number_check": True}},
        {"tool": "outside_prices", "ok": True, "summary": {"source": "binance", "available": True, "points": 900}},
        {"tool": "wallet_trades", "ok": False, "summary": {"error": "That isn't a wallet address."}},
        {"tool": "some_new_tool", "ok": True, "summary": {"n": 2, "nested": {"a": 1}}},
        {"tool": "wallet_trades", "ok": True, "summary": "450 fills in 3 windows"},  # the recorded sample's strings
        {"tool": "code", "ok": True, "stdout": "x", "return_code": 0},
    ]
    events = [{"type": "tool.result", "seq": i, "v": 2, "run": 1, "id": f"t{i}", **e} for i, e in enumerate(results)]
    log = _page_store(f"const inv = S.emptyInv('x'); for (const e of {json.dumps(events)}) S.apply(inv, e, null);\n"
                      "process.stdout.write(JSON.stringify(inv.log.map(l => l.text)));")
    assert not [line for line in log if "[object" in line or "undefined" in line], log
    assert log == [
        "Read its trades: 412 trades in 37 windows (24.4 s)",
        "Added a finding: F3",
        "Updated a step: step trades done",
        "Proposed a plan: 3 steps",
        f"Built a window: {SLUG_EX}, ended Up",
        "Showed windows: 1 window",
        "Wrote a walkthrough: 4 steps, a number flagged",
        "Wrote the answer: shown",
        "Read Binance and Chainlink prices: 900 prices from binance",
        "Read its trades: failed: That isn't a wallet address.",
        "some_new_tool: n 2",
        "Read its trades: 450 fills in 3 windows",
        "Ran a calculation: done",
    ]


def test_a_reloaded_interrupted_breakdown_shows_where_it_got_to_not_working() -> None:
    """The events the service writes for a run cut off by a deploy, replayed as a reload does: not running, done, the
    partial answer and the notice in the column."""
    events = [
        {"type": "ask.started", "ask_id": 7, "text": "Go", "context": None},
        {"type": "tool.call", "id": "t1", "tool": "wallet_trades", "args": {"wallet": "0xab"}, "started_at": 1794300000},
        {"type": "finding.added", "finding_id": "F1", "label": "observed", "title": "Two-sided in 93 of 94 windows",
         "counts": True, "number_check": {"passed": True, "flagged": {}}},
        {"type": "answer.card", "ask_id": 7, "label": "Where the breakdown got to", "partial": True,
         "observed": ["Two-sided in 93 of 94 windows"], "inferred": [], "annotations": [], "focus": None,
         "finding_ids": ["F1"], "number_check": {"passed": True, "flagged": {}}},
        {"type": "notice", "text": "This breakdown was interrupted by an update. Ask again to finish it."},
        {"type": "done"},
    ]
    events = [{"seq": i, "v": 2, "run": 7, **e} for i, e in enumerate(events)]
    inv = _page_store(f"const inv = S.emptyInv('x'); for (const e of {json.dumps(events)}) S.apply(inv, e, S.emptyUi());\n"
                      "process.stdout.write(JSON.stringify({running: inv.running, done: inv.done, error: inv.error, "
                      "feed: inv.feed.map(f => [f.type, f.text || f.label || f.id || null])}));")
    assert inv["running"] is False and inv["done"] is True and inv["error"] is None
    assert inv["feed"] == [["ask", "Go"], ["finding", "F1"], ["answer", "Where the breakdown got to"],
                           ["note", "This breakdown was interrupted by an update. Ask again to finish it."]]


def test_a_started_plan_shows_its_step_and_a_running_row_says_so() -> None:
    """Drew, 10 Nov: "how far along is it?". A Started plan's progress is its steps (step.status): "Step 2 of 3" and a
    segment per step. A question's run has none (its clock alone). A running row in the list words its step and the
    time left."""
    steps = [{"id": "a", "title": "Read its trades"}, {"id": "b", "title": "Match prices"}, {"id": "c", "title": "Write"}]
    events = [
        {"type": "plan.proposed", "plan_id": "p1", "title": "Plan", "steps": steps},
        {"type": "ask.started", "ask_id": 2, "text": "Start the plan.", "context": {"plan_id": "p1", "action": "approve"},
         "started_at": 1794300000, "limit_s": 600, "typical_s": 240},
        {"type": "plan.answered", "plan_id": "p1", "action": "approve"},
        {"type": "step.status", "step_id": "a", "status": "done"},
        {"type": "step.status", "step_id": "b", "status": "running", "progress": {"done": 30, "total": 120}},
    ]
    events = [{"seq": i, "v": 2, "run": 2, **e} for i, e in enumerate(events)]
    got = _page_store(
        f"const inv = S.emptyInv('x'); const ev = {json.dumps(events)};\n"
        "const q = S.emptyInv('q'); S.apply(q, {seq: 0, v: 2, type: 'ask.started', ask_id: 1, text: 'Why?', started_at: 1}, null);\n"
        "const out = {};\n"
        "S.apply(inv, ev[0], null); out.proposed = S.planProgress(inv);\n"
        "for (const e of ev.slice(1)) S.apply(inv, e, null); out.running = S.planProgress(inv);\n"
        "out.question = S.planProgress(q);\n"
        "S.apply(inv, {seq: 10, v: 2, type: 'step.status', step_id: 'b', status: 'done'}, null);\n"
        "S.apply(inv, {seq: 11, v: 2, type: 'step.status', step_id: 'c', status: 'done'}, null);\n"
        "out.finishing = S.planProgress(inv);\n"
        "S.apply(inv, {seq: 12, v: 2, type: 'done'}, null); out.done = S.planProgress(inv);\n"
        "out.rows = [S.rowProgress({started_at: 1794300000, typical_s: 240, limit_s: 600, steps: 3, done: 1, step: 2}, 1794300060),\n"
        "            S.rowProgress({started_at: 1794300000, limit_s: 600}, 1794300060), S.rowProgress(null)];\n"
        "process.stdout.write(JSON.stringify(out));")
    assert got["proposed"] is None and got["question"] is None and got["done"] is None
    r = got["running"]
    assert (r["label"], r["step"], r["total"], r["done"], r["segs"], r["frac"]) == ("Step 2 of 3", 2, 3, 1, ["done", "run", ""], 0.25)
    assert got["finishing"]["label"] == "Finishing up" and got["finishing"]["segs"] == ["done", "done", "done"]
    assert got["rows"] == ["Running · step 2 of 3 · about 3 min left", "Running · it stops by 10 min at the latest", "Running"]


def test_a_finished_breakdown_is_ready_until_you_open_it() -> None:
    """A row that isn't running: Ready when its latest run ended cleanly after you last opened it (and after `since`,
    within a day), Stopped when it ended on an error, else Saved."""
    now, since = 1794300000, 1794200000
    rows = [
        {"id": "a", "running": True},
        {"id": "b", "ended": now - 60},  # never opened
        {"id": "c", "ended": now - 60},  # opened after it ended
        {"id": "d", "ended": now - 60, "stopped": "over_budget"},
        {"id": "e", "ended": since - 10},  # ended before this code's first visit
        {"id": "f", "ended": now - 90000},  # over a day ago
        {"id": "g"},  # never ran
    ]
    got = _page_store(f"const opened = {{c: {now - 30}}};\n"
                      f"process.stdout.write(JSON.stringify({json.dumps(rows)}.map(r => S.rowState(r, opened, {since}, {now}))));")
    assert got == ["running", "ready", "saved", "stopped", "saved", "saved", "saved"]
    assert _page_store("process.stdout.write(JSON.stringify(S.rowState({id: 'q', queued: true}, {}, 0, 1)));") == "queued"


def test_a_queued_start_shows_queued_then_runs_or_goes_back_to_start() -> None:
    plan = {"type": "plan.proposed", "plan_id": "p1", "title": "Plan", "steps": [{"id": "a", "title": "Read"}]}
    got = _page_store(
        f"const out = []; const inv = S.emptyInv('x'); S.apply(inv, {json.dumps({'seq': 0, 'v': 2, **plan})}, null);\n"
        "S.apply(inv, {seq: 1, v: 2, type: 'plan.queued', plan_id: 'p1'}, null); out.push(inv.plans.p1.status);\n"
        "S.apply(inv, {seq: 2, v: 2, type: 'plan.answered', plan_id: 'p1', action: 'approve'}, null); out.push(inv.plans.p1.status);\n"
        "const b = S.emptyInv('y'); S.apply(b, {...inv.plans.p1, seq: 0, v: 2, type: 'plan.proposed', status: undefined}, null);\n"
        "S.apply(b, {seq: 1, v: 2, type: 'plan.queued', plan_id: 'p1'}, null);\n"
        "S.apply(b, {seq: 2, v: 2, type: 'plan.unqueued', plan_id: 'p1', text: 'Press Start again.'}, null);\n"
        "out.push(b.plans.p1.status, b.feed.map(f => f.text));\n"
        "process.stdout.write(JSON.stringify(out));")
    assert got == ["queued", "approved", "proposed", ["Press Start again."]]


def test_the_column_puts_the_answer_first_and_offers_one_next_step() -> None:
    """Owner, 11 Nov: "so much information combined in the right-hand side that it mentally overloads the trader".
    Answer first, proof on demand: the sample's run ends on its answer (as a live one does) in two or three
    sentences; the column groups the feed by question (a plan's Start isn't a new question), the agent's proposal
    is the one next step above the ask box (not a card in the feed), and no finding carries an id or a "numbers
    checked" line: only a failed check is marked."""
    sample = json.loads((FIX / "events.sample.json").read_text())
    events = [e for run in sample["runs"] for e in run]
    cards = [e for e in sample["runs"][1] if e["type"] == "answer.card"]
    assert len(cards) == 1
    sentences = re.findall(r"[.!?](?:\s|$)", " ".join(cards[0]["observed"] + cards[0]["inferred"]))
    assert 2 <= len(sentences) <= 3, cards[0]
    seq = [{**e, "seq": i, "v": 2} for i, e in enumerate(events)]
    got = _page_store(f"const inv = S.emptyInv('x'); for (const e of {json.dumps(seq)}) S.apply(inv, e, null);\n"
                      "process.stdout.write(JSON.stringify(S.groups(inv.feed).map(g => [g.ask && g.ask.text, g.items.map(x => x.type)])));")
    assert len(got) == 1, got  # the question, and its Start's run under it
    assert got[0][0] == sample["runs"][0][0]["question"]
    assert "answer" in got[0][1] and "finding" in got[0][1]
    js = (STATIC / "js" / "agent.js").read_text()
    assert "Next, I'd look at" not in js and "Numbers checked" not in js and "f.finding_id}</span>" not in js
    assert "x.type !== 'proposal'" in js and "lastP.state === 'open'" in js
