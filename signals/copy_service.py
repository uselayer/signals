"""The order service for one-tap copy (signals/copying.py): the only part of Signals that places orders.

It runs on its own (SIGNALS_ROLE=copy in the Dockerfile) in a region Polymarket takes orders from: Polymarket decides
by the IP an order comes from, and the engine runs in the US. It keeps no data. It makes trading keys and returns
them encrypted with SIGNALS_COPY_KEY, which only it holds, so the engine stores keys it can't use. Each order comes
from the engine (SIGNALS_COPY_TOKEN), with the follower's encrypted key, their Deposit Wallet, the outcome, the
dollars and the highest price per share; it is a FAK market buy (fills what it can at or under that price, the rest
is cancelled), credited to Signals' builder code.

Before any order it asks Polymarket's geoblock about its own IP, and refuses to send one when Polymarket says no.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
import urllib.request
from decimal import Decimal
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from eth_account import Account
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

GEOBLOCK_URL = "https://polymarket.com/api/geoblock"
GEOBLOCK_S = 600  # asked again at most every 10 minutes
# Polymarket's geoblock "blocked" also covers places that are close-only on its website but whose API isn't
# restricted (docs.polymarket.com/api-reference/geoblock, 11 Nov 2026). The order service only uses the API, so a
# server there may send orders. Followers in these places are still refused at set-up (/copy asks "blocked").
API_OPEN = frozenset({"IE", "JP", "NL", "KR"})

app = FastAPI(title="Signals copy", docs_url=None, redoc_url=None, openapi_url=None)
_creds: dict[str, Any] = {}  # trading key address → its CLOB credentials (made once per key per process)
_geo: dict[str, Any] = {"at": 0.0, "answer": None}
_geo_lock = threading.Lock()


def _fernet() -> Fernet:
    key = os.environ.get("SIGNALS_COPY_KEY", "")
    if not key:
        raise HTTPException(503, detail="Copying isn't set up here yet.")
    return Fernet(key.encode())


def engine_only(request: Request) -> None:
    """Only the engine, with the shared token."""
    token = os.environ.get("SIGNALS_COPY_TOKEN", "")
    got = request.headers.get("authorization", "")
    if not token or not hmac.compare_digest(got.encode(), f"Bearer {token}".encode()):
        raise HTTPException(401, detail="Not allowed.")


def server_may_order(g: dict[str, Any]) -> bool:
    """Whether Polymarket's API takes orders from this server's IP: not blocked, or blocked only on the website."""
    return not g.get("blocked") or g.get("country") in API_OPEN


def geoblock(now: float | None = None) -> dict[str, Any]:
    """Polymarket's answer about this server's IP ({blocked, country, region, ip}), kept for GEOBLOCK_S."""
    now = time.time() if now is None else now
    with _geo_lock:
        if _geo["answer"] is not None and now - _geo["at"] < GEOBLOCK_S:
            return dict(_geo["answer"])
        with urllib.request.urlopen(urllib.request.Request(GEOBLOCK_URL, headers={"User-Agent": "signals-copy"}), timeout=10) as r:
            answer = dict(json.loads(r.read()))
        _geo.update(at=now, answer=answer)
        return dict(answer)


class OrderIn(BaseModel):
    enc: str
    wallet: str = Field(pattern=r"^0x[0-9a-fA-F]{40}$")
    token: str = Field(pattern=r"^[0-9]{1,80}$")
    usd: float = Field(gt=0, le=1000)
    max_price: float = Field(gt=0, lt=1)


@app.get("/")
def root() -> dict[str, bool]:
    """Railway's health check (railway.json checks "/" for every service built from this repo): up, nothing more."""
    return {"ok": True}


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        g = geoblock()
    except (OSError, ValueError):
        return {"ok": False, "geoblock": None}
    return {"ok": server_may_order(g), "country": g.get("country"), "region": g.get("region")}


@app.post("/keys", dependencies=[Depends(engine_only)])
def make_key() -> dict[str, str]:
    """A new trading key: its address, and the key encrypted (only this service can open it)."""
    acct = Account.create()
    return {"address": acct.address, "enc": _fernet().encrypt(acct.key.hex().encode()).decode()}


@app.post("/order", dependencies=[Depends(engine_only)])
def order(req: OrderIn) -> dict[str, Any]:
    """One copy: a FAK market buy of ``usd`` dollars of ``token``, at most ``max_price`` a share, from the
    follower's Deposit Wallet, signed with their trading key."""
    try:
        g = geoblock()
    except (OSError, ValueError) as e:
        raise HTTPException(503, detail="Couldn't check Polymarket just now. Nothing was bought.") from e
    if not server_may_order(g):
        raise HTTPException(503, detail="Polymarket isn't taking orders from Signals' server right now. Nothing was bought.")
    try:
        key = _fernet().decrypt(req.enc.encode()).decode()
    except InvalidToken as e:
        raise HTTPException(400, detail="This copy can't be placed. Set up copying again.") from e
    return place(key, req.wallet, req.token, req.usd, req.max_price)


def place(key: str, wallet: str, token: str, usd: float, max_price: float) -> dict[str, Any]:
    """Sign and send the order (polymarket-client, session-key mode: the key isn't the wallet's owner)."""
    from polymarket import SecureClient
    from polymarket.errors import InsufficientLiquidityError, PolymarketError

    signer = Account.from_key(key).address
    try:
        client = SecureClient.create(private_key=key, wallet=wallet, credentials=_creds.get(signer))
    except PolymarketError as e:
        return {"ok": False, "code": "setup", "message": str(e)[:300]}
    try:
        _creds[signer] = client.credentials
        r = client.place_market_order(token_id=token, side="BUY", amount=Decimal(str(round(usd, 2))),
                                      max_price=Decimal(str(max_price)), order_type="FAK",
                                      builder_code=os.environ.get("SIGNALS_BUILDER_CODE") or None)  # fmt: skip
    except InsufficientLiquidityError:
        return {"ok": False, "code": "no_liquidity", "message": "No one is selling at that price."}
    except PolymarketError as e:
        return {"ok": False, "code": "rejected", "message": str(e)[:300]}
    finally:
        client.close()
    if not r.ok:
        return {"ok": False, "code": r.code, "message": r.message}
    return {"ok": True, "status": r.status, "order_id": r.order_id, "spent": float(r.making_amount),
            "shares": float(r.taking_amount)}  # fmt: skip
