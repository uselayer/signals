"""The owner's own one-tap copy on Kalshi and Polymarket US (owner, 11 Nov 2026: "I should be able to copy trade on
poly us or kalshi").

Only the owner's account (SIGNALS_OWN_UID), with the owner's own exchange keys: Signals' software trading its owner's
own account, which both exchanges allow (Kalshi's Developer Agreement: the API is for "a member's own trading").
It never takes anyone else's exchange keys: both exchanges forbid that (AGENTS.md "Copying a trade").

Under a buy alert whose outcome has a verified match on Kalshi or Polymarket US (us_match), "Copy $25 on Kalshi" /
"Copy $25 on Polymarket US". A tap sends an IOC buy through the uselayer SDK (live): that many dollars of contracts
at most COLLAR above the price the alert showed; what doesn't fill at once is cancelled. Never a sell, never without
a tap, at most OWN_DAILY_USD a UTC day. The engine runs in the US, where both exchanges are open.

The amount (owner, 11 Nov 2026: "sometimes i wanna use $5 not just $25"): the usual one is a setting (/copy, then
Amount); "Other amount" under an alert changes it for that one trade. Each alert keeps the amount its buttons show,
so a tap never buys a size the button didn't say.

When nobody is selling at the top price (owner, 11 Nov 2026: "then do a limit order"), the setting "If it doesn't
fill" decides: ask each time (the default: nothing rests without a tap), leave a limit order, or skip. A limit order
is the same buy (same size, same top price) resting in the exchange's book for the minutes chosen; the exchange
itself ends it then. "Cancel order" ends it sooner; "Buy now at 46¢" buys from the cheapest seller the reply showed,
at most that price, and only on that tap. ``check`` (the engine's loop) reads a resting order back until it's over
and the bot says what was bought, if anything. Still one order per alert, still counted in the day's limit while it
rests.
"""

from __future__ import annotations

import html
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
OWN_USD = float(os.environ.get("SIGNALS_OWN_USD", "25"))  # the usual amount until /copy changes it
OWN_DAILY_USD = float(os.environ.get("SIGNALS_OWN_DAILY_USD", "250"))
LIMIT_MIN = float(os.environ.get("SIGNALS_OWN_LIMIT_MIN", "30"))  # how long a limit order rests until /copy changes it
MIN_USD = 1.0  # one contract never costs more than 99¢
AMOUNTS = (5.0, 10.0, 50.0)  # the amounts offered as buttons; "Type it" takes any other
WAITS = (15.0, 30.0, 60.0)  # minutes a limit order may rest
MISS = {"l": "limit", "a": "ask", "s": "skip"}  # "If it doesn't fill"
VENUES = {"k": ("kalshi", "Kalshi"), "u": ("polymarket_us", "Polymarket US")}
NOBODY_SELLING = ("not_filled", "no_liquidity")  # the misses a limit order answers
TAPS = ("cv", "ca", "cu", "ct", "cl", "cw", "ck", "cb", "cx", "os", "oa", "om", "ow", "noop")  # this module's buttons
_lock = threading.Lock()  # one SDK client at a time on the own-trading store (a tap, a cancel, the loop's check)

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_offers (alert_id TEXT NOT NULL, code TEXT NOT NULL, uid TEXT NOT NULL,
  market TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, at REAL NOT NULL, usd REAL, label TEXT, title TEXT,
  trader TEXT, url TEXT, PRIMARY KEY (alert_id, code));
