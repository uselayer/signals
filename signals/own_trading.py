"""The owner's own one-tap copy on Kalshi and Polymarket US (owner, 11 Nov 2026: "I should be able to copy trade on
poly us or kalshi").

Only the owner's account (SIGNALS_OWN_UID), with the owner's own exchange keys: Signals' software trading its owner's
own account, which both exchanges allow (Kalshi's Developer Agreement: the API is for "a member's own trading").
It never takes anyone else's exchange keys: both exchanges forbid that (AGENTS.md "Copying a trade").

Under a buy alert whose outcome has a verified match on Kalshi or Polymarket US (us_match), one button: "Copy $25"
(owner, 13 Nov 2026: "copy on poly and copy on kalshi, i dont like those 2 buttons"). A tap buys on whichever of
the two is cheaper right then (``choose``: each one's cheapest seller, leaving out one whose balance can't cover the
amount), and the reply names it. The buy is an IOC through the uselayer SDK (live): that many dollars of contracts at
most COLLAR above the price the alert showed; what doesn't fill at once is cancelled. Never a sell, never without a
tap, at most OWN_DAILY_USD a UTC day. The engine runs in the US, where both exchanges are open.

Nothing here is a command to remember (owner, 12 Nov 2026: "hidden commands dont fit"): every choice is a button
where it's needed. The amount (owner, 11 Nov: "sometimes i wanna use $5 not just $25"): "Change amount" under the
alert, then "Just this trade" or "Every trade". Each alert keeps the amount its button shows, so a tap never buys a
size the button didn't say. "Copy settings" sits under every result.

When nobody is selling at the top price (owner, 11 Nov 2026: "then do a limit order"), the reply carries "Leave a
limit order at 45¢": the same buy (same size, same top price) resting in that exchange's book for LIMIT_MIN minutes;
the exchange itself ends it then. The first time, the bot asks whether to do that every time; "Cancel order" ends
one sooner. ``check`` (the engine's loop) reads a resting order back until it's over and the bot says what was
bought, if anything. Still one order per alert, still counted in the day's limit while it rests.
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
OWN_USD = float(os.environ.get("SIGNALS_OWN_USD", "25"))  # the usual amount until "Every trade" changes it
OWN_DAILY_USD = float(os.environ.get("SIGNALS_OWN_DAILY_USD", "250"))
LIMIT_MIN = float(os.environ.get("SIGNALS_OWN_LIMIT_MIN", "30"))  # how long a limit order rests
MIN_USD = 1.0  # one contract never costs more than 99¢
AMOUNTS = (5.0, 10.0, 50.0)  # the amounts offered as buttons; "Type my own" takes any other
VENUES = {"k": ("kalshi", "Kalshi"), "u": ("polymarket_us", "Polymarket US")}
NOBODY_SELLING = ("not_filled", "no_liquidity")  # the misses a limit order answers
TAPS = ("cv", "ca", "cu", "ct", "cj", "ce", "cl", "cx", "os", "oa", "om", "oy", "noop")  # this module's buttons
INTRO = "New: tap Copy to buy this yourself. Tap Change amount first for a different amount."  # once, on the first alert
_lock = threading.Lock()  # one SDK client at a time on the own-trading store (a tap, a cancel, the loop's check)

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_offers (alert_id TEXT NOT NULL, code TEXT NOT NULL, uid TEXT NOT NULL,
  market TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, at REAL NOT NULL, usd REAL, label TEXT, title TEXT,
  trader TEXT, url TEXT, PRIMARY KEY (alert_id, code));
CREATE TABLE IF NOT EXISTS own_limits (alert_id TEXT PRIMARY KEY, uid TEXT NOT NULL, code TEXT NOT NULL,
  market TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, size REAL NOT NULL, usd REAL NOT NULL,
  minutes REAL NOT NULL, state TEXT NOT NULL, order_id TEXT, chat TEXT, message_id INTEGER,
  expires_at REAL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS own_settings (uid TEXT PRIMARY KEY, usd REAL, miss TEXT, intro INTEGER NOT NULL DEFAULT 0);
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


# ---- settings ("Copy settings" under every result) ----


def settings(con: sqlite3.Connection, uid: str) -> dict[str, Any]:
    """The account's copy settings: the usual amount; what a copy that doesn't fill does (``miss``: "ask", "limit",
    or None while they've never been asked: it asks, as "ask" does); whether the first alert's line was shown."""
    row = con.execute("SELECT usd, miss, intro FROM own_settings WHERE uid = ?", (uid,)).fetchone() or (None, None, 0)
    return {"usd": float(row[0]) if row[0] and valid_usd(float(row[0])) else min(OWN_USD, OWN_DAILY_USD),
            "miss": row[1] if row[1] in ("ask", "limit") else None, "intro": bool(row[2])}  # fmt: skip


def save(con: sqlite3.Connection, uid: str, **changed: Any) -> dict[str, Any]:
    """Change some settings (``usd``, ``miss``, ``intro``); all of them as they now are."""
    s = settings(con, uid) | changed
    con.execute("INSERT OR REPLACE INTO own_settings (uid, usd, miss, intro) VALUES (?, ?, ?, ?)",
                (uid, s["usd"], s["miss"], int(bool(s["intro"]))))  # fmt: skip
    return s


def valid_usd(usd: float) -> bool:
    """An amount a copy can be: from MIN_USD to the day's limit."""
    return MIN_USD <= usd <= OWN_DAILY_USD


AMOUNT_RANGE = f"Send a number from {MIN_USD:g} to {OWN_DAILY_USD:g}."
SETTINGS_BUTTON = {"text": "Copy settings", "callback_data": "os:o"}


def settings_text(s: dict[str, Any]) -> str:
    return "\n".join(["<b>Your copy settings</b>", f"Amount: {money(s['usd'])} a trade",
                      f"If a copy doesn't fill: {'leave a limit order' if s['miss'] == 'limit' else 'ask me'}",
                      f"Top price: {cents(copying.COLLAR)}¢ above the alert's price. Most in a day: {money(OWN_DAILY_USD)}."])  # fmt: skip


def settings_markup() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "Amount", "callback_data": "os:a"},
                                 {"text": "If it doesn't fill", "callback_data": "os:m"}]]}  # fmt: skip


