"""Who's asking: the same Clerk session check as the engine's (``signals/app.py`` ``_session``): the page's
``Authorization: Bearer`` token, checked against Clerk's public keys (no Clerk secret), expiry, issuer and origin.

TODO: move ``clerk_frontend_api``/``_session`` into a module both services import (importing ``signals.app`` here
would start the engine). Until then keep this in step with app.py's.
"""

from __future__ import annotations

import base64
import os
import re

import jwt
from fastapi import HTTPException, Request

CLERK_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")  # the publishable key, as the engine has it
SITE = os.environ.get("SIGNALS_SITE", "https://usesignals.app")
LOCAL_USER = "local"

_jwks: jwt.PyJWKClient | None = None


def clerk_frontend_api(key: str) -> str | None:
    m = re.fullmatch(r"pk_(?:test|live)_([A-Za-z0-9+/=_-]+)", key)
    if not m:
        return None
    raw = m.group(1)
    try:
        host = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode()
    except ValueError:
        return None
    return host[:-1] if host.endswith("$") and len(host) > 1 else None


def _signing_key(token: str, fapi: str) -> object:
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(f"https://{fapi}/.well-known/jwks.json", cache_keys=True)
    return _jwks.get_signing_key_from_jwt(token).key


def user_of(request: Request) -> str:
    """The signed-in Clerk user id, or 401. Without Clerk's key (running locally) everyone is ``local``; the hosted
    service refuses to start that way (``server.py``)."""
    fapi = clerk_frontend_api(CLERK_KEY)
    if not fapi:
        return LOCAL_USER
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not token:
        raise HTTPException(401, detail="Sign in to use Research.")
    try:
        claims = jwt.decode(token, _signing_key(token, fapi), algorithms=["RS256"], issuer=f"https://{fapi}",
                            options={"require": ["exp", "iat", "sub"]}, leeway=5)  # fmt: skip
    except jwt.PyJWKClientConnectionError as e:
        raise HTTPException(503, detail="Couldn't check your sign-in just now. Try again in a minute.") from e
    except jwt.PyJWTError as e:
        raise HTTPException(401, detail="Your sign-in has expired. Sign in again.") from e
    if claims.get("azp") and claims["azp"] != SITE:
        raise HTTPException(401, detail="Sign in to use Research on this site.")
    return str(claims["sub"])
