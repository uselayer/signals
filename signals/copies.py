"""Your copies: the page's Copies view (``#/copies``, ``/api/me/copies``), for an account that can copy (one-tap copy,
``copying.on_for``, or the owner's own account, ``own_trading.on_for``). Owner, 15 Nov 2026: "if I go to the Signals
web app, can I see like a list of all my copy trades".

Every Copy tap is kept in alerts.db (``copy_orders``), whichever way it went: bought, missed and why, a limit order
waiting, or still being matched. This adds, per tap:

- what it copied: the market, the outcome and the trader (the offer the alert kept: ``own_offers`` or
  ``copy_offers``), and the trader's own buy (``buys``: their price and dollars, matched on the alert's trade);
- the price now, or how its market ended: for the owner's own Kalshi and Polymarket US account, one ``client.pnl``
  read per exchange (``own_trading.marks``: each position's best bid, and its settlement); for a one-tap copy wallet,
  its positions on Polymarket (the current price; a settled market reads 0¢ or 100¢ until it's redeemed).

``view`` turns that into the page's figures. Facts only: the trader's price is context ("They paid"), never a target,
and the view never says copying makes money. Nothing here buys or sells.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
from collections import defaultdict
from typing import Any

from signals import own_trading

MAX_ROWS = 500  # the most recent taps the page lists
POLY = ("polymarket", "Polymarket")  # a one-tap copy: Polymarket International, from the follower's wallet

# Why a tap bought nothing, in one plain sentence (the exchanges' and the order service's codes).
_NOBODY = ("not_filled", "fak_not_filled", "fok_not_filled", "unmatched", "no_liquidity")
_SHORT = ("not_enough_balance", "insufficient_balance", "insufficient_funds", "no_balance")


def reason(error: str | None, max_price: float, usd: float, exchange: str | None = None) -> str:
    """Why a tap bought nothing. A code we know reads as one plain sentence; anything else the exchange said is shown
    as it said it (owner, 15 Nov: "the exchange didn't take the order" alone says nothing)."""
    code = (error or "").strip()
    if code in _NOBODY or code.startswith("Not bought: no one"):
        return f"No one was selling at {round(max_price * 100)}¢ or less."
    if code in _SHORT:
        return f"Your balance was under ${usd:,.2f}."
    if code == "market_not_ready":
        return "The market wasn't taking orders."
    if code == "too_small":
        return "The amount was too small for one contract."
    if " " in code:  # the exchange's own words, not a code
        said = code if len(code) <= 160 else code[:157].rstrip() + "…"
        return f"{exchange or 'The exchange'} said: {said}"
    if code:
        return f"{exchange or 'The exchange'} didn't take the order ({code}). Nothing was spent."
    return "The exchange didn't take the order. Nothing was spent."


_ALERT_HEAD = re.compile(r"<b>(?P<who>[^<]*)</b> bought <b>(?P<label>[^<]*)</b> · (?P<title>[^\n]+)")


def _from_alert(body: str | None) -> dict[str, str]:
    """The trader, outcome and market from an alert's kept message ("<b>Sam</b> bought <b>Yes</b> · Rain in NYC?"),
    for a tap from before its offer kept names. Empty when the message isn't that shape (a grouped alert)."""
    try:
        m = _ALERT_HEAD.search(json.loads(body or "{}").get("text") or "")
    except ValueError:
        return {}
    return {k: html.unescape(v).strip() for k, v in m.groupdict().items()} if m else {}


def _venue_of(token: str) -> tuple[str | None, str, str, str]:
    """(own code or None, venue, market, side) from a copy's token: "kalshi:<market>:<side>" or
    "polymarket_us:<market>:<side>" for the owner's own account (own_trading), else a Polymarket token id."""
    for code, (venue, _) in own_trading.VENUES.items():
        if token.startswith(venue + ":"):
            market, _, side = token[len(venue) + 1 :].rpartition(":")
            return code, venue, market, side
    return None, POLY[0], token, ""


def kept(con: sqlite3.Connection, uid: str) -> list[dict[str, Any]]:
    """This account's taps, newest first, with what each copied. Only ``uid``'s own: never anyone else's."""
    rows = con.execute(
        "SELECT o.alert_id, o.token, o.usd, o.max_price, o.state, o.spent, o.shares, o.error, o.at,"
        " a.trader, a.outcome, a.sent_at, a.trade_at, a.body FROM copy_orders o LEFT JOIN alerts a ON a.id = o.alert_id"
        " WHERE o.uid = ? ORDER BY o.at DESC LIMIT ?", (uid, MAX_ROWS)).fetchall()  # fmt: skip
    out = []
    for (aid, token, usd, cap, state, spent, shares, error, at, wallet, outcome, sent_at, trade_at, body) in rows:
        code, venue, market, side = _venue_of(str(token))
        if code:
            names = con.execute("SELECT label, title, trader, url, price FROM own_offers WHERE alert_id = ? AND code = ?",
                                (aid, code)).fetchone()  # fmt: skip
            exchange = own_trading.VENUES[code][1]
        else:
            names = con.execute("SELECT label, title, trader, url, price FROM copy_offers WHERE alert_id = ?",
                                (aid,)).fetchone()  # fmt: skip
            exchange = POLY[1]
        label, title, trader, url, alert_price = names or (None, None, None, None, None)
        if not (title and label and trader):  # an offer from before it kept names: the alert's own words
            said = _from_alert(body)
            title, label, trader = title or said.get("title"), label or said.get("label"), trader or said.get("who")
        theirs = None
        if wallet and outcome and trade_at is not None:
            theirs = con.execute("SELECT price, usd FROM buys WHERE uid = ? AND outcome = ? AND trader = ?"
                                 " ORDER BY ABS(at - ?) LIMIT 1", (uid, outcome, wallet, trade_at)).fetchone()  # fmt: skip
        limit = con.execute("SELECT expires_at FROM own_limits WHERE alert_id = ?", (aid,)).fetchone() if code else None
        out.append({
            "id": aid, "code": code, "venue": venue, "exchange": exchange, "market": market, "side": side,
            "title": title, "label": label, "trader": wallet, "trader_name": trader, "url": url,
            "usd": float(usd), "max_price": float(cap), "state": state, "spent": spent, "shares": shares, "error": error,
            "tapped_at": at, "sent_at": sent_at, "trade_at": trade_at, "alert_price": alert_price,
            "their_price": theirs[0] if theirs else None, "their_usd": theirs[1] if theirs else None,
            "limit_until": limit[0] if limit else None,
        })  # fmt: skip
    return out