def _ticked(text: str, on: bool) -> str:
    return f"✓ {text}" if on else text


def usual_text(s: dict[str, Any]) -> str:
    return f"<b>Your usual amount?</b>\nNow {money(s['usd'])}. Smallest is {money(MIN_USD)}."


def usual_markup(s: dict[str, Any]) -> dict[str, Any]:
    row = [{"text": _ticked(money(a), a == s["usd"]), "callback_data": f"oa:{a:g}"} for a in AMOUNTS if valid_usd(a)]
    return {"inline_keyboard": [[*row, {"text": "Type my own", "callback_data": "oa:t"}]]}


def usual_saved(usd: float) -> str:
    return f"{money(usd)} from now on. New alerts' Copy button will say {money(usd)}."


MISS_TEXT = (f"<b>If a copy doesn't fill?</b>\nA limit order waits on the exchange at your top price for {wait_text(LIMIT_MIN)}."
             " It buys only if a seller comes down to it, and never pays more.")  # fmt: skip
ALWAYS_TEXT = "<b>Do this every time a copy doesn't fill?</b>\nYou can change it later in Copy settings."
ALWAYS_MARKUP = {"inline_keyboard": [[{"text": "Yes, always", "callback_data": "oy:1"}, {"text": "No, ask me", "callback_data": "oy:0"}]]}


def miss_markup(s: dict[str, Any]) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": _ticked("Ask me", s["miss"] != "limit"), "callback_data": "om:a"},
                                 {"text": _ticked("Leave a limit order", s["miss"] == "limit"), "callback_data": "om:l"}]]}  # fmt: skip


def miss_saved(s: dict[str, Any]) -> str:
    if s["miss"] == "limit":
        return f"Saved. A copy that doesn't fill now becomes a limit order for {wait_text(LIMIT_MIN)}."
    return "Saved. When a copy doesn't fill, I'll ask before leaving a limit order."


# ---- what an alert offers ----


def button(alert_id: str, usd: float | None = None) -> dict[str, str]:
    """The one Copy button: which exchange is decided on the tap (``choose``)."""
    return {"text": f"Copy {money(OWN_USD if usd is None else usd)}", "callback_data": f"cv:{alert_id}"}


