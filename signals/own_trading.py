"""The owner's own one-tap copy on Kalshi and Polymarket US (owner, 11 Nov 2026: "I should be able to copy trade on
poly us or kalshi").

Only the owner's account (SIGNALS_OWN_UID), with the owner's own exchange keys: Signals' software trading its owner's
own account, which both exchanges allow (Kalshi's Developer Agreement: the API is for "a member's own trading").
It never takes anyone else's exchange keys: both exchanges forbid that (AGENTS.md "Copying a trade").

Under a buy alert whose outcome has a verified match on Kalshi or Polymarket US (us_match), "Copy $25 on Kalshi" /
"Copy $25 on Polymarket US". A tap sends an IOC buy through the uselayer SDK (live): $25 of contracts at most COLLAR
above the price the alert showed; what doesn't fill at once is cancelled. Never a sell, never without a tap, at
most OWN_DAILY_USD a UTC day. The engine runs in the US, where both exchanges are open.

A limit order after a miss (owner, 11 Nov 2026: "then do a limit order"): when nobody was selling at that price, the
"Not bought" reply carries "Leave a limit order at 43¢". A tap rests the same buy (same size, same top price) in the
exchange's book for LIMIT_MIN minutes; the exchange itself ends it then. "Cancel order" under the reply ends it
sooner. ``check`` (the engine's loop) reads it back until it's over and the bot says what was bought, if anything.
Still one order per alert, still counted in the day's limit while it rests.
"""

from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from signals import copying

OWN_UID = os.environ.get("SIGNALS_OWN_UID", "")
OWN_USD = float(os.environ.get("SIGNALS_OWN_USD", "25"))
OWN_DAILY_USD = float(os.environ.get("SIGNALS_OWN_DAILY_USD", "250"))
LIMIT_MIN = float(os.environ.get("SIGNALS_OWN_LIMIT_MIN", "30"))  # how long a limit order rests
VENUES = {"k": ("kalshi", "Kalshi"), "u": ("polymarket_us", "Polymarket US")}
NOBODY_SELLING = ("not_filled", "no_liquidity")  # the misses a limit order answers
_lock = threading.Lock()  # one SDK client at a time on the own-trading store (a tap, a cancel, the loop's check)

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_offers (alert_id TEXT NOT NULL, code TEXT NOT NULL, uid TEXT NOT NULL,
  market TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, at REAL NOT NULL, PRIMARY KEY (alert_id, code));
CREATE TABLE IF NOT EXISTS own_limits (alert_id TEXT PRIMARY KEY, uid TEXT NOT NULL, code TEXT NOT NULL,
  market TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, size REAL NOT NULL, state TEXT NOT NULL,
  order_id TEXT, chat TEXT, message_id INTEGER, expires_at REAL, at REAL NOT NULL);
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
                      " AND state IN ('placing', 'filled', 'delayed', 'resting')", (uid, day0)).fetchone()  # fmt: skip
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


def _client(code: str, store_dir: Path) -> Any:
    """The SDK, live, with the owner's key for this one venue."""
    from uselayer import Client
    from uselayer.venues.kalshi import Kalshi
    from uselayer.venues.polymarket_us_live import PolymarketUS

    key_id, secret = _keys(code)
    venue = {"kalshi": Kalshi(key_id=key_id, private_key_pem=secret)} if code == "k" else {
        "polymarket_us": PolymarketUS(key_id=key_id, secret_key=secret)}  # fmt: skip
    return Client(mode="live", store=store_dir / "own-trading", **venue)  # type: ignore[arg-type]


def _bought(o: Any, top: float) -> dict[str, Any]:
    """What an order has bought so far."""
    filled = float(o.filled or 0)
    avg = float(o.avg_price or top)
    return {"status": o.status, "order_id": o.venue_order_id or o.id, "shares": filled,
            "spent": round(filled * avg + float(o.fees or 0), 2), "avg": avg}  # fmt: skip