def _end(r: dict[str, Any], own: dict[str, Any], poly: dict[tuple[str, str], float]) -> tuple[str, float | None]:
    """A bought copy's status (open, won, lost or void) and its price per share now or at the end (None: not read)."""
    if r["code"]:
        m = (own.get(r["code"]) or {}).get((r["market"], r["side"]))
        if m and m["settled"] and m.get("outcome"):
            if m["outcome"] == "void":
                return "void", None
            return ("won", 1.0) if m["outcome"] == r["side"] else ("lost", 0.0)
        return "open", (float(m["mark"]) if m and m.get("mark") is not None else None)
    now = poly.get((r["title"] or "", r["label"] or ""))
    return "open", now


def view(rows: list[dict[str, Any]], own: dict[str, Any], poly: dict[tuple[str, str], float]) -> dict[str, Any]:
    """The page's figures: each tap (``rows``) with its status, what it's worth and its profit; the totals (the four
    tiles); and one line per trader copied, beside what the same dollars made at the trader's own price. ``own``:
    own_trading.marks per exchange code (None when that read failed); ``poly``: a one-tap wallet's prices by
    (market, outcome)."""
    shown = []
    for r in rows:
        bought = r["state"] == "filled" and float(r["shares"] or 0) > 0
        status, end, worth, pnl, paid, why = r["state"], None, None, None, None, None
        if bought:
            paid = float(r["spent"]) / float(r["shares"])
            status, end = _end(r, own, poly)
            if status == "void":
                worth = float(r["spent"])  # a voided market pays back what it cost
            elif end is not None:
                worth = float(r["shares"]) * end
            pnl = None if worth is None else worth - float(r["spent"])
        elif r["state"] == "missed":
            why = reason(r["error"], r["max_price"], r["usd"], r["exchange"])
        elif r["state"] == "resting":
            status = "waiting"
        elif r["state"] == "delayed":
            status = "unknown" if r["error"] == "outcome_unknown" else "matching"
        elif r["state"] == "placing":
            status = "buying"
        shown.append(r | {"status": status, "bought": bought, "paid": paid, "now": end, "worth": worth, "pnl": pnl,
                          "why": why})  # fmt: skip

    filled = [r for r in shown if r["bought"]]
    valued = [r for r in filled if r["worth"] is not None]
    gaps = [r["paid"] - float(r["their_price"]) for r in filled if r["their_price"]]
    totals = {
        "put_in": sum(float(r["spent"]) for r in filled),
        "worth": sum(r["worth"] for r in valued),
        "open_worth": sum(r["worth"] for r in valued if r["status"] == "open"),
        "paid_out": sum(r["worth"] for r in valued if r["status"] != "open"),
        "profit": sum(r["pnl"] for r in valued),
        "valued_put_in": sum(float(r["spent"]) for r in valued),
        "unvalued": len(filled) - len(valued),
        "bought": len(filled),
        "missed": sum(1 for r in shown if r["status"] == "missed"),
        "gap": sum(gaps) / len(gaps) if gaps else None,  # per share, in dollars: what being second cost on average
    }

    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in shown:
        by[r["trader"] or r["trader_name"] or "?"].append(r)
    traders = []
    for rs in by.values():
        mine = [r for r in rs if r["bought"]]
        same = [r for r in mine if r["worth"] is not None and r["their_price"] and r["status"] != "void"]
        put = sum(float(r["spent"]) for r in mine)
        traders.append({
            "trader": rs[0]["trader"], "name": next((r["trader_name"] for r in rs if r["trader_name"]), None),
            "bought": len(mine), "open": sum(1 for r in mine if r["status"] == "open"), "put_in": put,
            "profit": sum(r["pnl"] for r in mine if r["pnl"] is not None),
            "valued_put_in": sum(float(r["spent"]) for r in mine if r["pnl"] is not None),
            # the same trades, the same dollars, at the trader's own price: what being second cost
            "same_put_in": sum(float(r["spent"]) for r in same),
            "same_you": sum(r["pnl"] for r in same),
            "same_them": sum(float(r["spent"]) / float(r["their_price"]) * (r["worth"] / float(r["shares"]))
                             - float(r["spent"]) for r in same),
            "missed": sum(1 for r in rs if r["status"] == "missed"),
            "waiting": sum(1 for r in rs if r["status"] == "waiting"),
            "last_at": max(float(r["tapped_at"]) for r in rs),
        })
    traders.sort(key=lambda t: (-t["bought"], -t["last_at"]))
    return {"rows": shown, "totals": totals, "traders": traders}