def amount_button(alert_id: str) -> dict[str, str]:
    return {"text": "Change amount", "callback_data": f"ca:{alert_id}"}


def offer(con: sqlite3.Connection, alert_id: str, uid: str, code: str, market: str, side: str, price: float, *,
          usd: float | None = None, label: str | None = None, title: str | None = None, trader: str | None = None,
          url: str | None = None) -> None:  # fmt: skip
    """One exchange the alert's Copy button may buy on: the market there, the price the alert showed and the amount
    the button says, with the names the replies use (the outcome, the market, who bought it, the exchange's page)."""
    con.execute("INSERT OR REPLACE INTO own_offers (alert_id, code, uid, market, side, price, at, usd, label, title, trader, url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (alert_id, code, uid, market, side, price, time.time(), OWN_USD if usd is None else usd, label, title, trader, url))  # fmt: skip


def amount_of(con: sqlite3.Connection, alert_id: str, uid: str) -> float | None:
    """The amount this alert's Copy button shows; None when it has none for this account."""
    row = con.execute("SELECT COALESCE(usd, ?) FROM own_offers WHERE alert_id = ? AND uid = ?", (OWN_USD, alert_id, uid)).fetchone()
    return float(row[0]) if row else None


def set_amount(con: sqlite3.Connection, alert_id: str, uid: str, usd: float) -> None:
    """"Change amount": this one trade's amount. CopyError when it can't be changed any more."""
    if not on_for(uid) or amount_of(con, alert_id, uid) is None:
        raise copying.CopyError("This alert can't be copied.")
    if con.execute("SELECT 1 FROM copy_orders WHERE alert_id = ?", (alert_id,)).fetchone():
        raise copying.CopyError("You already tapped Copy on this one.")
    if not valid_usd(usd):
        raise copying.CopyError(AMOUNT_RANGE)
    con.execute("UPDATE own_offers SET usd = ? WHERE alert_id = ? AND uid = ?", (usd, alert_id, uid))


def amount_text(now_usd: float) -> str:
    return f"<b>How much?</b>\nNow {money(now_usd)}. Smallest is {money(MIN_USD)}."


def amount_markup(alert_id: str) -> dict[str, Any]:
    row = [{"text": money(a), "callback_data": f"cu:{alert_id}:{a:g}"} for a in AMOUNTS if valid_usd(a)]
    return {"inline_keyboard": [[*row, {"text": "Type my own", "callback_data": f"ct:{alert_id}"}]]}


def which_text(usd: float) -> str:
    return f"<b>{money(usd)} for which trades?</b>"


def which_markup(alert_id: str, usd: float) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "Just this trade", "callback_data": f"cj:{alert_id}:{usd:g}"},
                                 {"text": "Every trade", "callback_data": f"ce:{alert_id}:{usd:g}"}]]}  # fmt: skip


def _is_copy(b: dict[str, Any], alert_id: str) -> bool:
    data = str(b.get("callback_data") or "")
    return data == f"cv:{alert_id}" or data.startswith(f"cv:{alert_id}:")  # the second: an alert from when each exchange had a button


def with_amount(markup: dict[str, Any], alert_id: str, usd: float) -> dict[str, Any]:
    """An alert's buttons with its Copy button saying ``usd``."""
    def new(b: dict[str, Any]) -> dict[str, Any]:
        return b | {"text": str(b["text"]).replace(str(b["text"]).split()[1], money(usd), 1)} if _is_copy(b, alert_id) else b

    return {"inline_keyboard": [[new(b) for b in row] for row in markup.get("inline_keyboard") or []]}


def copied(markup: dict[str, Any], alert_id: str, answer: dict[str, Any]) -> dict[str, Any]:
    """An alert's buttons once it was copied: Copy and "Change amount" give way to what was bought."""
    def mine(b: dict[str, Any]) -> bool:
        return _is_copy(b, alert_id) or b.get("callback_data") == f"ca:{alert_id}"

    rows = [[b for b in row if not mine(b)] for row in markup.get("inline_keyboard") or []]
    done = {"text": f"Copied · ${float(answer.get('spent') or 0):,.2f} at {cents(answer.get('avg') or 0)}¢", "callback_data": "noop"}
    return {"inline_keyboard": [[done], *(r for r in rows if r)]}


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


