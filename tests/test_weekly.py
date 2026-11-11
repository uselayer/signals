"""The weekly "what's new in Signals" email (signals/weekly.py): drafted the day before, previewed to David, sent to
readers at 9 AM in their time zone only once he approves, with a one-click unsubscribe."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from signals import app as engine
from signals import weekly

ENV = {"CLERK_SECRET_KEY": "sk_test_x", "RESEND_API_KEY": "re_x", "OPENROUTER_API_KEY": "or_x",
       "SIGNALS_OWNER_USER": "user_owner"}  # fmt: skip
SITE = "https://usesignals.app"


def at(s: str) -> float:
    """A Pacific wall time, "2026-11-11 13:05" (PST in November)."""
    return datetime.fromisoformat(s).replace(tzinfo=weekly.PT).timestamp()


WED_1PM = at("2026-11-11 13:05")  # the draft day for Thursday 12 Nov
DRAFT = {"subject": "Alert rules for every trader", "preheader": "Pick which trades reach you.",
         "tldr": ["Choose which trades alert you"],
         "items": [{"lead": "You can now pick which trades alert you.", "body": "Set a minimum size per trader.",
                    "page": "/#/traders", "video_hint": "Setting a rule in Telegram."}],
         "ask": "What should Signals do next?"}  # fmt: skip


def clerk(uid: str, email: str | None, **extra: Any) -> dict[str, Any]:
    emails = [{"id": f"e_{uid}", "email_address": email}] if email else []
    return {"id": uid, "created_at": 1_700_000_000_000, "first_name": "Sam", "last_name": None,
            "primary_email_address_id": f"e_{uid}" if email else None, "email_addresses": emails, **extra}  # fmt: skip


class Fake:
    def __init__(self) -> None:
        self.users = [clerk("user_a", "a@example.com"), clerk("user_b", "b@example.com"), clerk("user_tg", None),
                      clerk("user_owner", "boss@example.com"), clerk("user_x", "pemakenemi56@gmail.com"),
                      clerk("user_banned", "c@example.com", banned=True)]  # fmt: skip
        self.sent: list[tuple[dict[str, Any], str]] = []
        self.answer: bool | str = True
        self.prs = [{"number": 7, "title": "Alert rules", "body": "…", "merged_at": "2026-11-10T10:00:00Z", "url": "u"}]
        self.written: list[tuple[list[dict[str, Any]], str]] = []
        self.draft: tuple[dict[str, Any] | None, str] = (DRAFT, "")
        self.fail = False

    def send(self, payload: dict[str, Any], idem: str) -> bool | str:
        self.sent.append((payload, idem))
        return self.answer

    def writer(self, prs: list[dict[str, Any]], notes: str) -> tuple[dict[str, Any] | None, str]:
        if self.fail:
            raise RuntimeError("the writer answered 502")
        self.written.append((prs, notes))
        return self.draft

    def run(self, store: Path, now: float, env: dict[str, str] | None = None, **k: Any) -> dict[str, Any]:
        return weekly.check(now, store, env=ENV if env is None else env, site=SITE, users=lambda s: self.users,
                            prs_since=lambda since, tok: self.prs, writer=self.writer, send=self.send, **k)  # fmt: skip

    def to(self, addr: str) -> list[dict[str, Any]]:
        return [p for p, _ in self.sent if p["to"] == [addr]]


def test_days_and_nine_am() -> None:
    assert weekly.next_send_date(WED_1PM, 3) == "2026-11-12"
    assert weekly.next_send_date(at("2026-11-12 08:00"), 3) == "2026-11-19"  # on the send day: next week's
    assert weekly.is_draft_time(WED_1PM, 3)
    assert not weekly.is_draft_time(at("2026-11-11 12:59"), 3)
    assert not weekly.is_draft_time(at("2026-11-10 15:00"), 3)
    assert weekly.send_day({"SIGNALS_WEEKLY_SEND_DAY": "Tuesday"}) == 1
    assert weekly.send_day({"SIGNALS_WEEKLY_SEND_DAY": "someday"}) == 3
    assert weekly.local_nine("2026-11-12", "America/New_York") == datetime(2026, 11, 12, 14, tzinfo=UTC)
    assert weekly.local_nine("2026-07-09", "America/New_York") == datetime(2026, 7, 9, 13, tzinfo=UTC)  # summer time
    assert weekly.local_nine("2026-11-12", "Europe/London") == datetime(2026, 11, 12, 9, tzinfo=UTC)
    assert weekly.valid_tz("Africa/Lagos") == "Africa/Lagos"
    assert weekly.valid_tz("Mars/Olympus") is None and weekly.valid_tz("../etc") is None and weekly.valid_tz(None) is None


def test_signed_links() -> None:
    sig = weekly.sign("approve", "2026-11-12", ENV)
    assert weekly.verify("approve", "2026-11-12", sig, ENV)
    assert not weekly.verify("approve", "2026-11-19", sig, ENV)
    assert not weekly.verify("unsubscribe", "2026-11-12", sig, ENV)  # a link for one thing never works for another
    assert not weekly.verify("approve", "2026-11-12", sig, {**ENV, "CLERK_SECRET_KEY": "sk_other"})
    assert not weekly.verify("approve", "2026-11-12", None, ENV) and not weekly.verify("approve", "2026-11-12", "é", ENV)
    assert not weekly.verify("approve", "2026-11-12", sig, {})  # nothing to sign with: nothing verifies
    assert weekly.verify("unsubscribe", "u", weekly.sign("unsubscribe", "u", {"SIGNALS_WEEKLY_SECRET": "s"}), {"SIGNALS_WEEKLY_SECRET": "s"})


def test_draft_preview_approve_send(tmp_path: Path) -> None:
    f = Fake()
    assert f.run(tmp_path, at("2026-11-11 12:00")) == {}  # before 1 PM on the draft day: nothing
    assert f.written == [] and f.sent == []

    out = f.run(tmp_path, WED_1PM)
    assert out["draft"] == "drafted" and out["preview 2026-11-12"] == "sent"
    ((mail, _),) = f.sent
    assert mail["to"] == ["pemakenemi56@gmail.com"] and mail["subject"] == "[Preview] Alert rules for every trader"
    assert "Preview for you only" in mail["html"] and "Approve and send" in mail["html"]
    assert "for 2 readers at 9 AM on Thursday, November 12" in mail["html"]  # a, b: no Telegram-only, owner, banned
    assert "30-second video: Setting a rule in Telegram." in mail["html"]
    assert weekly.approve_url("2026-11-12", ENV) in mail["text"]

    f.run(tmp_path, WED_1PM + 60)
    assert len(f.sent) == 1 and len(f.written) == 1  # drafted and previewed once

    assert weekly.approve(tmp_path, "2026-11-12", WED_1PM + 600)
    assert not weekly.approve(tmp_path, "2026-11-12", WED_1PM + 601)  # once
    weekly.remember_tz(tmp_path, "user_b", "Europe/London")
    out = f.run(tmp_path, WED_1PM + 660)
    assert out["send 2026-11-12"] == {"scheduled": 2, "failed": 0, "dropped": 0, "later": 0, "total": 2}
    (a,), (b,) = f.to("a@example.com"), f.to("b@example.com")
    assert a["scheduled_at"] == "2026-11-12T14:00:00Z"  # Eastern when unknown
    assert b["scheduled_at"] == "2026-11-12T09:00:00Z"
    assert a["subject"] == "Alert rules for every trader" and "Preview" not in a["html"] and "Approve" not in a["text"]
    assert a["headers"]["List-Unsubscribe"] == f"<{weekly.unsubscribe_url('user_a', ENV)}>"
    assert a["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert f"{SITE}/#/traders" in a["html"] and a["reply_to"] == "david@uselayer.sh"
    assert weekly.get_issue(tmp_path, "2026-11-12")["status"] == "scheduled"

    n = len(f.sent)
    f.run(tmp_path, WED_1PM + 720)
    assert len(f.sent) == n  # never twice


def test_failed_sends_retry_refused_ones_dont(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, WED_1PM)
    weekly.approve(tmp_path, "2026-11-12", WED_1PM)
    f.answer = False
    out = f.run(tmp_path, WED_1PM + 60)
    assert out["send 2026-11-12"]["failed"] == 2 and weekly.get_issue(tmp_path, "2026-11-12")["status"] == "approved"
    f.answer = "dead"
    out = f.run(tmp_path, WED_1PM + 120)
    assert out["send 2026-11-12"]["dropped"] == 2 and weekly.get_issue(tmp_path, "2026-11-12")["status"] == "scheduled"
    n = len(f.sent)
    f.run(tmp_path, WED_1PM + 180)
    assert len(f.sent) == n


def test_late_approval_goes_soon_and_after_the_day_never(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, WED_1PM)
    weekly.approve(tmp_path, "2026-11-12", WED_1PM)
    thu_noon = at("2026-11-12 12:00")  # 3 PM Eastern: past their 9 AM
    f.run(tmp_path, thu_noon)
    (a,) = f.to("a@example.com")
    assert a["scheduled_at"] == datetime.fromtimestamp(thu_noon + weekly.SOONEST_S, UTC).isoformat().replace("+00:00", "Z")

    g = Fake()
    store = tmp_path / "late"
    g.run(store, WED_1PM)
    weekly.approve(store, "2026-11-12", WED_1PM)
    g.run(store, at("2026-11-13 08:00"))  # the day after: "this week" is over
    assert g.to("a@example.com") == []


def test_unsubscribed_and_skipped_weeks(tmp_path: Path) -> None:
    f = Fake()
    weekly.unsubscribe(tmp_path, "user_a", WED_1PM)
    weekly.remember_tz(tmp_path, "user_a", "Europe/Paris")  # a later visit doesn't resubscribe them
    f.run(tmp_path, WED_1PM)
    weekly.approve(tmp_path, "2026-11-12", WED_1PM)
    f.run(tmp_path, WED_1PM + 60)
    assert f.to("a@example.com") == [] and len(f.to("b@example.com")) == 1

    g = Fake()
    g.draft = (None, "Only tests and research notes merged.")
    store = tmp_path / "quiet"
    out = g.run(store, WED_1PM)
    assert out["draft"] == "skipped: Only tests and research notes merged."
    ((mail, _),) = g.sent
    assert mail["subject"] == "No Signals update this week (Thursday, November 12)"
    assert "Why: Only tests and research notes merged." in mail["text"] and "- Alert rules (#7)" in mail["text"]
    assert not weekly.approve(store, "2026-11-12", WED_1PM)  # nothing to approve


def test_failed_draft_retries_hourly_and_tells_david_once(tmp_path: Path) -> None:
    f = Fake()
    f.fail = True
    out = f.run(tmp_path, WED_1PM)
    assert out["draft"].startswith("failed")
    ((mail, _),) = f.sent
    assert mail["subject"] == "Signals weekly draft failed (Thursday, November 12)" and "502" in mail["text"]
    f.run(tmp_path, WED_1PM + 600)
    assert len(f.sent) == 1  # no retry before the hour, no second note
    f.fail = False
    out = f.run(tmp_path, WED_1PM + 3700)
    assert out["draft"] == "drafted" and f.sent[-1][0]["subject"].startswith("[Preview]")


def test_redraft_with_notes_replaces_unapproved_only(tmp_path: Path) -> None:
    f = Fake()
    f.run(tmp_path, WED_1PM)
    f.run(tmp_path, WED_1PM + 60, force=True, notes="Put alerts first.")
    assert f.written[-1][1] == "Put alerts first." and len([p for p, _ in f.sent if p["subject"].startswith("[Preview]")]) == 2
    weekly.approve(tmp_path, "2026-11-12", WED_1PM + 120)
    out = f.run(tmp_path, WED_1PM + 180, force=True)
    assert out["draft"] == "already approved, kept"


def test_off_without_keys(tmp_path: Path) -> None:
    f = Fake()
    assert f.run(tmp_path, WED_1PM, env={"CLERK_SECRET_KEY": "x"}) == {"off": "needs RESEND_API_KEY, OPENROUTER_API_KEY"}
    assert f.run(tmp_path, WED_1PM, env={**ENV, "SIGNALS_WEEKLY": "0"}) == {"off": "SIGNALS_WEEKLY=0"}
    assert f.sent == []


def test_writer_answer_and_flags() -> None:
    raw = {"worth_sending": True, "skip_reason": "", "subject": "S", "preheader": "P", "tldr": [],
           "items": [{"lead": "L.", "body": "B.", "page": "https://usesignals.app/#/watchlist", "video_hint": ""},
                     {"lead": "M.", "body": "C.", "page": "/admin", "video_hint": None},
                     {"lead": "", "body": "dropped", "page": None, "video_hint": None}],
           "ask": ""}  # fmt: skip
    draft, why = weekly.to_draft(raw)
    assert why == "" and [it["page"] for it in draft["items"]] == ["/#/watchlist", None]
    assert draft["tldr"] == ["L.", "M."] and draft["ask"] == "What should Signals do next?"
    assert draft["items"][0]["video_hint"] is None
    assert weekly.to_draft({**raw, "worth_sending": False, "skip_reason": "Quiet."}) == (None, "Quiet.")

    bad = {**DRAFT, "items": [{"lead": "Copy any bet in one tap.", "body": "Try it.", "page": None, "video_hint": None}]}
    assert weekly.flags(bad) == ["Item 1 says 'bet', 'copy'"]
    html = weekly.render(bad, unsubscribe="u", preview={"approve": "a", "recipients": 1, "send_date": "2026-11-12"})["html"]
    assert "Check before approving" in html and "for 1 reader at" in html
    assert weekly.flags(DRAFT) == []


def test_typed_escapes_become_characters() -> None:
    raw = {"worth_sending": True, "subject": "A \\u2014 B", "preheader": "", "tldr": ["x \\u2014 y"], "ask": "",
           "items": [{"lead": "L.", "body": "Leave the page \\u2014 it keeps working.", "page": None, "video_hint": None}]}
    draft, _ = weekly.to_draft(raw)
    assert draft["subject"] == "A — B" and draft["tldr"] == ["x — y"]
    assert draft["items"][0]["body"] == "Leave the page — it keeps working."


def test_davids_own_draft_with_a_picture(tmp_path: Path) -> None:
    f = Fake()
    mine = {"subject": "Breakdowns", "preheader": "P", "tldr": ["T"], "ask": "Q?",
            "items": [{"lead": "L.", "body": "B.", "page": "/breakdowns/", "image": "/static/email/b.jpg",
                       "image_alt": "Breakdown", "image_link": "/static/email/b.mp4"},
                      {"lead": "M.", "body": "C.", "page": None, "image": "javascript:x", "image_link": "/x"}]}  # fmt: skip
    out = f.run(tmp_path, WED_1PM - 3600, force=True, given=mine)
    assert out["draft"] == "drafted" and f.written == []  # the writer isn't asked
    issue = weekly.get_issue(tmp_path, "2026-11-12")
    one, two = issue["draft"]["items"]
    assert one["image"] == "/static/email/b.jpg" and one["image_link"] == "/static/email/b.mp4"
    assert "image" not in two
    email = weekly.render(issue["draft"], unsubscribe="u", site=SITE)
    assert f'<a href="{SITE}/static/email/b.mp4"><img src="{SITE}/static/email/b.jpg" alt="Breakdown"' in email["html"]
    assert f"Watch: {SITE}/static/email/b.mp4" in email["text"]


def test_merged_since_pages_until_the_week_ends() -> None:
    since = datetime(2026, 11, 4, tzinfo=UTC).timestamp()

    def pr(n: int, merged: str | None, updated: str) -> dict[str, Any]:
        return {"number": n, "title": f"#{n}", "body": None, "merged_at": merged, "updated_at": updated, "html_url": f"u{n}"}

    pages = [[pr(3, "2026-11-10T00:00:00Z", "2026-11-10T00:00:00Z"), pr(2, None, "2026-11-09T00:00:00Z")]
             + [pr(100 + i, "2026-11-05T00:00:00Z", "2026-11-05T00:00:00Z") for i in range(98)],
             [pr(1, "2026-11-01T00:00:00Z", "2026-11-01T00:00:00Z")] * 100, [pr(0, "x", "x")]]  # fmt: skip
    urls: list[str] = []

    def fetch(url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
        urls.append(url)
        assert headers["Authorization"] == "Bearer t"
        return pages[len(urls) - 1]

    got = weekly.merged_since(since, "t", fetch)
    assert len(urls) == 2  # the second page ends before the week: no third read
    assert got[0]["number"] == 3 and len(got) == 99 and all(p["body"] == "" for p in got)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(engine, "STORE_DIR", tmp_path)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(weekly, "clerk_all", lambda secret: Fake().users)
    return TestClient(engine.app)


def test_approve_and_unsubscribe_pages(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(engine.welcome, "resend_send", lambda key: lambda p, idem: sent.append(p) or True)
    monkeypatch.setattr(weekly.time, "time", lambda: WED_1PM)
    monkeypatch.setattr(engine.time, "time", lambda: WED_1PM)
    weekly.save_issue(tmp_path, "2026-11-12", DRAFT, "", [], WED_1PM)
    sig = weekly.sign("approve", "2026-11-12", ENV)

    assert client.get("/api/weekly/approve", params={"issue": "2026-11-12", "sig": "nope"}).status_code == 403
    r = client.get("/api/weekly/approve", params={"issue": "2026-11-12", "sig": sig})
    assert r.status_code == 200 and "2 readers" in r.text and "<form method=\"post\"" in r.text
    assert sent == [] and weekly.get_issue(tmp_path, "2026-11-12")["status"] == "drafted"  # opening it sends nothing

    r = client.post("/api/weekly/approve", params={"issue": "2026-11-12", "sig": sig})
    assert "Scheduled 2 of 2 emails" in r.text and len(sent) == 2
    r = client.post("/api/weekly/approve", params={"issue": "2026-11-12", "sig": sig})
    assert "Already approved" in r.text and len(sent) == 2

    usig = weekly.sign("unsubscribe", "user_a", ENV)
    assert client.post("/api/weekly/unsubscribe", params={"u": "user_b", "sig": usig}).status_code == 403
    r = client.get("/api/weekly/unsubscribe", params={"u": "user_a", "sig": usig})
    assert "Unsubscribe from Signals&#x27; weekly update?" in r.text and "<form method=\"post\"" in r.text
    assert "You&#x27;re unsubscribed" in client.post("/api/weekly/unsubscribe", params={"u": "user_a", "sig": usig},
                                                 data={"List-Unsubscribe": "One-Click"}).text  # fmt: skip
    assert [p["uid"] for p in weekly.readers(tmp_path, Fake().users, ENV)] == ["user_b"]
    assert "preview" in client.get("/api/weekly/unsubscribe", params={"u": "preview"}).text


def test_owner_redraft_is_the_owners(client: TestClient) -> None:
    assert client.post("/api/weekly/draft", json={}, headers={"x-forwarded-for": "1.2.3.4"}).status_code == 404


def test_me_keeps_the_time_zone(client: TestClient, tmp_path: Path) -> None:
    engine.app.dependency_overrides[engine.signed_in] = lambda: "user_a"
    try:
        assert client.get("/api/me", headers={"x-time-zone": "Africa/Lagos"}).status_code == 200
        client.get("/api/me", headers={"x-time-zone": "not/a zone"})
    finally:
        engine.app.dependency_overrides.clear()
    assert weekly.readers(tmp_path, Fake().users, ENV)[0] == {"uid": "user_a", "email": "a@example.com", "tz": "Africa/Lagos"}
