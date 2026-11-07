"""Signed in from an alert: an alert's "Check current price" is a Telegram login button (``/tg/in``) that signs in
whoever tapped it, as the account their chat is connected to. No network: Telegram and Clerk are stand-ins."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_alerts import SAM, Telegram, api, user  # noqa: F401 - the alerts' fixture and helpers

from signals import app as engine

CHECK = f"{engine.SITE}/#/check/{SAM}/0xcid:0"


def tg_data(tg_id: str = "555", at: float | None = None, token: str = "123:test") -> dict[str, str]:
    """What Telegram adds to a login button's address when it's tapped, signed as Telegram signs it."""
    q = {"id": tg_id, "first_name": "Zed", "auth_date": str(int(time.time() if at is None else at))}
    check = "\n".join(f"{k}={q[k]}" for k in sorted(q))
    return q | {"hash": hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()}


@pytest.fixture
def login(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> list[str]:  # noqa: F811
    monkeypatch.setattr(engine, "TG_LOGIN", True)
    monkeypatch.setattr(engine, "CLERK_SECRET", "sk_test_x")
    engine._tg_logins_used.clear()
    monkeypatch.setitem(engine._tg, "login_refused", None)
    made: list[str] = []
    monkeypatch.setattr(engine, "_sign_in_pass", lambda uid: made.append(uid) or f"pass-{uid}")
    return made


def check_alert() -> str:
    return engine._send("user_1", "555", "buy", lambda a: "alert\n" + engine._links(("Check current price", CHECK), aid=a)) or ""


def test_an_alerts_check_current_price_signs_in_whoever_tapped_it(api: TestClient, login: list[str]) -> None:  # noqa: F811
    user()
    aid = check_alert()
    button = engine.tg.sent[-1]["reply_markup"]["inline_keyboard"][0][0]
    assert button == {"text": "Check current price on Signals", "login_url": {"url": f"{engine.SITE}/tg/in/{aid}"}}
    r = api.get(f"/tg/in/{aid}", params=tg_data(), follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{engine.SITE}/?signin=pass-user_1#/check/{SAM}/0xcid:0"
    assert login == ["user_1"]
    with engine._db() as con:
        assert con.execute("SELECT alert_id, target FROM events WHERE kind = 'tap'").fetchall() == [(aid, "check")]


def test_a_login_tap_that_doesnt_check_out_opens_the_trade_signed_out(api: TestClient, login: list[str]) -> None:  # noqa: F811
    user()
    user("user_2", chat="777")
    user(engine.TG_ONLY + "abc", chat="888")
    aid = check_alert()

    def go(q: dict[str, str]) -> str:
        return str(api.get(f"/tg/in/{aid}", params=q, follow_redirects=False).headers["location"])

    assert go({}) == CHECK  # they declined Telegram's "log in?"
    assert go(tg_data(token="999:someone-else")) == CHECK  # not signed by our bot
    assert go(tg_data() | {"id": "777"}) == CHECK  # changed after signing
    assert go(tg_data(at=time.time() - 3600)) == CHECK  # old
    assert go(tg_data(tg_id="888")) == CHECK  # a Telegram-only follower: no account to sign in to
    assert go(tg_data(tg_id="999")) == CHECK  # a chat connected to no one
    once = tg_data(tg_id="777")
    assert go(once) == f"{engine.SITE}/?signin=pass-user_2#/check/{SAM}/0xcid:0"  # forwarded: the tapper's own account
    assert go(once) == CHECK  # the same data again (a copied link): never twice
    assert login == ["user_2"]
    assert api.get("/tg/in/madeup12", params=tg_data(), follow_redirects=False).headers["location"] == engine.SITE


def test_the_sign_in_pass_comes_from_clerk_and_its_failure_means_signed_out(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json
    import urllib.request

    asked: list[urllib.request.Request] = []

    def clerk(req: urllib.request.Request, timeout: float) -> io.BytesIO:
        asked.append(req)
        return io.BytesIO(json.dumps({"token": "tok_1", "url": "https://accounts.test"}).encode())

    monkeypatch.setattr(engine, "CLERK_SECRET", "sk_test_x")
    monkeypatch.setattr(urllib.request, "urlopen", clerk)
    assert engine._sign_in_pass("user_1") == "tok_1"
    (req,) = asked
    assert req.full_url == "https://api.clerk.com/v1/sign_in_tokens" and req.get_header("Authorization") == "Bearer sk_test_x"
    assert json.loads(req.data) == {"user_id": "user_1", "expires_in_seconds": engine.SIGN_IN_PASS_S}  # type: ignore[arg-type]

    def down(req: urllib.request.Request, timeout: float) -> None:
        raise OSError("no answer")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    assert engine._sign_in_pass("user_1") is None


def test_the_login_button_is_off_until_switched_on(api: TestClient, login: list[str], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    user()
    engine._send("user_1", "555", "buy", lambda a: "alert, no price to check")
    assert engine.tg.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Useful"  # no check link: no button
    monkeypatch.setattr(engine, "TG_LOGIN", False)  # until the bot is linked to the site (/setdomain)
    aid = check_alert()
    assert engine.tg.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Useful"
    r = api.get(f"/tg/in/{aid}", params=tg_data(), follow_redirects=False)
    assert r.headers["location"] == CHECK and login == []


class RefusingTelegram(Telegram):
    """Telegram that refuses every message with a login button, as it does while the bot isn't linked to the site."""

    def __call__(self, method: str, **params: Any) -> Any:
        if method == "sendMessage" and engine._has_login_button(params.get("reply_markup") or {}):
            raise engine.TelegramError("Telegram: Bad Request: BOT_DOMAIN_INVALID", 400)
        return super().__call__(method, **params)


def test_an_alert_telegram_refuses_for_its_button_goes_out_without_it(api: TestClient, login: list[str], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    user()
    tg = RefusingTelegram()
    monkeypatch.setattr(engine, "tg", tg)
    aid = check_alert()
    assert aid and len(tg.sent) == 1  # sent now, at the second ask: the first was refused for the button
    assert tg.sent[0]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Useful"
    assert "Check current price" in tg.sent[0]["text"]  # the link stays in the text
    with engine._db() as con:
        state, body = con.execute("SELECT state, body FROM alerts WHERE id = ?", (aid,)).fetchone()
    assert state == "sent" and not engine._has_login_button(json.loads(body)["markup"])
    assert engine._tg["login_refused"] == "Telegram: Bad Request: BOT_DOMAIN_INVALID"
    assert not engine._tg_login_on()
    check_alert()  # from now on no alert asks for the button, so none is refused
    assert len(tg.sent) == 2 and not engine._has_login_button(tg.sent[1]["reply_markup"])
    assert engine._sent_today("user_1") == 2


def test_a_refusal_for_anything_but_the_button_still_fails_the_alert(api: TestClient, login: list[str], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    user()

    class Refusing(Telegram):
        def __call__(self, method: str, **params: Any) -> Any:
            raise engine.TelegramError("Telegram: Bad Request: can't parse entities", 400)

    monkeypatch.setattr(engine, "tg", Refusing())
    assert check_alert() == ""
    with engine._db() as con:
        assert con.execute("SELECT state FROM alerts").fetchone()[0] == "failed"
    assert engine._tg["login_refused"] is None and engine._tg_login_on()