def _venue(code: str, market: str, side: str, url: str | None) -> dict[str, Any]:
    return {"code": code, "venue": VENUES[code][0], "name": VENUES[code][1], "market": market, "side": side, "url": url}


def claim(con: sqlite3.Connection, alert_id: str, uid: str, code: str | None = None, now: float | None = None) -> dict[str, Any]:
    """A tap: the order to send, kept as "placing" first (one copy per alert, whichever exchange: never twice).
    ``choices``: the exchanges it may go to (``code``: only that one, a button from when each had its own); the
    order starts as the first and ``choose`` settles it. CopyError when there's no such offer, it was copied
    already, or today's limit is reached."""
    now = time.time() if now is None else now
    if not on_for(uid) or (code is not None and code not in VENUES):
        raise copying.CopyError("Copying isn't on for your account.")
    rows = con.execute("SELECT code, market, side, price, COALESCE(usd, ?), url FROM own_offers WHERE alert_id = ? AND uid = ?"
                       " ORDER BY code DESC", (OWN_USD, alert_id, uid)).fetchall()  # fmt: skip
    rows = [r for r in rows if has(r[0]) and code in (None, r[0])]
    if not rows:
        raise copying.CopyError("This alert can't be copied.")
    done = con.execute("SELECT state FROM copy_orders WHERE alert_id = ?", (alert_id,)).fetchone()
    if done:
        raise copying.CopyError("Already copied." if done[0] == "filled" else "You already tapped Copy on this one.")
    usd = float(rows[0][4])
    if _spent_today(con, uid, now) + usd > OWN_DAILY_USD:
        raise copying.CopyError(f"Not bought: that would pass today's copy limit of ${OWN_DAILY_USD:,.0f}.")
    cap = copying.max_price(float(rows[0][3]))
    choices = [_venue(r[0], r[1], r[2], r[5]) for r in rows]
    con.execute("INSERT INTO copy_orders (alert_id, uid, token, usd, max_price, state, at) VALUES (?, ?, ?, ?, ?, 'placing', ?)",
                (alert_id, uid, _token(choices[0]), usd, cap, now))  # fmt: skip
    return {"alert_id": alert_id, "uid": uid, "usd": usd, "max_price": cap, "size": math.floor(usd / cap),
            "miss": settings(con, uid)["miss"], "minutes": LIMIT_MIN, "choices": choices, "others": [],
            } | _names(con, alert_id, choices[0]["code"]) | choices[0]  # fmt: skip


def _token(v: dict[str, Any]) -> str:
    return f"{v['venue']}:{v['market']}:{v['side']}"


def set_venue(con: sqlite3.Connection, order: dict[str, Any]) -> None:
    """The exchange ``choose`` settled on, kept with the order."""
    con.execute("UPDATE copy_orders SET token = ? WHERE alert_id = ?", (_token(order), order["alert_id"]))


def _client(code: str, store_dir: Path) -> Any:
    """The SDK, live, with the owner's key for this one venue."""
    from uselayer import Client
    from uselayer.venues.kalshi import Kalshi
    from uselayer.venues.polymarket_us_live import PolymarketUS

    key_id, secret = _keys(code)
    venue = {"kalshi": Kalshi(key_id=key_id, private_key_pem=secret)} if code == "k" else {
        "polymarket_us": PolymarketUS(key_id=key_id, secret_key=secret)}  # fmt: skip
    return Client(mode="live", store=store_dir / "own-trading", **venue)  # type: ignore[arg-type]


def cheapest(order: dict[str, Any], store_dir: Path) -> float | None:
    """The cheapest price anyone is selling this outcome at on its exchange right now (a read: no order). None when
    no one is selling, or the book couldn't be read."""
    try:
        with _lock, _client(order["code"], store_dir) as client:
            best = client.book(order["market"], venue=order["venue"]).outcome(order["side"]).best_ask
    except Exception:  # noqa: BLE001  (a price for the reply: never in the way of saying what happened)
        return None
    return float(best.price) if best is not None else None