def place(order: dict[str, Any], store_dir: Path) -> dict[str, Any]:
    """Send it: an IOC buy of ``size`` contracts at most ``max_price``, with the owner's key for that venue."""
    from uselayer import VenueError

    if order["size"] < 1:
        return {"ok": False, "code": "too_small"}
    try:
        with _lock, _client(order["code"], store_dir) as client:
            o = client.buy(venue=order["venue"], market=order["market"], side=order["side"], price=order["max_price"],
                           size=order["size"], tif="ioc")  # fmt: skip
    except VenueError as e:
        return {"ok": False, "code": e.code, "message": e.message}
    if float(o.filled or 0) <= 0:
        return {"ok": False, "code": "not_filled", "status": o.status}
    return {"ok": True} | _bought(o, order["max_price"])


# ---- a limit order after a miss ----

_LIMIT_COLS = "alert_id, uid, code, market, side, price, size, state, order_id, chat, message_id, expires_at"


def limit_button(alert_id: str, order: dict[str, Any]) -> dict[str, str]:
    return {"text": f"Leave a limit order at {round(order['max_price'] * 100)}¢", "callback_data": f"cl:{alert_id}"}


def cancel_button(alert_id: str) -> dict[str, str]:
    return {"text": "Cancel order", "callback_data": f"cx:{alert_id}"}


def offer_limit(con: sqlite3.Connection, alert_id: str, uid: str, order: dict[str, Any]) -> None:
    """Nobody was selling at the top price: the same buy is kept, to rest as a limit order on a tap."""
    con.execute("INSERT OR REPLACE INTO own_limits (alert_id, uid, code, market, side, price, size, state, at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'offered', ?)",
                (alert_id, uid, order["code"], order["market"], order["side"], order["max_price"], order["size"], time.time()))  # fmt: skip


def _limit(row: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(("alert_id", "uid", "code", "market", "side", "max_price", "size", "state", "order_id", "chat",
                  "message_id", "expires_at"), row, strict=True))  # fmt: skip
    return d | {"venue": VENUES[d["code"]][0], "name": VENUES[d["code"]][1], "usd": OWN_USD, "minutes": LIMIT_MIN}


def claim_limit(con: sqlite3.Connection, alert_id: str, uid: str, now: float | None = None) -> dict[str, Any]:
    """A tap on "Leave a limit order": the order to rest, kept as "placing" first (a second tap never rests two).
    CopyError when it wasn't offered, was tapped already, or today's limit is reached."""
    now = time.time() if now is None else now
    if not on_for(uid):
        raise copying.CopyError("Copying isn't on for your account.")
    row = con.execute(f"SELECT {_LIMIT_COLS} FROM own_limits WHERE alert_id = ? AND uid = ?", (alert_id, uid)).fetchone()
    if not row or not has(row[2]):
        raise copying.CopyError("There's no limit order to leave for this alert.")
    if row[7] != "offered":
        raise copying.CopyError("Your limit order is already there." if row[7] == "resting" else "You already tapped this one.")
    if _spent_today(con, uid, now) + OWN_USD > OWN_DAILY_USD:
        raise copying.CopyError(f"Not placed: that would pass today's copy limit of ${OWN_DAILY_USD:,.0f}.")
    con.execute("UPDATE own_limits SET state = 'placing' WHERE alert_id = ?", (alert_id,))
    con.execute("UPDATE copy_orders SET state = 'placing', error = NULL, at = ? WHERE alert_id = ?", (now, alert_id))
    return _limit(row)


def place_limit(order: dict[str, Any], store_dir: Path, now: float | None = None) -> dict[str, Any]:
    """Rest it: a buy of ``size`` contracts at most ``max_price`` that stays in the book for LIMIT_MIN minutes
    (the exchange ends it then, whatever happens to the engine)."""
    from uselayer import VenueError

    expires = (time.time() if now is None else now) + LIMIT_MIN * 60
    try:
        with _lock, _client(order["code"], store_dir) as client:
            o = client.buy(venue=order["venue"], market=order["market"], side=order["side"], price=order["max_price"],
                           size=order["size"], tif="gtc", expires_at=datetime.fromtimestamp(expires, UTC))  # fmt: skip
    except VenueError as e:
        return {"ok": False, "code": e.code, "message": e.message}
    return {"ok": True, "sdk_id": o.id or o.client_id, "expires_at": expires,
            "over": o.status not in ("pending", "open")} | _bought(o, order["max_price"])  # fmt: skip


