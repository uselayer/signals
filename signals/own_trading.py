"""The owner's own one-tap copy on Kalshi and Polymarket US (owner, 11 Nov 2026: "I should be able to copy trade on
poly us or kalshi").

Only the owner's account (SIGNALS_OWN_UID), with the owner's own exchange keys: Signals' software trading its owner's
own account, which both exchanges allow (Kalshi's Developer Agreement: the API is for "a member's own trading").
It never takes anyone else's exchange keys: both exchanges forbid that (AGENTS.md "Copying a trade").

Under a buy alert whose outcome has a verified match on Kalshi or Polymarket US (us_match), "Copy $25 on Kalshi" /
"Copy $25 on Polymarket US". A tap sends an IOC buy through the uselayer SDK (live): $25 of contracts at most COLLAR
above the price the alert showed; what doesn't fill at once is cancelled. Never a sell, never without a tap, at
most OWN_DAILY_USD a UTC day. The engine runs in the US, where both exchanges are open.
"""

from __future__ import annotations

import math
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signals import copying

OWN_UID = os.environ.get("SIGNALS_OWN_UID", "")
OWN_USD = float(os.environ.get("SIGNALS_OWN_USD", "25"))
OWN_DAILY_USD = float(os.environ.get("SIGNALS_OWN_DAILY_USD", "250"))
VENUES = {"k": ("kalshi", "Kalshi"), "u": ("polymarket_us", "Polymarket US")}

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_offers (alert_id TEXT NOT NULL, code TEXT NOT NULL, uid TEXT NOT NULL,
  market TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, at REAL NOT NULL, PRIMARY KEY (alert_id, code));
"""


def _keys(code: str) -> tuple[str, str]:
    if code == "k":
        return os.environ.get("SIGNALS_OWN_KALSHI_KEY_ID", ""), os.environ.get("SIGNALS_OWN_KALSHI_PRIVATE_KEY", "")
    return os.environ.get("SIGNALS_OWN_PMUS_KEY_ID", ""), os.environ.get("SIGNALS_OWN_PMUS_SECRET", "")


def has(code: str) -> bool:
    """Whether the owner's key for this venue is set."""
    return all(_keys(code))


def on_for(uid: str | None) -> bool:
    """Only the owner's own account, and only with at least one of their exchange keys set."""
    return bool(OWN_UID) and uid == OWN_UID and any(has(c) for c in VENUES)


def button(alert_id: str, code: str) -> dict[str, str]:
    return {"text": f"Copy ${OWN_USD:g} on {VENUES[code][1]}", "callback_data": f"cv:{alert_id}:{code}"}


def offer(con: sqlite3.Connection, alert_id: str, uid: str, code: str, market: str, side: str, price: float) -> None:
    con.execute("INSERT OR REPLACE INTO own_offers VALUES (?, ?, ?, ?, ?, ?, ?)", (alert_id, code, uid, market, side, price, time.time()))