def balance(code: str, store_dir: Path) -> float | None:
    """The cash in the owner's account on this exchange (a read). None when it couldn't be read."""
    try:
        with _lock, _client(code, store_dir) as client:
            return float(client.balances()[VENUES[code][0]].cash)
    except Exception:  # noqa: BLE001  (not known: the exchange itself says so if it's short)
        return None


def choose(order: dict[str, Any], store_dir: Path) -> dict[str, Any]:
    """Which exchange a tap buys on, when the outcome is on both: the one with the cheaper seller right now, leaving
    out one whose balance can't cover the amount. With one exchange there's nothing to read: it's that one."""
    if len(order["choices"]) < 2:
        return order
    seen = []
    for c in order["choices"]:
        cash = balance(c["code"], store_dir)
        short = cash is not None and cash < order["usd"]
        seen.append(c | {"short": short, "ask": None if short else cheapest(order | c, store_dir)})
    return pick(order, seen)


def pick(order: dict[str, Any], seen: list[dict[str, Any]]) -> dict[str, Any]:
    """``choose``'s decision from what was read (each choice with ``ask`` and ``short``): the cheapest seller among
    the exchanges with the money; ``others``: the rest, for the reply. ``none``: no balance covers it."""
    able = [s for s in seen if not s["short"]]
    if not able:
        return order | {"none": True, "others": seen}
    best = min(able, key=lambda s: (s["ask"] is None, s["ask"] or 0.0))
    return order | best | {"others": [s for s in seen if s is not best]}


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

_LIMIT_COLS = "alert_id, uid, code, market, side, price, size, usd, minutes, state, order_id, chat, message_id, expires_at"


def _limit(con: sqlite3.Connection, row: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(("alert_id", "uid", "code", "market", "side", "max_price", "size", "usd", "minutes", "state",
                  "order_id", "chat", "message_id", "expires_at"), row, strict=True))  # fmt: skip
    return d | {"venue": VENUES[d["code"]][0], "name": VENUES[d["code"]][1]} | _names(con, d["alert_id"], d["code"])


def offer_limit(con: sqlite3.Connection, order: dict[str, Any], chat: str, message_id: int | None) -> None:
    """Nobody was selling at the top price: the same buy is kept, with where its reply is, to rest as a limit
    order on a tap (or at once, by the setting)."""
    con.execute("INSERT OR REPLACE INTO own_limits (alert_id, uid, code, market, side, price, size, usd, minutes, state,"
                " chat, message_id, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'offered', ?, ?, ?)",
                (order["alert_id"], order["uid"], order["code"], order["market"], order["side"], order["max_price"],
                 order["size"], order["usd"], order["minutes"], chat, message_id, time.time()))  # fmt: skip


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
    con.execute("UPDATE own_limits SET state = 'placing' WHERE alert_id = ?", (alert_id,))
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
    """A limit order is over: what it bought is kept (nothing: the day's limit gets its dollars back). False when
    someone else (the loop, a cancel tap) settled it first, so it's said once."""
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


# ---- what the bot says ----


def buying_text(order: dict[str, Any]) -> str:
    what, top = f"Buying {money(order['usd'])} of <b>{_e(order['label'])}</b>", cents(order["max_price"])
    if len(order["choices"]) > 1:
        names = " and ".join(c["name"] for c in order["choices"])
        return f"{what} at {top}¢ or less, on whichever of {names} is cheaper. One second…"
    return f"{what} on {order['name']} at {top}¢ or less. One second…"


def _theirs(order: dict[str, Any], left: float | None) -> str:
    """The second line of a buy: the other exchange's price, what the trader paid, and what's left of the day."""
    parts = []
    for o in order.get("others") or []:
        if o.get("short"):
            parts.append(f"{o['name']} left out: your balance there is under {money(order['usd'])}.")
        elif o.get("ask") is not None:
            parts.append(f"{o['name']} was at {cents(o['ask'])}¢.")
    if order.get("trader") and order.get("alert_price"):
        parts.append(f"{_e(order['trader'])} paid {cents(order['alert_price'])}¢.")
    if left is not None:
        parts.append(f"${left:,.2f} left of today's {money(OWN_DAILY_USD)}.")
    return "\n" + " ".join(parts) if parts else ""


