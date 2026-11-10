"""The research page (signals/research/static/): served by the research service at /research, its recorded
fixtures match docs/research-contract.md, and its sample event log is the one tests/research_sample.py writes (so
every number in it is worked out from the real windows)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

import research_sample
from signals.research.server import app

STATIC = Path(__file__).resolve().parent.parent / "signals" / "research" / "static"
FIX = STATIC / "fixtures"
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
