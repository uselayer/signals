"""One-tap copy (signals/copying.py, signals/copy_service.py): the owner's flag, the set-up API, the "Copy" button
under an alert and what a tap does, and the order service. No real order is ever sent: the order service's
Polymarket calls are replaced."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import test_alerts as alerts
from fastapi.testclient import TestClient
from test_alerts import SAM, auth, new_buy, user

from signals import app as engine
from signals import copy_service, copying

OWNER = "0x" + "1" * 40
DEPOSIT = "0x" + "2" * 40
SIGNER = "0x" + "3" * 40


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> TestClient:
    client = alerts.api.__wrapped__(monkeypatch, tmp_path)  # type: ignore[attr-defined]
    monkeypatch.setattr(copying, "COPY_USERS", frozenset({"user_1"}))
    monkeypatch.setattr(copying, "COPY_URL", "https://copy.test")
    monkeypatch.setattr(copying, "COPY_TOKEN", "t0ken")
    monkeypatch.setattr(copying, "_signs", {})
    return client  # type: ignore[no-any-return]


class Service:
    """The order service, pretend: what it was asked, and what it answers."""

    def __init__(self, answer: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.answer = answer or {"ok": True, "status": "matched", "order_id": "0xo", "spent": 24.8, "shares": 59.0}

    def __call__(self, path: str, payload: dict[str, Any], timeout: float = 25) -> dict[str, Any]:
        self.calls.append((path, payload))
        if path == "/keys":
            return {"address": SIGNER, "enc": "ENC"}
        return dict(self.answer)


class Now:
    """threading.Thread that runs at once, so a tap's reply is there when the test looks."""

    def __init__(self, target: Any, args: tuple[Any, ...] = (), **kw: Any) -> None:
        self.target, self.args = target, args

    def start(self) -> None:
        self.target(*self.args)


def set_up(api: TestClient, monkeypatch: pytest.MonkeyPatch, svc: Service) -> None:
    monkeypatch.setattr(copying, "service", svc)
    assert api.post("/api/me/copy/start", json={"owner": OWNER, "country": "MX", "blocked": False}, headers=auth()).json() == {"signer": SIGNER}
    assert api.post("/api/me/copy/finish", json={"wallet": DEPOSIT}, headers=auth()).json() == {"state": "ready"}


def tap(data: str, chat: str = "555", message_id: int = 1) -> None:
    engine._on_update({"callback_query": {"id": "q", "data": data, "message": {"chat": {"id": chat}, "message_id": message_id}}})


def buy_alert() -> dict[str, Any]:
    assert engine._deliver("user_1", "555", new_buy(SAM, datetime.now(UTC), now=0.42), "Politics") == 1
    return engine.tg.sent[-1]


def buttons(msg: dict[str, Any]) -> list[str]:
    markup = msg["reply_markup"]
    rows = markup["inline_keyboard"] if isinstance(markup, dict) else __import__("json").loads(markup)["inline_keyboard"]
    return [b["text"] for row in rows for b in row]


# ---- the flag ----