def check(order: dict[str, Any], store_dir: Path, *, cancel: bool = False) -> dict[str, Any] | None:
    """A resting limit order read back from the exchange (``cancel``: ended first). None when it couldn't be read
    or the SDK no longer knows it; ``over`` once it's filled, ended or cancelled."""
    from uselayer import VenueError

    try:
        with _lock, _client(order["code"], store_dir) as client:
            o = client.cancel(order["order_id"]) if cancel else next(
                (x for x in client.orders(open=False) if order["order_id"] in (x.id, x.client_id)), None)  # fmt: skip
    except VenueError:
        return None
    if o is None:
        return None
    return {"over": o.status not in ("pending", "open")} | _bought(o, order["max_price"])


def rest(con: sqlite3.Connection, alert_id: str, answer: dict[str, Any], chat: str, message_id: int | None) -> None:
    """The limit order is in the book: kept with where to say how it ended."""
    con.execute("UPDATE own_limits SET state = 'resting', order_id = ?, chat = ?, message_id = ?, expires_at = ? WHERE alert_id = ?",
                (answer["sdk_id"], chat, message_id, answer["expires_at"], alert_id))  # fmt: skip
    con.execute("UPDATE copy_orders SET state = 'resting', order_id = ? WHERE alert_id = ?", (answer.get("order_id"), alert_id))


def resting(con: sqlite3.Connection, alert_id: str | None = None, uid: str | None = None) -> list[dict[str, Any]]:
    """The limit orders in the book now (``alert_id`` and ``uid``: that account's one, for a cancel tap)."""
    q, args = f"SELECT {_LIMIT_COLS} FROM own_limits WHERE state = 'resting'", ()
    if alert_id is not None:
        q, args = q + " AND alert_id = ? AND uid = ?", (alert_id, uid or "")
    return [_limit(r) for r in con.execute(q, args).fetchall()]


def settle(con: sqlite3.Connection, alert_id: str, answer: dict[str, Any], *, was: str = "resting") -> bool:
    """A limit order is over: what it bought is kept (nothing: the day's limit gets its dollars back). False when
    someone else (the loop, a cancel tap) settled it first, so it's said once."""
    if con.execute("UPDATE own_limits SET state = 'done' WHERE alert_id = ? AND state = ?", (alert_id, was)).rowcount != 1:
        return False
    if float(answer.get("shares") or 0) > 0:
        con.execute("UPDATE copy_orders SET state = 'filled', spent = ?, shares = ?, order_id = ? WHERE alert_id = ?",
                    (answer.get("spent"), answer.get("shares"), answer.get("order_id"), alert_id))  # fmt: skip
    else:
        why = answer.get("message") or answer.get("code") or f"limit order {answer.get('status') or 'ended'}"
        con.execute("UPDATE copy_orders SET state = 'missed', error = ? WHERE alert_id = ?", (str(why)[:300], alert_id))
    return True


def _for(minutes: float) -> str:
    return f"{minutes:g} min" if minutes < 120 else f"{minutes / 60:g} h"


def limit_text(order: dict[str, Any], answer: dict[str, Any], *, cancelled: bool = False) -> str:
    """What the bot says about a limit order: left in the book, or how it ended."""
    where, top, got = order["name"], round(order["max_price"] * 100), float(answer.get("shares") or 0)
    if not answer.get("ok", True):
        return result_text(order, answer).replace("Not bought:", "No limit order:")
    bought = f"${float(answer.get('spent') or 0):,.2f} at {round(float(answer.get('avg') or order['max_price']) * 100)}¢"
    if not answer.get("over"):
        return (f"Limit order left on {where}: {order['size']:,.0f} contracts at {top}¢ or less, for {_for(order['minutes'])}."
                " You'll hear here if it fills.")  # fmt: skip
    if got >= float(order["size"]) - 1e-6:
        return f"Limit order filled: bought {bought} on {where} ({got:,.0f} contracts)."
    how = "cancelled" if cancelled else "ended"
    if got > 0:
        return f"Limit order {how}: bought {bought} on {where} ({got:,.0f} of {order['size']:,.0f} contracts)."
    return f"Limit order {how}: nothing was bought on {where}."


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
