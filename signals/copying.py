"""One-tap copy (owner, 11 Nov 2026): "Copy $25" under an alert buys the same outcome on Polymarket
International from the follower's own wallet, only when they tap.

How the pieces fit (AGENTS.md "Copying a trade"):

- The wallet is the follower's. They set it up on /copy: Privy signs them in and holds the wallet's owner key on
  their device; Polymarket deploys their Deposit Wallet; they approve trading, then approve one Signals trading key
  (a Polymarket session key: it can place and cancel orders, it can never withdraw, it ends after 180 days, and they
  can revoke it). Signals never sees the owner key.
- The trading key is made, kept (encrypted) and used only by the order service (``copy_service``), which runs in a
  region Polymarket takes orders from. This engine runs in the US (Railway us-east4), where Polymarket takes no new
  orders, so it never places one: it stores only the key's encrypted form and its address, and asks the service.
- Everyone sees it only when their account is in SIGNALS_COPY_USERS (the owner's feature flag: no one else yet).
- People in the US, or anywhere else Polymarket doesn't let open new positions, can't set it up (the page checks
  Polymarket's geoblock from their own browser). They keep the alert's "View on Polymarket US" / "View on Kalshi".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from typing import Any

COPY_USERS = frozenset(u.strip() for u in os.environ.get("SIGNALS_COPY_USERS", "").split(",") if u.strip())
COPY_URL = os.environ.get("SIGNALS_COPY_URL", "").rstrip("/")  # the order service (copy_service)
COPY_TOKEN = os.environ.get("SIGNALS_COPY_TOKEN", "")  # shared with the order service: only this engine may call it
COPY_USD = float(os.environ.get("SIGNALS_COPY_USD", "25"))
# The most a copy pays above the price in the alert. The drift study (11 Nov: 935 buys by the top 30, 36 h of
# recorded books) found the best ask a median 1¢ from the leader's price at 2 s to 60 s; 3¢ leaves room for that and
# stops a copy chasing a price that ran away. Polymarket fills at the resting orders' prices, never above this.
COLLAR = 0.03
TOP_PRICE = 0.99

# Builder credentials (polymarket.com/settings?tab=builder): they pay the gas for the follower's wallet set-up through
# Polymarket's relayer. Only these relayer calls are signed, and only for flagged accounts, a few times an hour: the
# free tier allows 100 relayer transactions a day for every account together.
BUILDER_KEY = os.environ.get("SIGNALS_BUILDER_KEY", "")
BUILDER_SECRET = os.environ.get("SIGNALS_BUILDER_SECRET", "")
BUILDER_PASSPHRASE = os.environ.get("SIGNALS_BUILDER_PASSPHRASE", "")
BUILDER_CODE = os.environ.get("SIGNALS_BUILDER_CODE", "")  # public: signed into every order, sent to the bridge
PRIVY_APP_ID = os.environ.get("SIGNALS_PRIVY_APP_ID", "")  # public: the /copy page's sign-in for the wallet
RELAYER_PATHS = ("/submit", "/relay-payload", "/deployed", "/nonce", "/transaction", "/v2/approvals",
                 "/v1/session-signers/authorizations", "/v1/session-signers/revocations", "/v1/user/session-signers")  # fmt: skip
SIGNS_PER_HOUR = 40

SCHEMA = """
CREATE TABLE IF NOT EXISTS copy_wallets (uid TEXT PRIMARY KEY, owner TEXT, wallet TEXT, signer TEXT NOT NULL,
  signer_enc TEXT NOT NULL, country TEXT, state TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS copy_offers (alert_id TEXT PRIMARY KEY, uid TEXT NOT NULL, token TEXT NOT NULL,
  price REAL NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS copy_orders (alert_id TEXT PRIMARY KEY, uid TEXT NOT NULL, token TEXT NOT NULL,
  usd REAL NOT NULL, max_price REAL NOT NULL, state TEXT NOT NULL, spent REAL, shares REAL, order_id TEXT,
  error TEXT, at REAL NOT NULL);
"""

_signs: dict[str, list[float]] = {}
_signs_lock = threading.Lock()


class CopyError(Exception):
    """Something the follower is told in one plain sentence."""


def on_for(uid: str | None) -> bool:
    """Whether this account sees copying: in the flag, and the order service is set up."""
    return bool(uid) and uid in COPY_USERS and bool(COPY_URL and COPY_TOKEN)


def wallet_of(con: sqlite3.Connection, uid: str) -> dict[str, Any] | None:
    row = con.execute("SELECT owner, wallet, signer, signer_enc, country, state, at FROM copy_wallets WHERE uid = ?",
                      (uid,)).fetchone()  # fmt: skip
    if not row:
        return None
    return dict(zip(("owner", "wallet", "signer", "signer_enc", "country", "state", "at"), row, strict=True))


def ready(con: sqlite3.Connection, uid: str) -> bool:
    """Set up and able to copy: the wallet's trading key approved (state "ready")."""
    w = wallet_of(con, uid)
    return bool(w and w["state"] == "ready" and w["wallet"])


def max_price(price: float) -> float:
    """The most a copy of a buy shown at ``price`` pays a share: ``COLLAR`` above it, never past 99¢."""
    return min(TOP_PRICE, round(price + COLLAR, 2))


def _hmac(secret: str, timestamp: int, method: str, path: str, body: str | None) -> str:
    """Polymarket's request signature (the SDK's build_hmac_signature): URL-safe base64 HMAC-SHA256 of
    timestamp + method + path + body, keyed by the URL-safe base64 secret."""
    raw = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
    msg = f"{timestamp}{method}{path}{body or ''}"
    return base64.urlsafe_b64encode(hmac.new(raw, msg.encode(), hashlib.sha256).digest()).decode()


def builder_headers(uid: str, method: str, path: str, body: str | None, now: float | None = None) -> dict[str, str]:
    """The builder headers for one relayer call made by the follower's browser while setting up (the SDK's
    ``remoteBuilderSigning``). Only relayer paths, only ``SIGNS_PER_HOUR`` an hour per account."""
    if not (BUILDER_KEY and BUILDER_SECRET and BUILDER_PASSPHRASE):
        raise CopyError("Copying isn't set up here yet.")
    bare = path.split("?", 1)[0]
    if method.upper() not in ("GET", "POST", "DELETE") or not any(bare == p or bare.startswith(p + "/") for p in RELAYER_PATHS):
        raise CopyError("That request can't be signed.")
    now = time.time() if now is None else now
    with _signs_lock:
        recent = [t for t in _signs.get(uid, []) if now - t < 3600]
        if len(recent) >= SIGNS_PER_HOUR:
            raise CopyError("Too many set-up steps this hour. Try again later.")
        _signs[uid] = [*recent, now]
    ts = int(now)
    return {"POLY_BUILDER_API_KEY": BUILDER_KEY, "POLY_BUILDER_TIMESTAMP": str(ts), "POLY_BUILDER_PASSPHRASE": BUILDER_PASSPHRASE,
            "POLY_BUILDER_SIGNATURE": _hmac(BUILDER_SECRET, ts, method.upper(), path, body)}  # fmt: skip


def service(path: str, payload: dict[str, Any], timeout: float = 25) -> dict[str, Any]:
    """One call to the order service. Its answer, or CopyError when it can't be reached or refuses."""
    if not (COPY_URL and COPY_TOKEN):
        raise CopyError("Copying isn't set up here yet.")
    req = urllib.request.Request(f"{COPY_URL}{path}", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {COPY_TOKEN}", "Content-Type": "application/json"})  # fmt: skip
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return dict(json.loads(r.read()))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except (ValueError, AttributeError, OSError):
            detail = None
        raise CopyError(detail if isinstance(detail, str) else "Copying didn't work just now. Nothing was bought.") from e
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise CopyError("Couldn't reach Polymarket just now. Nothing was bought.") from e


def start(con: sqlite3.Connection, uid: str, owner: str, country: str | None, now: float | None = None) -> str:
    """The first step on /copy, after the page found the follower may trade (Polymarket's geoblock, from their browser):
    a Signals trading key for them, made by the order service. Its address, which their wallet then approves.
    The same key again if they already have one (a page reload mid-set-up)."""
    w = wallet_of(con, uid)
    if w and w["owner"] and w["owner"].lower() != owner.lower():
        raise CopyError("This account is already set up with another wallet.")
    if w:
        return str(w["signer"])
    made = service("/keys", {})
    con.execute("INSERT INTO copy_wallets (uid, owner, wallet, signer, signer_enc, country, state, at) VALUES"
                " (?, ?, NULL, ?, ?, ?, 'key', ?)",
                (uid, owner, made["address"], made["enc"], country, time.time() if now is None else now))  # fmt: skip
    return str(made["address"])


def finish(con: sqlite3.Connection, uid: str, wallet: str) -> None:
    """The page's last step: their Deposit Wallet is deployed, trading approved and the trading key authorized."""
    if not wallet_of(con, uid):
        raise CopyError("Start setting up copying first.")
    con.execute("UPDATE copy_wallets SET wallet = ?, state = 'ready', at = ? WHERE uid = ?", (wallet, time.time(), uid))


def offer(con: sqlite3.Connection, alert_id: str, uid: str, token: str, price: float) -> None:
    """Keep what a "Copy" button under an alert buys: the outcome and the price the alert showed."""
    con.execute("INSERT OR REPLACE INTO copy_offers VALUES (?, ?, ?, ?, ?)", (alert_id, uid, token, price, time.time()))


def claim(con: sqlite3.Connection, alert_id: str, uid: str, now: float | None = None) -> dict[str, Any]:
    """A tap on "Copy": the order to place, kept as "placing" before it's sent so a second tap never buys twice.
    CopyError when this alert has no copy for this account, it was already copied, or they aren't set up."""
    o = con.execute("SELECT token, price FROM copy_offers WHERE alert_id = ? AND uid = ?", (alert_id, uid)).fetchone()
    if not o:
        raise CopyError("This alert can't be copied.")
    w = wallet_of(con, uid)
    if not (w and w["state"] == "ready"):
        raise CopyError("Set up copying first.")
    done = con.execute("SELECT state FROM copy_orders WHERE alert_id = ?", (alert_id,)).fetchone()
    if done:
        raise CopyError("Already copied." if done[0] == "filled" else "You already tapped Copy on this one.")
    cap = max_price(float(o[1]))
    con.execute("INSERT INTO copy_orders (alert_id, uid, token, usd, max_price, state, at) VALUES (?, ?, ?, ?, ?, 'placing', ?)",
                (alert_id, uid, o[0], COPY_USD, cap, time.time() if now is None else now))  # fmt: skip
    return {"token": o[0], "usd": COPY_USD, "max_price": cap, "wallet": w["wallet"], "enc": w["signer_enc"]}


def record(con: sqlite3.Connection, alert_id: str, answer: dict[str, Any] | None, error: str | None = None) -> None:
    """What the order service said about a copy (``answer``), or why it couldn't be asked (``error``)."""
    if answer and answer.get("ok") and answer.get("status") == "delayed":
        con.execute("UPDATE copy_orders SET state = 'delayed', order_id = ? WHERE alert_id = ?", (answer.get("order_id"), alert_id))
    elif answer and answer.get("ok") and float(answer.get("shares") or 0) > 0:
        con.execute("UPDATE copy_orders SET state = 'filled', spent = ?, shares = ?, order_id = ? WHERE alert_id = ?",
                    (answer.get("spent"), answer.get("shares"), answer.get("order_id"), alert_id))  # fmt: skip
    else:
        why = error or (answer or {}).get("message") or (answer or {}).get("code") or "not filled"
        con.execute("UPDATE copy_orders SET state = 'missed', error = ? WHERE alert_id = ?", (str(why)[:300], alert_id))


def result_text(order: dict[str, Any], answer: dict[str, Any] | None, error: str | None = None) -> str:
    """The reply to a tap: what was bought, or plainly why nothing was."""
    if error:
        return error
    a = answer or {}
    shares, spent = float(a.get("shares") or 0), float(a.get("spent") or 0)
    if a.get("ok") and a.get("status") == "delayed":
        return "Order sent. Polymarket is still matching it: check your positions in a minute."
    if a.get("ok") and shares > 0:
        return f"Bought ${spent:,.2f} at {round(spent / shares * 100)}¢ ({shares:,.1f} shares)."
    code = a.get("code")
    if code in ("fak_not_filled", "fok_not_filled", "unmatched", "no_liquidity"):
        return f"Not bought: no one is selling at {round(order['max_price'] * 100)}¢ or less right now."
    if code == "not_enough_balance":
        return f"Not bought: your wallet has less than ${order['usd']:,.0f}. Add funds on {_site()}/copy"
    if code == "market_not_ready":
        return "Not bought: this market isn't taking orders right now."
    return "Not bought: Polymarket didn't take the order. Nothing was spent."


def _site() -> str:
    return os.environ.get("SIGNALS_SITE", "https://usesignals.app")