def _what(order: dict[str, Any], a: dict[str, Any]) -> str:
    return f"${float(a.get('spent') or 0):,.2f} of {_e(order['label'])} at {cents(a.get('avg') or order['max_price'])}¢"


def bought_text(order: dict[str, Any], answer: dict[str, Any], left: float | None = None) -> str:
    return (f"<b>Bought on {order['name']}.</b> {_what(order, answer)} ({float(answer['shares']):,.0f} contracts)."
            f"{_theirs(order, left)}")  # fmt: skip


def missed_text(order: dict[str, Any], ask: float | None) -> str:
    """A copy that didn't fill: why, from the cheapest seller there now."""
    top = cents(order["max_price"])
    if ask is None:
        why = f"No one is selling {_e(order['label'])} on {order['name']} right now."
    elif cents(ask) > top:
        why = f"The cheapest seller is at {cents(ask)}¢, on {order['name']}, above your {top}¢ top price."
    else:
        why = f"No one sold {_e(order['label'])} at {top}¢ or less on {order['name']} just then."
    return f"<b>Not bought.</b> {why} Nothing was spent."


def missed_markup(order: dict[str, Any]) -> dict[str, Any]:
    """Under "Not bought.": the limit order, and the settings."""
    return {"inline_keyboard": [[{"text": f"Leave a limit order at {cents(order['max_price'])}¢", "callback_data": f"cl:{order['alert_id']}"}],
                                [SETTINGS_BUTTON]]}  # fmt: skip


def resting_text(order: dict[str, Any], *, by_setting: bool = False) -> str:
    """A limit order now in the book: left by a tap, or (``by_setting``) at once after a miss."""
    top = cents(order["max_price"])
    line = (f"{order['size']:,.0f} contracts of {_e(order['label'])} at {top}¢ on {order['name']},"
            f" waiting {wait_text(order['minutes'])}.")  # fmt: skip
    foot = f"It buys only if a seller comes down to {top}¢. I'll message you when it fills or ends."
    if by_setting:
        return f"<b>Not bought yet</b>: no one is selling at {top}¢ or less. <b>Limit order placed</b>, as you set: {line}\n{foot}"
    return f"<b>Limit order placed.</b> {line}\n{foot}"


def resting_markup(order: dict[str, Any]) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "Cancel order", "callback_data": f"cx:{order['alert_id']}"}]]}


def ended_text(order: dict[str, Any], answer: dict[str, Any], left: float | None = None, *, cancelled: bool = False) -> str:
    """How a limit order ended: filled, bought part, or bought nothing (the time ran out, or it was cancelled)."""
    got, size, top = float(answer.get("shares") or 0), float(order["size"]), cents(order["max_price"])
    how = "cancelled" if cancelled else "ended"
    on = f" on {order['name']}"
    if got >= size - 1e-6:
        return f"<b>Limit order filled.</b> Bought {_what(order, answer)}{on} ({got:,.0f} contracts).{_theirs(order, left)}"
    if got > 0:
        back = max(0.0, float(order["usd"]) - float(answer.get("spent") or 0))
        return (f"<b>Limit order {how}.</b> Bought {_what(order, answer)}{on} ({got:,.0f} of {size:,.0f} contracts)."
                f" The other ${back:,.2f} is back in today's limit.")  # fmt: skip
    back_all = f"Your {money(order['usd'])} is back in today's limit."
    if cancelled:
        return f"<b>Limit order cancelled.</b> Nothing was bought. {back_all}"
    return (f"<b>Limit order ended.</b> No one sold {_e(order['label'])} at {top}¢ in {wait_text(order['minutes'])},"
            f" so nothing was bought. {back_all}")  # fmt: skip


def result_markup(order: dict[str, Any]) -> dict[str, Any]:
    """Under what was bought: the market's page on that exchange (when the match has one), and the settings."""
    view = [{"text": "View position ↗", "url": order["url"]}] if order.get("url") else []
    return {"inline_keyboard": [[*view, SETTINGS_BUTTON]]}


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
    if code == "no_balance":
        names = " and ".join(o["name"] for o in order.get("others") or []) or where
        return f"Not bought: your {names} balance{'s are' if ' and ' in names else ' is'} under {money(order['usd'])}."
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