def test_copying_is_hidden_from_everyone_outside_the_flag(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert api.get("/api/me/copy", headers=auth("user_2")).status_code == 404
    assert api.post("/api/copy/builder-sign", json={"method": "POST", "path": "/submit"}, headers=auth("user_2")).status_code == 404
    assert api.get("/api/me/copy").status_code == 401
    monkeypatch.setattr(copying, "COPY_URL", "")  # flagged, but no order service: off too
    assert api.get("/api/me/copy", headers=auth()).status_code == 404


def test_set_up_makes_one_trading_key_and_refuses_blocked_places(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = Service()
    monkeypatch.setattr(copying, "service", svc)
    assert api.get("/api/me/copy", headers=auth()).json()["state"] == "none"
    r = api.post("/api/me/copy/start", json={"owner": OWNER, "country": "US", "blocked": True}, headers=auth())
    assert r.status_code == 403 and "doesn't allow new trades where you are" in r.json()["detail"] and svc.calls == []
    set_up(api, monkeypatch, svc)
    again = api.post("/api/me/copy/start", json={"owner": OWNER, "blocked": False}, headers=auth())
    assert again.json() == {"signer": SIGNER} and [c[0] for c in svc.calls] == ["/keys"]  # a reload: the same key
    other = api.post("/api/me/copy/start", json={"owner": "0x" + "9" * 40, "blocked": False}, headers=auth())
    assert other.status_code == 409
    state = api.get("/api/me/copy", headers=auth()).json()
    assert state["state"] == "ready" and state["wallet"] == DEPOSIT and state["signer"] == SIGNER and "enc" not in str(state)


# ---- builder signing ----


def test_builder_headers_match_the_sdk_and_only_relayer_calls_are_signed(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from polymarket._internal.hmac import build_hmac_signature

    secret = "c2VjcmV0LXNlY3JldC1zZWNyZXQtc2VjcmV0LXNlY3I="
    monkeypatch.setattr(copying, "BUILDER_KEY", "k")
    monkeypatch.setattr(copying, "BUILDER_SECRET", secret)
    monkeypatch.setattr(copying, "BUILDER_PASSPHRASE", "p")
    body = '{"type":"WALLET-CREATE"}'
    h = api.post("/api/copy/builder-sign", json={"method": "POST", "path": "/submit", "body": body}, headers=auth()).json()
    assert h["POLY_BUILDER_API_KEY"] == "k" and h["POLY_BUILDER_PASSPHRASE"] == "p"
    want = build_hmac_signature(secret=secret, timestamp=int(h["POLY_BUILDER_TIMESTAMP"]), method="POST", path="/submit", body=body)
    assert h["POLY_BUILDER_SIGNATURE"] == want
    for path in ("/order", "/auth/api-key", "/submitx", "/../submit"):
        assert api.post("/api/copy/builder-sign", json={"method": "POST", "path": path}, headers=auth()).status_code == 403
    assert api.post("/api/copy/builder-sign", json={"method": "GET", "path": "/deployed?address=0x1"}, headers=auth()).status_code == 200


def test_builder_signing_stops_after_the_hourly_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, v in (("BUILDER_KEY", "k"), ("BUILDER_SECRET", "c2VjcmV0"), ("BUILDER_PASSPHRASE", "p"), ("_signs", {})):
        monkeypatch.setattr(copying, name, v)
    for _ in range(copying.SIGNS_PER_HOUR):
        copying.builder_headers("u", "POST", "/submit", None, now=1000.0)
    with pytest.raises(copying.CopyError, match="Too many"):
        copying.builder_headers("u", "POST", "/submit", None, now=1000.0)
    copying.builder_headers("u", "POST", "/submit", None, now=1000.0 + 3601)  # an hour later: again


# ---- the button and the tap ----


def test_no_copy_button_until_set_up_then_copy_under_each_buy(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user()
    assert "Copy $25" not in buttons(buy_alert())
    set_up(api, monkeypatch, Service())
    assert buttons(buy_alert())[0] == "Copy $25"
    monkeypatch.setattr(copying, "COPY_USERS", frozenset())  # flag off: gone again
    assert "Copy $25" not in buttons(buy_alert())


def test_a_tap_buys_once_at_most_three_cents_above_the_alert_and_says_what_it_bought(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user()
    svc = Service()
    set_up(api, monkeypatch, svc)
    monkeypatch.setattr(engine.threading, "Thread", Now)
    msg = buy_alert()
    aid = next(b["callback_data"][3:] for row in msg["reply_markup"]["inline_keyboard"] for b in row if b["text"] == "Copy $25")
    tap(f"cp:{aid}")
    path, payload = svc.calls[-1]
    assert path == "/order" and payload == {"enc": "ENC", "wallet": DEPOSIT, "token": "tok-0xcid:0", "usd": 25.0, "max_price": 0.45}
    assert engine.tg.answers[-1]["text"] == "Buying…"
    assert engine.tg.sent[-1]["text"] == "Bought $24.80 at 42¢ (59.0 shares)." and engine.tg.sent[-1]["reply_to_message_id"] == 1
    tap(f"cp:{aid}")  # a second tap: nothing more bought
    assert [c[0] for c in svc.calls].count("/order") == 1 and engine.tg.sent[-1]["text"] == "Already copied."


@pytest.mark.parametrize(("answer", "says"), [
    ({"ok": False, "code": "no_liquidity"}, "Not bought: no one is selling at 45¢ or less right now."),
    ({"ok": False, "code": "not_enough_balance"}, "Not bought: your wallet has less than $25. Add funds on https://usesignals.app/copy"),
    ({"ok": True, "status": "delayed", "order_id": "0xo", "spent": 0, "shares": 0}, "Order sent. Polymarket is still matching it"),
    ({"ok": False, "code": "rejected", "message": "boom"}, "Not bought: Polymarket didn't take the order. Nothing was spent."),
])  # fmt: skip
def test_what_a_tap_says_when_nothing_was_bought(api: TestClient, monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any], says: str) -> None:
    user()
    set_up(api, monkeypatch, Service(answer))
    monkeypatch.setattr(engine.threading, "Thread", Now)
    msg = buy_alert()
    tap(next(b["callback_data"] for row in msg["reply_markup"]["inline_keyboard"] for b in row if b["text"] == "Copy $25"))
    assert engine.tg.sent[-1]["text"].startswith(says)


def test_a_tap_from_an_account_without_the_flag_buys_nothing(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user()
    svc = Service()
    set_up(api, monkeypatch, svc)
    monkeypatch.setattr(engine.threading, "Thread", Now)
    msg = buy_alert()
    monkeypatch.setattr(copying, "COPY_USERS", frozenset())
    tap(next(b["callback_data"] for row in msg["reply_markup"]["inline_keyboard"] for b in row if b["text"] == "Copy $25"))
    assert "/order" not in [c[0] for c in svc.calls] and engine.tg.sent[-1]["text"] == "Copying isn't on for your account."


def test_max_price_is_three_cents_above_never_past_99() -> None:
    assert copying.max_price(0.42) == 0.45 and copying.max_price(0.97) == 0.99 and copying.max_price(0.995) == 0.99


# ---- the order service ----


@pytest.fixture
def svc_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("SIGNALS_COPY_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SIGNALS_COPY_TOKEN", "t0ken")
    monkeypatch.setattr(copy_service, "_geo", {"at": 0.0, "answer": None})
    return TestClient(copy_service.app)


ENGINE = {"Authorization": "Bearer t0ken"}


def test_the_order_service_answers_only_the_engine(svc_app: TestClient) -> None:
    assert svc_app.get("/").json() == {"ok": True}  # Railway's health check: open, says nothing
    assert svc_app.post("/keys").status_code == 401
    assert svc_app.post("/keys", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_a_trading_key_comes_back_encrypted_and_opens_to_its_address(svc_app: TestClient) -> None:
    import os

    from cryptography.fernet import Fernet
    from eth_account import Account

    made = svc_app.post("/keys", headers=ENGINE).json()
    key = Fernet(os.environ["SIGNALS_COPY_KEY"].encode()).decrypt(made["enc"].encode()).decode()
    assert Account.from_key(key).address == made["address"] and key not in made["enc"]


def test_no_order_leaves_while_polymarket_blocks_the_server(svc_app: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    placed: list[Any] = []
    monkeypatch.setattr(copy_service, "place", lambda *a: placed.append(a) or {"ok": True})
    monkeypatch.setattr(copy_service, "geoblock", lambda: {"blocked": True, "country": "US"})
    enc = svc_app.post("/keys", headers=ENGINE).json()["enc"]
    order = {"enc": enc, "wallet": DEPOSIT, "token": "123", "usd": 25, "max_price": 0.45}
    r = svc_app.post("/order", json=order, headers=ENGINE)
    assert r.status_code == 503 and "isn't taking orders from Signals' server" in r.json()["detail"] and placed == []
    monkeypatch.setattr(copy_service, "geoblock", lambda: {"blocked": False, "country": "NL"})
    assert svc_app.post("/order", json=order, headers=ENGINE).json() == {"ok": True} and len(placed) == 1
    assert placed[0][1:] == (DEPOSIT, "123", 25.0, 0.45)


def test_place_sends_a_fak_buy_capped_at_max_price_with_the_builder_code(monkeypatch: pytest.MonkeyPatch) -> None:
    import polymarket
    from eth_account import Account
    from polymarket.models.clob.order_response import AcceptedOrder

    asked: dict[str, Any] = {}

    class Client:
        credentials = "creds"

        @classmethod
        def create(cls, **kw: Any) -> Client:
            asked["create"] = kw
            return cls()

        def place_market_order(self, **kw: Any) -> AcceptedOrder:
            asked["order"] = kw
            return AcceptedOrder(order_id="0x" + "a" * 64, status="matched", making_amount=Decimal("24.8"),
                                 taking_amount=Decimal(59), trade_ids=(), transactions_hashes=())  # fmt: skip

        def close(self) -> None:
            asked["closed"] = True

    monkeypatch.setattr(polymarket, "SecureClient", Client)
    monkeypatch.setenv("SIGNALS_BUILDER_CODE", "0x" + "b" * 64)
    key = Account.create().key.hex()
    got = copy_service.place(key, DEPOSIT, "123", 25, 0.45)
    assert got == {"ok": True, "status": "matched", "order_id": "0x" + "a" * 64, "spent": 24.8, "shares": 59.0}
    assert asked["create"]["wallet"] == DEPOSIT and asked["closed"]
    o = asked["order"]
    assert (o["token_id"], o["side"], o["amount"], o["max_price"], o["order_type"], o["builder_code"]) == (
        "123", "BUY", Decimal(25), Decimal("0.45"), "FAK", "0x" + "b" * 64)