CREATE TABLE IF NOT EXISTS own_limits (alert_id TEXT PRIMARY KEY, uid TEXT NOT NULL, code TEXT NOT NULL,
  market TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, size REAL NOT NULL, usd REAL NOT NULL,
  minutes REAL NOT NULL, ask REAL, state TEXT NOT NULL, order_id TEXT, chat TEXT, message_id INTEGER,
  expires_at REAL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS own_settings (uid TEXT PRIMARY KEY, usd REAL, miss TEXT, wait REAL);
"""
_OFFER_ADDED = (("usd", "REAL"), ("label", "TEXT"), ("title", "TEXT"), ("trader", "TEXT"), ("url", "TEXT"))


def migrate(con: sqlite3.Connection) -> None:
    """An alerts.db from before an offer kept its amount and names: add those columns, once."""
    have = {r[1] for r in con.execute("PRAGMA table_info(own_offers)")}
    for col, kind in _OFFER_ADDED:
        if col not in have:
            con.execute(f"ALTER TABLE own_offers ADD COLUMN {col} {kind}")


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


# ---- words ----


def money(usd: float) -> str:
    """$25, or $7.50 when it has cents."""
    return f"${usd:,.0f}" if float(usd).is_integer() else f"${usd:,.2f}"


def cents(price: float) -> int:
    return round(float(price) * 100)


def wait_text(minutes: float) -> str:
    return f"{minutes:g} min" if minutes < 60 else "1 hour" if minutes == 60 else f"{minutes / 60:g} hours"


def _e(s: Any) -> str:
    return html.escape(str(s), quote=False)


# ---- settings (/copy) ----


def settings(con: sqlite3.Connection, uid: str) -> dict[str, Any]:
    """The account's copy settings: the usual amount, what a copy that doesn't fill does and how long a limit order
    waits. Ask each time until they choose otherwise: nothing rests in a book without a tap."""
    row = con.execute("SELECT usd, miss, wait FROM own_settings WHERE uid = ?", (uid,)).fetchone() or (None, None, None)
    return {"usd": float(row[0]) if row[0] and valid_usd(float(row[0])) else min(OWN_USD, OWN_DAILY_USD),
            "miss": row[1] if row[1] in MISS.values() else "ask",
            "wait": float(row[2]) if row[2] in WAITS else LIMIT_MIN}  # fmt: skip


def save(con: sqlite3.Connection, uid: str, **changed: Any) -> dict[str, Any]:
    """Change some settings (``usd``, ``miss``, ``wait``); all of them as they now are."""
    s = settings(con, uid) | changed
    con.execute("INSERT OR REPLACE INTO own_settings (uid, usd, miss, wait) VALUES (?, ?, ?, ?)", (uid, s["usd"], s["miss"], s["wait"]))
    return s


def valid_usd(usd: float) -> bool:
    """An amount a copy can be: from MIN_USD to the day's limit."""
    return MIN_USD <= usd <= OWN_DAILY_USD


_MISS_SAYS = {"limit": "leave a limit order", "ask": "ask me each time", "skip": "skip the trade"}


def settings_text(s: dict[str, Any]) -> str:
    lines = ["<b>Your copy settings</b>", "Used every time you tap Copy under an alert.", "",
             f"Amount: {money(s['usd'])} a trade",
             f"Top price: up to {cents(copying.COLLAR)}¢ above the alert's price",
             f"If it doesn't fill: {_MISS_SAYS[s['miss']]}"]  # fmt: skip
    if s["miss"] != "skip":
        lines.append(f"Limit order waits: {wait_text(s['wait'])}")
    return "\n".join([*lines, f"Most in a day: {money(OWN_DAILY_USD)}"])


def settings_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "Amount", "callback_data": "os:a"},
                                 {"text": "If it doesn't fill", "callback_data": "os:m"}]]}  # fmt: skip


def _ticked(text: str, on: bool) -> str:
    return f"✓ {text}" if on else text


def amount_text(s: dict[str, Any]) -> str:
    return f"<b>Your usual amount?</b>\nEvery Copy button shows this amount. Now {money(s['usd'])}."


def amount_markup(s: dict[str, Any]) -> dict[str, Any]:
    row = [{"text": _ticked(money(a), a == s["usd"]), "callback_data": f"oa:{a:g}"} for a in AMOUNTS if valid_usd(a)]
    return {"inline_keyboard": [[*row, {"text": "Type it", "callback_data": "oa:t"}]]}


MISS_TEXT = ("<b>If no one is selling at your top price?</b>\nA limit order waits in the exchange's book at your top "
             "price. It buys only if a seller comes down to it, and never pays more.")  # fmt: skip
WAIT_TEXT = "<b>How long should it wait?</b>"


def miss_markup(s: dict[str, Any]) -> dict[str, Any]:
    names = (("l", "Leave a limit order"), ("a", "Ask me each time"), ("s", "Skip the trade"))
    return {"inline_keyboard": [[{"text": _ticked(t, MISS[k] == s["miss"]), "callback_data": f"om:{k}"}] for k, t in names]}


