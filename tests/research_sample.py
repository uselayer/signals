"""The research page's sample event log (``signals/research/static/fixtures/events.sample.json``), for the page's
fixtures mode (``/research/?fixtures``) and its tests.

The windows are real (the service's own ``window.ready``/``window.summary`` for one wallet's BTC 15-minute windows on
9 Nov 2026); the events around them follow docs/research-contract.md (v2). Every number in the sample's text is
worked out here from those windows, so the sample can't claim what the data doesn't show. One finding is labelled a
sample: it carries a deliberately flagged number, to show how the page draws a failed number check.

Run ``uv run python tests/research_sample.py`` to rewrite the file; ``tests/test_research_ui.py`` checks it's current.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIX = Path(__file__).resolve().parent.parent / "signals" / "research" / "static" / "fixtures"
OUT = FIX / "events.sample.json"
WALLET = "0xb945…db68"  # shortened: the page shows "Trader 0xb9…68"
QUESTION = (
    "Analyze this wallet's BTC 15-minute trades. Plot its entries against Binance and Polymarket prices, show how its "
    "positions change over time, and help me understand its trading strategy."
)


def money(v: float) -> str:
    return f"${abs(v):,.2f}"


def signed(v: float) -> str:
    return ("−" if round(v, 2) < 0 else "+") + money(v)


def shares(v: float) -> str:
    return f"{round(v):,}"


def _load() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    ready = [json.loads(p.read_text()) for p in sorted(FIX.glob("window.ready.*.json"))]
    summ = [json.loads(p.read_text()) for p in sorted(FIX.glob("window.summary.*.json"))]
    totals = json.loads((FIX / "coverage.totals.json").read_text())
    return ready, summ, totals


def build() -> dict[str, Any]:
    ready, summ, totals = _load()
    by = {s["window_id"]: s for s in summ}
    n = len(ready)
    ids = [r["window_id"] for r in ready]
    hm = {r["window_id"]: _hm(r["start"]) for r in ready}

    pre = [r for r in ready if any(t["pre_open"] for t in r["trades"])]
    first_before = {r["window_id"]: r["coverage"]["pre_open_entries"]["first_s_before"] for r in pre}
    pre_fills = {r["window_id"]: sum(t["pre_open"] for t in r["trades"]) for r in pre}
    pre_sides = {r["window_id"]: sorted({t["side"] for t in r["trades"] if t["pre_open"]}) for r in pre}
    pre_both = [i for i, sides in pre_sides.items() if len(sides) == 2]
    one_side = {i: sides[0] for i, sides in pre_sides.items() if len(sides) == 1}
    both_end = [r for r in ready if r["position"][-1]["up"] > 0 and r["position"][-1]["down"] > 0]
    book = [r for r in ready if r["coverage"]["book"]]
    maker = sum(t.get("liquidity") == "maker" for r in book for t in r["trades"])
    taker = sum(t.get("liquidity") == "taker" for r in book for t in r["trades"])
    unchecked = sum(t.get("liquidity") is None for r in book for t in r["trades"])
    profits = [by[i]["profit"] for i in ids]
    total = round(sum(profits), 2)
    up_cost = round(sum(t["usd"] for r in ready for t in r["trades"] if t["side"] == "Up" and t["action"] == "buy"), 2)
    dn_cost = round(sum(t["usd"] for r in ready for t in r["trades"] if t["side"] == "Down" and t["action"] == "buy"), 2)
    assert up_cost > dn_cost, "the flagged sample's title says Up got more"
    wrong_title = f"Spends more on Up than on Down: $1,190.00 on Up, {money(dn_cost)} on Down"
    assert all(by[i]["profit"] < 0 for i in ids), "F2's title says it lost in every window"
    focus = max(book, key=lambda r: sum(t["pre_open"] for t in r["trades"]) * 1000 + len(r["trades"]))["window_id"]

    ends = "; ".join(
        f"{hm[r['window_id']]} UTC window: {shares(r['position'][-1]['up'])} Up and {shares(r['position'][-1]['down'])} "
        f"Down, resolved {r['result']}, {signed(by[r['window_id']]['profit'])}"
        for r in ready
    )
    run1 = [
        {"type": "investigation.created", "title": "How Trader 0xb9…68 trades BTC 15-minute markets", "question": QUESTION,
         "subject": {"wallet": WALLET, "name": None}, "scope": None, "origin": "pasted wallet"},
        {"type": "ask.started", "ask_id": 1, "text": QUESTION, "context": None},
        {"type": "answer.progress", "ask_id": 1, "text": "Working out what to read and in what order."},
        {"type": "plan.proposed", "plan_id": "plan-1", "ask_id": 1, "title": "Read and replay its BTC 15-minute windows",
         "scope": {"wallet": WALLET, "family": "btc-updown-15m", "from": "9 Nov 2026 11:00 UTC", "to": "10 Nov 2026 00:15 UTC"},
         "steps": [
             {"id": "s1", "title": "Find its BTC 15-minute trades", "source": "Polymarket trade history", "estimate_s": 20},
             {"id": "s2", "title": "Line up each window: start, price to beat, result", "source": "Polymarket market listings", "estimate_s": 10},
             {"id": "s3", "title": "Get each window second by second: Binance BTCUSDT, Chainlink BTC/USD, the Up and Down prices and order book", "source": "Layer's recordings, else Polymarket's once-a-minute prices", "estimate_s": 40},
             {"id": "s4", "title": "Draw every window with its fills and its position", "source": "", "estimate_s": 10},
             {"id": "s5", "title": "Find what repeats, and check each pattern against every window", "source": "", "estimate_s": 40}],
         "scope_options": [{"id": "all-since-2-nov", "text": "Every BTC 15-minute window it traded since 2 Nov (recorded order books)"}],
         "estimate_usd": 0.6, "needs_approval": True},
        {"type": "done"},
    ]
    s3_warn = [
        {"kind": "chainlink", "text": "Chainlink BTC/USD isn't recorded before 10 Nov 05:27 UTC: these windows have its start price and result only.", "window_ids": ids},
        *[{"kind": "gaps", "text": f"{hm[r['window_id']]} UTC window: no order book for {r['coverage']['seconds_without_book']} of 900 s; {r['coverage']['market_trades']['recorded']:,} of {r['coverage']['market_trades']['polymarket']:,} market trades recorded.", "window_ids": [r["window_id"]]} for r in book],
        *[{"kind": "no_book", "text": f"{hm[r['window_id']]} UTC window: read from Polymarket's API, no order book; prices once a minute.", "window_ids": [r["window_id"]]} for r in ready if not r["coverage"]["book"]],
    ]
    run2 = [
        {"type": "ask.started", "ask_id": 2, "text": "Start", "context": {"plan_id": "plan-1"}},
        {"type": "step.status", "step_id": "s1", "status": "running", "summary": "Reading its trades in BTC 15-minute markets"},
        {"type": "tool.call", "id": "t1", "tool": "wallet_trades", "args": {"wallet": WALLET, "family": "btc-updown-15m"}},
        {"type": "tool.result", "id": "t1", "tool": "wallet_trades", "ok": True, "rows": sum(len(r["trades"]) for r in ready), "limit_hit": False, "ms": 2140,
         "summary": f"{sum(len(r['trades']) for r in ready)} fills in {n} windows"},
        {"type": "step.status", "step_id": "s1", "status": "done", "summary": f"{sum(len(r['trades']) for r in ready)} fills in {n} windows"},
        {"type": "step.status", "step_id": "s2", "status": "done", "summary": f"{n} windows: {sum(r['result'] == 'Up' for r in ready)} resolved Up, {sum(r['result'] == 'Down' for r in ready)} Down"},
        {"type": "step.status", "step_id": "s3", "status": "running", "summary": "Lining up prices for every second", "progress": {"done": 0, "total": n}},
        *[e for r in ready for e in (
            {"type": "tool.call", "id": f"w{r['start']}", "tool": "window", "args": {"window": r["window_id"]}},
            {"type": "tool.result", "id": f"w{r['start']}", "tool": "window", "ok": True, "rows": len(r["binance"]), "limit_hit": False, "ms": 900,
             "summary": f"{hm[r['window_id']]} UTC: {r['coverage']['source']}"},
            {**{k: v for k, v in by[r["window_id"]].items()}, "type": "window.summary"},
        )],
        {"type": "coverage", "per_source": totals, "windows": [r["coverage"] for r in ready]},
        {"type": "step.status", "step_id": "s3", "status": "warning", "summary": f"Binance for all {n}; order book for {len(book)} of {n}", "progress": {"done": n, "total": n}, "warnings": s3_warn},
        {"type": "step.status", "step_id": "s4", "status": "done", "summary": f"{n} windows drawn"},
        {"type": "view.focus", "stage": "window", "window_id": focus, "step_index": 1, "highlight_window_ids": [], "label": "its buys before the open"},
        {"type": "answer.progress", "ask_id": 2, "text": "Looking for what repeats across the windows."},
        {"type": "step.status", "step_id": "s5", "status": "done", "summary": "4 findings, 1 reading, and what's missing"},
        {"type": "finding.added", "finding_id": "F1", "ask_id": 2, "kind": "pattern", "label": "observed",
         "title": "Buys before the window opens, usually both sides",
         "stat": {"count": len(pre), "out_of": n, "unit": "windows", "text": f"{len(pre)} of {n} windows"},
         "rule": "Fills timed before the window's start (pre_open). Its first came "
                 + ", ".join(f"{first_before[i]} s" for i in ids if i in first_before) + " early ("
                 + ", ".join(str(pre_fills[i]) for i in ids if i in pre_fills) + " fills before the open); "
                 + f"both Up and Down before the open in {len(pre_both)} of {len(pre)}"
                 + ("; " + "; ".join(f"the {hm[i]} UTC window {side} only" for i, side in one_side.items()) if one_side else "") + ".",
         "evidence": {"supporting_window_ids": [r["window_id"] for r in pre], "against_window_ids": [i for i in ids if i not in first_before],
                      "trade_ids": [t["trade_id"] for r in pre for t in r["trades"] if t["pre_open"]]},
         "example": {"window_id": focus, "step_index": 1}, "based_on": [], "would_change_mind": None,
         "number_check": {"passed": True, "flagged": {}}, "counts": True},
        {"type": "finding.added", "finding_id": "F2", "ask_id": 2, "kind": "pattern", "label": "observed",
         "title": f"Holds both sides to the close, and lost in all {n} windows",
         "stat": {"count": len(both_end), "out_of": n, "unit": "windows", "text": f"{len(both_end)} of {n} windows"},
         "rule": f"Shares held of each side at the end, and profit from its fills plus the payout of shares held. {ends}. "
                 f"Together {signed(total)}; merges and redemptions aren't in the fills.",
         "evidence": {"supporting_window_ids": [r["window_id"] for r in both_end],
                      "against_window_ids": [i for i in ids if i not in {r['window_id'] for r in both_end}], "trade_ids": []},
         "example": {"window_id": ids[-1], "step_index": None}, "based_on": [], "would_change_mind": None,
         "number_check": {"passed": True, "flagged": {}}, "counts": True},
        {"type": "finding.added", "finding_id": "F3", "ask_id": 2, "kind": "pattern", "label": "observed",
         "title": "Most of its checked fills were resting buys, not taken at the asking price",
         "stat": {"count": maker, "out_of": maker + taker, "unit": "checked fills", "text": f"{maker} of {maker + taker} checked fills"},
         "rule": f"A buy at or above the recorded best ask just before the trade paid the asking price; below it, a resting buy filled. "
                 f"In the {len(book)} windows with a recorded book: {maker} resting, {taker} paid the asking price, {unchecked} in recording gaps "
                 "and not checked. The window without a book can't be checked.",
         "evidence": {"supporting_window_ids": [r["window_id"] for r in book], "against_window_ids": [], "trade_ids": []},
         "example": {"window_id": focus, "step_index": None}, "based_on": [], "would_change_mind": None,
         "number_check": {"passed": True, "flagged": {}}, "counts": True},
        {"type": "finding.added", "finding_id": "F4", "ask_id": 2, "kind": "read", "label": "inferred",
         "title": "It seems to quote both sides rather than pick a direction",
         "stat": None,
         "rule": f"If it rests buy orders on both Up and Down and keeps what fills to the close, most fills should sit below the asking "
                 f"price and both sides should be held at the end: {maker} of {maker + taker} checked fills were resting buys, and all {n} "
                 "windows ended holding both sides.",
         "evidence": {"supporting_window_ids": ids, "against_window_ids": [], "trade_ids": []},
         "example": None, "based_on": ["F1", "F2", "F3"],
         "would_change_mind": "Fills mostly at the asking price in windows with a recorded book, or windows where it ends holding one side only.",
         "number_check": {"passed": True, "flagged": {}}, "counts": True},
        {"type": "finding.added", "finding_id": "F5", "ask_id": 2, "kind": "pattern", "label": "observed",
         "title": wrong_title, "stat": None,
         "rule": "The fills' usd, buys only, by side.",
         "evidence": {"supporting_window_ids": ids, "against_window_ids": [], "trade_ids": []},
         "example": None, "based_on": [], "would_change_mind": None,
         "number_check": {"passed": False, "flagged": {"title": [{"value_text": "$1,190.00", "start": wrong_title.index("$1,190.00"),
                                                                   "end": wrong_title.index("$1,190.00") + 9, "data_value": money(up_cost)}]}},
         "counts": False, "sample_note": "A deliberately flagged sample, to show how a failed number check looks."},
        {"type": "finding.added", "finding_id": "F6", "ask_id": 2, "kind": "data", "label": "observed", "title": "What the data doesn't show",
         "stat": None,
         "rule": "\n".join([
             "Chainlink BTC/USD isn't recorded before 10 Nov 05:27 UTC, so BTC's moves here are measured on Binance BTCUSDT from its own price at the start.",
             *[f"{hm[r['window_id']]} UTC window: {r['coverage']['market_trades']['pct']}% of market trades recorded; gaps are hatched on the chart." for r in book],
             *[f"{hm[r['window_id']]} UTC window: no order book; the dotted lines are Polymarket's once-a-minute prices." for r in ready if not r["coverage"]["book"]],
             "Profit counts fills and the payout of shares held at the end; merges and redemptions aren't in the fills."]),
         "evidence": {"supporting_window_ids": [], "against_window_ids": [], "trade_ids": []},
         "example": None, "based_on": [], "would_change_mind": None, "number_check": {"passed": True, "flagged": {}}, "counts": True},
        {"type": "proposal", "proposal_id": "P1", "ask_id": 2, "text": f"Every BTC 15-minute window it traded on 9 Nov, to see whether these {n} are typical.", "accept_label": "Read them"},
        {"type": "usage", "cost_usd": 0.41, "rounds": 6, "tool_calls": 3 + n},
        {"type": "done"},
    ]
    asks = {
        "Why does it buy below the asking price?": [
            {"type": "answer.progress", "text": "Counting its fills against the recorded book."},
            {"type": "answer.card", "label": "How its fills compare with the asking price",
             "observed": [f"In the {len(book)} windows with a recorded order book, {maker} of its {maker + taker} checked fills were resting buys that filled, and {taker} paid the asking price.",
                          f"{unchecked} fills fell in recording gaps and can't be checked."],
             "inferred": ["It seems to post buy orders a little below the asking price and wait to be filled, on both sides. If so, its fills should cluster just under the best ask; the windows with a recorded book are where that can be checked."],
             "annotations": [], "focus": None, "finding_ids": ["F3"], "number_check": {"passed": True, "flagged": {}}},
            {"type": "done"}],
        "Read every BTC 15-minute window it traded on 9 Nov": [
            {"type": "answer.progress", "text": "That reads more windows, so here's the plan first."},
            {"type": "plan.proposed", "plan_id": "plan-3", "ask_id": 3, "title": "Read every window on 9 Nov",
             "scope": {"wallet": WALLET, "family": "btc-updown-15m", "from": "9 Nov 2026 00:00 UTC", "to": "10 Nov 2026 00:00 UTC"},
             "steps": [{"id": "s1", "title": "Find its BTC 15-minute trades on 9 Nov", "source": "Polymarket trade history", "estimate_s": 30},
                       {"id": "s2", "title": "Build each window and re-check every finding", "source": "Layer's recordings", "estimate_s": 120}],
             "scope_options": [], "estimate_usd": 1.2, "needs_approval": True},
            {"type": "done"}],
    }
    return {"about": "Sample events for the research page's fixtures mode: real windows, events per docs/research-contract.md (v2). Written by tests/research_sample.py.",
            "runs": [run1, run2], "asks": asks}


def _hm(unix: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(unix, UTC).strftime("%-d %b %H:%M")


def text() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    OUT.write_text(text())
    print(f"wrote {OUT}")