def _spent_today(con: sqlite3.Connection, uid: str, now: float) -> float:
    day0 = datetime.fromtimestamp(now, UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    row = con.execute("SELECT COALESCE(SUM(COALESCE(spent, usd)), 0) FROM copy_orders WHERE uid = ? AND at >= ?"
                      " AND state IN ('placing', 'filled', 'delayed')", (uid, day0)).fetchone()  # fmt: skip
    return float(row[0])


def claim(con: sqlite3.Connection, alert_id: str, uid: str, code: str, now: float | None = None) -> dict[str, Any]:
    """A tap: the order to send, kept as "placing" first (one copy per alert, whichever venue: never twice).
    CopyError when there's no such offer, it was copied already, or today's limit is reached."""
    now = time.time() if now is None else now
    if not on_for(uid) or code not in VENUES or not has(code):
        raise copying.CopyError("Copying isn't on for your account.")
    o = con.execute("SELECT market, side, price FROM own_offers WHERE alert_id = ? AND code = ? AND uid = ?",
                    (alert_id, code, uid)).fetchone()  # fmt: skip
    if not o:
        raise copying.CopyError("This alert can't be copied.")
    done = con.execute("SELECT state FROM copy_orders WHERE alert_id = ?", (alert_id,)).fetchone()
    if done:
        raise copying.CopyError("Already copied." if done[0] == "filled" else "You already tapped Copy on this one.")
    if _spent_today(con, uid, now) + OWN_USD > OWN_DAILY_USD:
        raise copying.CopyError(f"Not bought: that would pass today's copy limit of ${OWN_DAILY_USD:,.0f}.")
    cap = copying.max_price(float(o[2]))
    con.execute("INSERT INTO copy_orders (alert_id, uid, token, usd, max_price, state, at) VALUES (?, ?, ?, ?, ?, 'placing', ?)",
                (alert_id, uid, f"{VENUES[code][0]}:{o[0]}:{o[1]}", OWN_USD, cap, now))  # fmt: skip
    return {"code": code, "venue": VENUES[code][0], "name": VENUES[code][1], "market": o[0], "side": o[1],
            "usd": OWN_USD, "max_price": cap, "size": math.floor(OWN_USD / cap)}  # fmt: skip


def place(order: dict[str, Any], store_dir: Path) -> dict[str, Any]:
    """Send it: an IOC buy of ``size`` contracts at most ``max_price``, with the owner's key for that venue."""
    from uselayer import Client, VenueError
    from uselayer.venues.kalshi import Kalshi
    from uselayer.venues.polymarket_us_live import PolymarketUS

    if order["size"] < 1:
        return {"ok": False, "code": "too_small"}
    key_id, secret = _keys(order["code"])
    venue = {"kalshi": Kalshi(key_id=key_id, private_key_pem=secret)} if order["code"] == "k" else {
        "polymarket_us": PolymarketUS(key_id=key_id, secret_key=secret)}  # fmt: skip
    try:
        with Client(mode="live", store=store_dir / "own-trading", **venue) as client:  # type: ignore[arg-type]
            o = client.buy(venue=order["venue"], market=order["market"], side=order["side"], price=order["max_price"],
                           size=order["size"], tif="ioc")  # fmt: skip
    except VenueError as e:
        return {"ok": False, "code": e.code, "message": e.message}
    filled = float(o.filled or 0)
    if filled <= 0:
        return {"ok": False, "code": "not_filled", "status": o.status}
    avg = float(o.avg_price or order["max_price"])
    return {"ok": True, "status": o.status, "order_id": o.venue_order_id or o.id, "shares": filled,
            "spent": round(filled * avg + float(o.fees or 0), 2), "avg": avg}  # fmt: skip


def result_text(order: dict[str, Any], answer: dict[str, Any] | None, error: str | None = None) -> str:
    """The reply under the alert."""
    if error:
        return error
    a, where = answer or {}, order["name"]
    if a.get("ok"):
        return f"Bought ${a['spent']:,.2f} at {round(a['avg'] * 100)}¢ on {where} ({a['shares']:,.0f} contracts)."
    code = a.get("code")
    if code in ("not_filled", "no_liquidity"):
        return f"Not bought: no one is selling at {round(order['max_price'] * 100)}¢ or less on {where} right now."
    if code in ("insufficient_balance", "insufficient_funds", "not_enough_balance"):
        return f"Not bought: your {where} balance is under ${order['usd']:,.0f}."
    if code == "too_small":
        return "Not bought: the price is too high for one contract at this amount."
    if code == "outcome_unknown":
        return f"Not sure the order went through: {where} didn't answer in time. Check your {where} positions before tapping again."
    if code == "market_closed":
        return f"Not bought: this market isn't trading on {where} right now."
    if code == "auth_failed":
        return f"Not bought: {where} didn't accept your API key. Check it in Railway."
    return f"Not bought: {where} didn't take the order ({a.get('message') or code or 'unknown'}). Nothing was spent."