def wait_markup(s: dict[str, Any]) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": _ticked(wait_text(w), w == s["wait"]), "callback_data": f"ow:{w:g}"} for w in WAITS]]}


def saved_text(s: dict[str, Any]) -> str:
    """What the settings now do when a copy doesn't fill."""
    if s["miss"] == "limit":
        does = f"A copy that doesn't fill now becomes a limit order for {wait_text(s['wait'])}."
    elif s["miss"] == "ask":
        does = f"When a copy doesn't fill, I'll ask before leaving a limit order ({wait_text(s['wait'])})."
    else:
        does = "A copy that doesn't fill is skipped."
    return f"Saved. {does} Change it any time with /copy."


# ---- what an alert offers ----


def button(alert_id: str, code: str, usd: float | None = None) -> dict[str, str]:
    return {"text": f"Copy {money(OWN_USD if usd is None else usd)} on {VENUES[code][1]}", "callback_data": f"cv:{alert_id}:{code}"}


def amount_button(alert_id: str) -> dict[str, str]:
    return {"text": "Other amount", "callback_data": f"ca:{alert_id}"}


def offer(con: sqlite3.Connection, alert_id: str, uid: str, code: str, market: str, side: str, price: float, *,
          usd: float | None = None, label: str | None = None, title: str | None = None, trader: str | None = None,
          url: str | None = None) -> None:  # fmt: skip
    """What a Copy button under this alert buys: the market, the price the alert showed and the amount the button
    says, with the names the replies use (the outcome, the market, who bought it, the exchange's page)."""
    con.execute("INSERT OR REPLACE INTO own_offers (alert_id, code, uid, market, side, price, at, usd, label, title, trader, url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, code, uid, market, side, price, time.time(), OWN_USD if usd is None else usd, label, title, trader, url))  # fmt: skip


def amount_of(con: sqlite3.Connection, alert_id: str, uid: str) -> float | None:
    """The amount this alert's Copy buttons show; None when it has none for this account."""
    row = con.execute("SELECT COALESCE(usd, ?) FROM own_offers WHERE alert_id = ? AND uid = ?", (OWN_USD, alert_id, uid)).fetchone()
    return float(row[0]) if row else None


def set_amount(con: sqlite3.Connection, alert_id: str, uid: str, usd: float) -> None:
    """"Other amount": this one trade's amount. CopyError when it can't be changed any more."""
    if not on_for(uid) or amount_of(con, alert_id, uid) is None:
        raise copying.CopyError("This alert can't be copied.")
    if con.execute("SELECT 1 FROM copy_orders WHERE alert_id = ?", (alert_id,)).fetchone():
        raise copying.CopyError("You already tapped Copy on this one.")
    if not valid_usd(usd):
        raise copying.CopyError(AMOUNT_RANGE)
    con.execute("UPDATE own_offers SET usd = ? WHERE alert_id = ? AND uid = ?", (usd, alert_id, uid))


AMOUNT_RANGE = f"Send a number from {MIN_USD:g} to {OWN_DAILY_USD:g}."


def trade_amount_text(usual: float) -> str:
    return f"<b>How much for this trade?</b>\nOnly this one. Your usual stays {money(usual)}. Smallest is {money(MIN_USD)}."


def trade_amount_markup(alert_id: str) -> dict[str, Any]:
    row = [{"text": money(a), "callback_data": f"cu:{alert_id}:{a:g}"} for a in AMOUNTS if valid_usd(a)]
    return {"inline_keyboard": [[*row, {"text": "Type it", "callback_data": f"ct:{alert_id}"}]]}


def with_amount(markup: dict[str, Any], alert_id: str, usd: float) -> dict[str, Any]:
    """An alert's buttons with its Copy buttons saying ``usd``."""
    def new(b: dict[str, Any]) -> dict[str, Any]:
        data = str(b.get("callback_data") or "")
        return button(alert_id, data.rsplit(":", 1)[1], usd) if data.startswith(f"cv:{alert_id}:") and data[-1] in VENUES else b

    return {"inline_keyboard": [[new(b) for b in row] for row in markup.get("inline_keyboard") or []]}


def copied(markup: dict[str, Any], alert_id: str, answer: dict[str, Any]) -> dict[str, Any]:
    """An alert's buttons once it was copied: the Copy buttons and "Other amount" give way to what was bought."""
    mine = (f"cv:{alert_id}:", f"ca:{alert_id}")
    rows = [row for row in markup.get("inline_keyboard") or []
            if not any(str(b.get("callback_data") or "").startswith(mine) for b in row)]  # fmt: skip
    done = {"text": f"Copied · ${float(answer.get('spent') or 0):,.2f} at {cents(answer.get('avg') or 0)}¢", "callback_data": "noop"}
    return {"inline_keyboard": [[done], *rows]}


# ---- a tap on Copy ----


def _spent_today(con: sqlite3.Connection, uid: str, now: float) -> float:
    day0 = datetime.fromtimestamp(now, UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    row = con.execute("SELECT COALESCE(SUM(COALESCE(spent, usd)), 0) FROM copy_orders WHERE uid = ? AND at >= ?"
                      " AND state IN ('placing', 'filled', 'delayed', 'resting')", (uid, day0)).fetchone()  # fmt: skip
    return float(row[0])


def left_today(con: sqlite3.Connection, uid: str, now: float | None = None) -> float:
    """What's left of today's limit, counting what rests in a book."""
    return max(0.0, OWN_DAILY_USD - _spent_today(con, uid, time.time() if now is None else now))


def _names(con: sqlite3.Connection, alert_id: str, code: str) -> dict[str, Any]:
    row = con.execute("SELECT price, label, title, trader, url FROM own_offers WHERE alert_id = ? AND code = ?",
                      (alert_id, code)).fetchone() or (None, None, None, None, None)  # fmt: skip
    return {"alert_price": row[0], "label": row[1] or "it", "title": row[2], "trader": row[3], "url": row[4]}


def claim(con: sqlite3.Connection, alert_id: str, uid: str, code: str, now: float | None = None) -> dict[str, Any]:
    """A tap: the order to send, kept as "placing" first (one copy per alert, whichever venue: never twice).
    CopyError when there's no such offer, it was copied already, or today's limit is reached."""
    now = time.time() if now is None else now
    if not on_for(uid) or code not in VENUES or not has(code):
        raise copying.CopyError("Copying isn't on for your account.")
    o = con.execute("SELECT market, side, price, COALESCE(usd, ?) FROM own_offers WHERE alert_id = ? AND code = ? AND uid = ?",
                    (OWN_USD, alert_id, code, uid)).fetchone()  # fmt: skip
    if not o:
        raise copying.CopyError("This alert can't be copied.")
    done = con.execute("SELECT state FROM copy_orders WHERE alert_id = ?", (alert_id,)).fetchone()
    if done:
        raise copying.CopyError("Already copied." if done[0] == "filled" else "You already tapped Copy on this one.")
    usd = float(o[3])
    if _spent_today(con, uid, now) + usd > OWN_DAILY_USD:
        raise copying.CopyError(f"Not bought: that would pass today's copy limit of ${OWN_DAILY_USD:,.0f}.")
    cap = copying.max_price(float(o[2]))
    con.execute("INSERT INTO copy_orders (alert_id, uid, token, usd, max_price, state, at) VALUES (?, ?, ?, ?, ?, 'placing', ?)",
                (alert_id, uid, f"{VENUES[code][0]}:{o[0]}:{o[1]}", usd, cap, now))  # fmt: skip
    s = settings(con, uid)
    return {"alert_id": alert_id, "uid": uid, "code": code, "venue": VENUES[code][0], "name": VENUES[code][1],
            "market": o[0], "side": o[1], "usd": usd, "max_price": cap, "size": math.floor(usd / cap),
            "miss": s["miss"], "minutes": s["wait"]} | _names(con, alert_id, code)  # fmt: skip


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


def cheapest(order: dict[str, Any], store_dir: Path) -> float | None:
    """The cheapest price anyone is selling this outcome at on its exchange right now (a read: no order). None when
    no one is selling, or the book couldn't be read."""
    try:
        with _lock, _client(order["code"], store_dir) as client:
            best = client.book(order["market"], venue=order["venue"]).outcome(order["side"]).best_ask
    except Exception:  # noqa: BLE001  (a price for the reply: never in the way of saying what happened)
        return None
    return float(best.price) if best is not None else None


# ---- a limit order after a miss ----

_LIMIT_COLS = "alert_id, uid, code, market, side, price, size, usd, minutes, ask, state, order_id, chat, message_id, expires_at"


def _limit(con: sqlite3.Connection, row: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(("alert_id", "uid", "code", "market", "side", "max_price", "size", "usd", "minutes", "ask", "state",
                  "order_id", "chat", "message_id", "expires_at"), row, strict=True))  # fmt: skip
    return d | {"venue": VENUES[d["code"]][0], "name": VENUES[d["code"]][1]} | _names(con, d["alert_id"], d["code"])


def offer_limit(con: sqlite3.Connection, order: dict[str, Any], ask: float | None, chat: str, message_id: int | None) -> None:
    """Nobody was selling at the top price: the same buy is kept, with the cheapest seller the reply shows and
    where that reply is, to rest as a limit order (or buy from that seller) on a tap."""
    con.execute("INSERT OR REPLACE INTO own_limits (alert_id, uid, code, market, side, price, size, usd, minutes, ask, state,"
                " chat, message_id, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'offered', ?, ?, ?)",
                (order["alert_id"], order["uid"], order["code"], order["market"], order["side"], order["max_price"],
                 order["size"], order["usd"], order["minutes"], ask, chat, message_id, time.time()))  # fmt: skip


def limit_of(con: sqlite3.Connection, alert_id: str, uid: str) -> dict[str, Any] | None:
    row = con.execute(f"SELECT {_LIMIT_COLS} FROM own_limits WHERE alert_id = ? AND uid = ?", (alert_id, uid)).fetchone()
    return _limit(con, row) if row else None


def claim_limit(con: sqlite3.Connection, alert_id: str, uid: str, now: float | None = None) -> dict[str, Any]:
    """A limit order is about to rest (a tap on "Leave a limit order", or the setting): kept as "placing" first, so
    a second tap never rests two. CopyError when it wasn't offered, was tapped already, or today's limit is reached."""
    now = time.time() if now is None else now
    if not on_for(uid):
        raise copying.CopyError("Copying isn't on for your account.")
    l = limit_of(con, alert_id, uid)
    if not l or not has(l["code"]):
        raise copying.CopyError("There's no limit order to leave for this alert.")
    if l["state"] != "offered":
        raise copying.CopyError({"resting": "Your limit order is already there.", "done": "This one is over."}.get(
            l["state"], "You already tapped this one."))  # fmt: skip
    if _spent_today(con, uid, now) + l["usd"] > OWN_DAILY_USD:
        raise copying.CopyError(f"Not placed: that would pass today's copy limit of ${OWN_DAILY_USD:,.0f}.")
    l["minutes"] = settings(con, uid)["wait"]
    con.execute("UPDATE own_limits SET state = 'placing', minutes = ? WHERE alert_id = ?", (l["minutes"], alert_id))
    con.execute("UPDATE copy_orders SET state = 'placing', error = NULL, at = ? WHERE alert_id = ?", (now, alert_id))
    return l


def place_limit(order: dict[str, Any], store_dir: Path, now: float | None = None) -> dict[str, Any]:
    """Rest it: a buy of ``size`` contracts at most ``max_price`` that stays in the book for ``minutes`` (the
    exchange ends it then, whatever happens to the engine)."""
    from uselayer import VenueError

    if order["size"] < 1:
        return {"ok": False, "code": "too_small"}
    expires = (time.time() if now is None else now) + order["minutes"] * 60
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
    """The limit order is in the book: kept with where its reply is."""
    con.execute("UPDATE own_limits SET state = 'resting', order_id = ?, chat = ?, message_id = ?, expires_at = ? WHERE alert_id = ?",
                (answer["sdk_id"], chat, message_id, answer["expires_at"], alert_id))  # fmt: skip
    con.execute("UPDATE copy_orders SET state = 'resting', order_id = ? WHERE alert_id = ?", (answer.get("order_id"), alert_id))


def resting(con: sqlite3.Connection, uid: str | None = None) -> list[dict[str, Any]]:
    """The limit orders in the book now (``uid``: that account's), soonest to end first."""
    q, args = f"SELECT {_LIMIT_COLS} FROM own_limits WHERE state = 'resting'", ()
    if uid is not None:
        q, args = q + " AND uid = ?", (uid,)
    return [_limit(con, r) for r in con.execute(q + " ORDER BY expires_at", args).fetchall()]


def settle(con: sqlite3.Connection, alert_id: str, answer: dict[str, Any], *, was: str = "resting") -> bool:
    """A limit order (or what stood in for it) is over: what it bought is kept (nothing: the day's limit gets its
    dollars back). False when someone else (the loop, a cancel tap) settled it first, so it's said once."""
    if con.execute("UPDATE own_limits SET state = 'done' WHERE alert_id = ? AND state = ?", (alert_id, was)).rowcount != 1:
        return False
    if answer.get("code") == "outcome_unknown":  # may have gone through: counted, never re-sent
        con.execute("UPDATE copy_orders SET state = 'delayed', error = 'outcome_unknown' WHERE alert_id = ?", (alert_id,))
    elif float(answer.get("shares") or 0) > 0:
        con.execute("UPDATE copy_orders SET state = 'filled', spent = ?, shares = ?, order_id = ? WHERE alert_id = ?",
                    (answer.get("spent"), answer.get("shares"), answer.get("order_id"), alert_id))  # fmt: skip
    else:
        why = answer.get("message") or answer.get("code") or f"limit order {answer.get('status') or 'ended'}"
        con.execute("UPDATE copy_orders SET state = 'missed', error = ? WHERE alert_id = ?", (str(why)[:300], alert_id))
    return True


def skip(con: sqlite3.Connection, alert_id: str, uid: str) -> dict[str, Any] | None:
    """A tap on "Skip": the offer of a limit order is over. None when there was none to skip."""
    l = limit_of(con, alert_id, uid)
    if not l or con.execute("UPDATE own_limits SET state = 'done' WHERE alert_id = ? AND state = 'offered'", (alert_id,)).rowcount != 1:
        return None
    return l


def claim_now(con: sqlite3.Connection, alert_id: str, uid: str, at_cents: int, now: float | None = None) -> dict[str, Any]:
    """A tap on "Buy now at 46¢": an IOC buy from the cheapest seller the reply showed, at most that price, kept as
    "buying" first (``now_price``, ``now_size``). From an offered limit order, or a resting one (``was``: the caller
    cancels that one first).
    CopyError when the button is stale, it was tapped already, or today's limit is reached."""
    now = time.time() if now is None else now
    if not on_for(uid):
        raise copying.CopyError("Copying isn't on for your account.")
    l = limit_of(con, alert_id, uid)
    if not l or not has(l["code"]) or l["state"] not in ("offered", "resting"):
        raise copying.CopyError("This one is over." if l and l["state"] == "done" else "You already tapped this one.")
    if l["ask"] is None or cents(l["ask"]) != at_cents or not 0 < at_cents < 100:
        raise copying.CopyError("That price is out of date.")
    if l["state"] == "offered" and _spent_today(con, uid, now) + l["usd"] > OWN_DAILY_USD:
        raise copying.CopyError(f"Not bought: that would pass today's copy limit of ${OWN_DAILY_USD:,.0f}.")
    con.execute("UPDATE own_limits SET state = 'buying' WHERE alert_id = ?", (alert_id,))
    con.execute("UPDATE copy_orders SET state = 'placing', error = NULL, at = ? WHERE alert_id = ?", (now, alert_id))
    return l | {"was": l["state"], "now_price": at_cents / 100, "now_size": math.floor(l["usd"] / (at_cents / 100))}


def unclaim_now(con: sqlite3.Connection, alert_id: str, was: str) -> None:
    """"Buy now" couldn't start (the resting order couldn't be cancelled): everything as it was."""
    con.execute("UPDATE own_limits SET state = ? WHERE alert_id = ? AND state = 'buying'", (was, alert_id))
    con.execute("UPDATE copy_orders SET state = ? WHERE alert_id = ?", ("resting" if was == "resting" else "missed", alert_id))


def reoffer(con: sqlite3.Connection, alert_id: str, ask: float | None, message_id: int | None) -> None:
    """"Buy now" bought nothing (that seller was gone): the limit order is offered again, with the cheapest seller now."""
    con.execute("UPDATE own_limits SET state = 'offered', ask = ?, order_id = NULL, expires_at = NULL,"
                " message_id = COALESCE(?, message_id) WHERE alert_id = ? AND state = 'buying'", (ask, message_id, alert_id))  # fmt: skip
    con.execute("UPDATE copy_orders SET state = 'missed', error = 'not_filled' WHERE alert_id = ?", (alert_id,))


# ---- what the bot says ----


def buying_text(order: dict[str, Any]) -> str:
    return (f"Buying {money(order['usd'])} of <b>{_e(order['label'])}</b> on {order['name']} at {cents(order['max_price'])}¢"
            " or less. One second…")  # fmt: skip


def _theirs(order: dict[str, Any], left: float | None) -> str:
    """The second line of a buy: what the trader paid, and what's left of the day."""
    parts = []
    if order.get("trader") and order.get("alert_price"):
        parts.append(f"{_e(order['trader'])} paid {cents(order['alert_price'])}¢.")
    if left is not None:
        parts.append(f"${left:,.2f} left of today's {money(OWN_DAILY_USD)}.")
    return "\n" + " ".join(parts) if parts else ""


def _what(order: dict[str, Any], a: dict[str, Any]) -> str:
    return (f"${float(a.get('spent') or 0):,.2f} of {_e(order['label'])} at {cents(a.get('avg') or order['max_price'])}¢"
            f" on {order['name']}")  # fmt: skip


def bought_text(order: dict[str, Any], answer: dict[str, Any], left: float | None = None) -> str:
    return f"<b>Bought.</b> {_what(order, answer)} ({float(answer['shares']):,.0f} contracts).{_theirs(order, left)}"


def _sellers(order: dict[str, Any], ask: float | None, top: float) -> str:
    """Why nothing was bought, from the cheapest seller there now."""
    if ask is None:
        return f"No one is selling {_e(order['label'])} on {order['name']} right now."
    if cents(ask) > cents(top):
        return f"The cheapest seller on {order['name']} is at {cents(ask)}¢, above your {cents(top)}¢ top price."
    return f"No one sold {_e(order['label'])} at {cents(top)}¢ or less on {order['name']} just then."


def missed_text(order: dict[str, Any], ask: float | None) -> str:
    """A copy that didn't fill, with no limit order left: asked each time, or skipped."""
    return f"<b>Not bought.</b> {_sellers(order, ask, order.get('top') or order['max_price'])} Nothing was spent."


def _order_line(order: dict[str, Any]) -> str:
    return f"<b>{order['size']:,.0f} contracts of {_e(order['label'])} at {cents(order['max_price'])}¢</b>"


def resting_text(order: dict[str, Any], ask: float | None, *, asked: bool = False) -> str:
    """A limit order now in the book: left by the setting right after a miss, or by a tap (``asked``)."""
    top = cents(order["max_price"])
    foot = f"It buys only if a seller comes down to {top}¢. You'll hear here either way."
    if asked:
        return f"<b>Limit order left</b> on {order['name']}: {_order_line(order)}, waiting for {wait_text(order['minutes'])}.\n{foot}"
    return (f"<b>Not bought yet.</b> {_sellers(order, ask, order['max_price'])}\n"
            f"Your settings say to leave a limit order, so I did: {_order_line(order)}, waiting for {wait_text(order['minutes'])}.\n{foot}")  # fmt: skip


def ended_text(order: dict[str, Any], answer: dict[str, Any], left: float | None = None, *, cancelled: bool = False) -> str:
    """How a limit order ended: filled, bought part, or bought nothing (the time ran out, or it was cancelled)."""
    got, size, top = float(answer.get("shares") or 0), float(order["size"]), cents(order["max_price"])
    how = "cancelled" if cancelled else "ended"
    if got >= size - 1e-6:
        return f"<b>Limit order filled.</b> Bought {_what(order, answer)} ({got:,.0f} contracts).{_theirs(order, left)}"
    if got > 0:
        back = max(0.0, float(order["usd"]) - float(answer.get("spent") or 0))
        return (f"<b>Limit order {how}.</b> Bought {_what(order, answer)} ({got:,.0f} of {size:,.0f} contracts)."
                f" The other ${back:,.2f} is back in today's limit.")  # fmt: skip
    back_all = f"Your {money(order['usd'])} is back in today's limit."
    if cancelled:
        return f"<b>Limit order cancelled.</b> Nothing was bought. {back_all}"
    return (f"<b>Limit order ended.</b> No one sold {_e(order['label'])} at {top}¢ in {wait_text(order['minutes'])},"
            f" so nothing was bought. {back_all}")  # fmt: skip


def waiting_text(order: dict[str, Any], ask: float | None, now: float | None = None) -> str:
    """One resting limit order in /orders."""
    left = max(1, round(((order.get("expires_at") or 0) - (time.time() if now is None else now)) / 60))
    head = f"<b>{_e(order['label'])}</b>" + (f" · {_e(order['title'])}" if order.get("title") else "")
    lines = [head, f"{order['size']:,.0f} contracts at {cents(order['max_price'])}¢ on {order['name']} · {left} min left"]
    tail = [f"Copied from {_e(order['trader'])}." if order.get("trader") else "",
            f"Cheapest seller now: {cents(ask)}¢." if ask is not None else ""]  # fmt: skip
    return "\n".join([*lines, " ".join(t for t in tail if t)]).strip()


def view_button(order: dict[str, Any], what: str) -> list[dict[str, str]]:
    """"View position on Polymarket US ↗": the market's page there, when the match has one."""
    return [{"text": f"View {what} on {order['name']} ↗", "url": order["url"]}] if order.get("url") else []


def _now_button(order: dict[str, Any], ask: float | None, top: float) -> list[dict[str, str]]:
    if ask is None or cents(ask) <= cents(top) or math.floor(order["usd"] / ask) < 1:
        return []
    return [{"text": f"Buy now at {cents(ask)}¢", "callback_data": f"cb:{order['alert_id']}:{cents(ask)}"}]


def ask_markup(order: dict[str, Any], ask: float | None) -> dict[str, Any]:
    """Under "Not bought." when the setting is to ask each time."""
    aid, top = order["alert_id"], order.get("top") or order["max_price"]
    rows = [[{"text": f"Leave a limit order at {cents(top)}¢ for {wait_text(order['minutes'])}", "callback_data": f"cl:{aid}"}],
            _now_button(order, ask, top),
            [{"text": "Skip", "callback_data": f"ck:{aid}"}],
            [{"text": "Always leave a limit order", "callback_data": f"cw:{aid}"}]]  # fmt: skip
    return {"inline_keyboard": [r for r in rows if r]}


def resting_markup(order: dict[str, Any], ask: float | None) -> dict[str, Any]:
    """Under a limit order in the book."""
    rows = [[{"text": "Cancel order", "callback_data": f"cx:{order['alert_id']}"}],
            _now_button(order, ask, order["max_price"]), view_button(order, "order")]  # fmt: skip
    return {"inline_keyboard": [r for r in rows if r]}


def result_text(order: dict[str, Any], answer: dict[str, Any] | None, error: str | None = None) -> str:
    """Why an order bought nothing, when it wasn't for want of a seller (plain text)."""
    if error:
        return error
    a, where = answer or {}, order["name"]
    if a.get("ok"):
        return f"Bought ${a['spent']:,.2f} at {round(a['avg'] * 100)}¢ on {where} ({a['shares']:,.0f} contracts)."
    code = a.get("code")
    if code in NOBODY_SELLING:
        return f"Not bought: no one is selling at {round(order['max_price'] * 100)}¢ or less on {where} right now."
    if code in ("insufficient_balance", "insufficient_funds", "not_enough_balance"):
        return f"Not bought: your {where} balance is under {money(order['usd'])}."
    if code == "too_small":
        return "Not bought: the price is too high for one contract at this amount."
    if code == "outcome_unknown":
        return f"Not sure the order went through: {where} didn't answer in time. Check your {where} positions before tapping again."
    if code == "market_closed":
        return f"Not bought: this market isn't trading on {where} right now."
    if code == "auth_failed":
        return f"Not bought: {where} didn't accept your API key. Check it in Railway."
    return f"Not bought: {where} didn't take the order ({a.get('message') or code or 'unknown'}). Nothing was spent."
