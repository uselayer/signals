"""The kinds of market a Breakdown can study, one entry each in ``TYPES``.

A market type says what a Breakdown's unit is (a 15-minute ``window``, or a ``market``: one market's life for the
wallet, from its first buy to its last sell, the resolution, or now), which markets belong to it, what resolves
them, which outside line its replay draws, and the "# The markets" section of the agent's instructions. The plan's
scope names one (``scope.market_type``; ``scope.family`` is the 15-minute path's older name for it).

Adding a market type (politics, a sports league) is one entry in ``TYPES``: an id, a label for the header, the unit
(``market`` for anything that isn't a 15-minute window), ``matches`` (does a market belong, from its slug and
Gamma's facts), ``rule`` (what resolves one market, read from its own rules), ``outside`` (which outside series to
draw, or None), the default ``min_days`` (George's timeframe: markets that run at least this long) and the prompt
text. Everything else (tiles, replay, the plan's scope, the header) reads it from here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

UPDOWN = re.compile(r"^[a-z0-9]+-updown-\d+[mh]-\d{9,11}$")


@dataclass(frozen=True)
class MarketType:
    id: str
    label: str  # what the header and the plan's scope say was studied
    unit: str  # "window" (15-minute Up/Down) or "market" (one market's life for the wallet)
    prompt: str  # this type's part of "# The markets" in the agent's instructions
    matches: Callable[[str | None, dict[str, Any]], bool] = lambda slug, facts: False
    rule: Callable[[dict[str, Any]], dict[str, Any] | None] = lambda facts: None
    outside: dict[str, str] | None = None  # the outside line its replay draws: {source, symbol, name}
    min_days: float = 0.0  # by default only markets that run at least this long (from listing to end date)
    aliases: tuple[str, ...] = field(default_factory=tuple)


# ---- BTC 15-minute Up/Down windows (the first Breakdowns; their path is unchanged) ----

BTC_15M_PROMPT = """## BTC 15-minute windows (market_type btc-updown-15m; the unit is a window)
A BTC 15-minute window's slug is btc-updown-15m-<start unix seconds>; it runs 900 seconds and is listed about a \
day ahead, so fills before the start are real (pre_open). "Up" pays $1 a share if Chainlink's BTC/USD at the end \
is above the window's price to beat, "Down" otherwise; the window tool gives price_to_beat, final_price and result: \
never work the result out yourself. A share's price (0 to 1) is the market's chance.
Units: Chainlink and the price to beat are US dollars (the price to beat is a 60-second average). Binance is BTC \
in USDT (Tether), usually about 0.1% away. Never compare a Binance price to the price to beat. To judge whether \
BTC was above the start, use Chainlink where it was recorded (from 10 Nov 2026 05:27 UTC); before that, measure \
Binance against its own value at the window's start and say so in plain words.
Fills: paid_ask true (liquidity "taker") means it paid the ask; false ("maker") means its resting order was \
filled below the ask: not a worse price. null means it couldn't be checked (no recorded book, a recording gap, or \
a sell). Order books exist only where Layer recorded the window (coverage.book). coverage.book_status says why \
there isn't one: "not_processed" means Layer recorded it but hasn't built it yet (say "the order book isn't \
processed yet", never that it wasn't recorded); "not_recorded" means before 2 Nov 17:00 UTC. Chainlink can come \
from Layer's raw recording even when the book isn't processed (coverage.chainlink_source). Many recorded windows have \
seconds without a book (coverage.seconds_without_book, lost): use every window for trades, fills and positions, \
and book facts only where there was a book. A finding that uses the book says how many windows or fills had one \
behind it ("in the 37 windows with a recorded book").
Worth checking: buying both sides (Up + Down under $1 together locks a profit; over $1 a loss); which side ends \
heavier and whether it wins; entries late in the window when the outcome is nearly decided; entries at a fixed time \
or before the open; size that scales with price; selling before the end; maker vs taker share. A window's profit: \
held winning shares pay $1, minus what was paid (the fills' usd), plus what sells brought in."""

BTC_15M = MarketType(
    id="btc-updown-15m", label="BTC Up or Down 15m", unit="window", prompt=BTC_15M_PROMPT,
    matches=lambda slug, facts: bool(slug and slug.startswith("btc-updown-15m-")),
)  # fmt: skip


# ---- long-dated BTC price markets ("Will Bitcoin reach $X by December 31?") ----

_BTC = re.compile(r"\b(bitcoin|btc)\b", re.IGNORECASE)
_PRICE_Q = re.compile(r"\b(reach|dip|hit|above|below|price|all[- ]time high|ath)\b|\$\s?\d", re.IGNORECASE)
_STRIKE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?")


def strike_of(question: str) -> float | None:
    """The price in a market's question ("$100,000", "$87.5k", "$1m"), or None."""
    m = _STRIKE.search(question or "")
    if not m:
        return None
    v = float(m[1].replace(",", ""))
    return v * {"k": 1e3, "m": 1e6}.get((m[2] or "").lower(), 1)


def btc_rule(facts: dict[str, Any]) -> dict[str, Any] | None:
    """What resolves one BTC price market, read from its own rules (Gamma's ``description``), never assumed for the
    type: ``touch_high`` (Yes once any 1-minute candle's High reaches the strike in the market's span), ``touch_low``
    (a Low at or under it), ``close_above``/``close_below`` (one candle's Close at a set time), ``all_time_high``,
    else ``other`` with the rules to quote. ``source``: the price it resolves on, as the rules name it."""
    rules = str(facts.get("description") or "")
    q = str(facts.get("question") or "")
    low = rules.lower()
    binance = "binance" in low and "btc/usdt" in low
    source = "Binance BTCUSDT 1-minute candles" if binance else None
    if not source:
        for name in ("Coinbase", "Chainlink", "Kraken", "CoinGecko", "CoinMarketCap"):
            if name.lower() in low:
                source = name
                break
    strike = strike_of(q)
    if "all time high" in low or "all-time high" in low or "all time high" in q.lower():
        kind = "all_time_high"
    elif re.search(r'"?high"? price (?:that is )?(?:equal to or greater|greater than or equal|higher than)', low) or \
            re.search(r"\bhigh\b.*equal to or greater", low):  # fmt: skip
        kind = "touch_high"
    elif re.search(r"\blow\b.*(?:equal to or (?:less|lower)|less than or equal|lower than)", low):
        kind = "touch_low"
    elif re.search(r'"?close"? price (?:higher|greater|above)', low):
        kind = "close_above"
    elif re.search(r'"?close"? price (?:lower|less|below)', low):
        kind = "close_below"
    else:
        kind = "other"
    words = {
        "touch_high": "Yes as soon as any {one} High reaches {k} before the end; No if none does",
        "touch_low": "Yes as soon as any {one} Low falls to {k} before the end; No if none does",
        "close_above": "Yes if one set {one} Close (the time is in the rules) is above {k}: one moment, not any time",
        "close_below": "Yes if one set {one} Close (the time is in the rules) is below {k}: one moment, not any time",
        "all_time_high": "Yes if any {one} High beats every earlier High before the end",
        "other": "Read the rules: this market's resolution doesn't match the usual BTC price wording",
    }[kind]
    k = f"${strike:,.0f}" if strike else "the price in the question"
    return {"kind": kind, "strike": strike, "source": source, "binance": binance,
            "says": words.format(one="Binance BTCUSDT 1-minute candle's" if binance else f"{source or 'the named source'}'s", k=k)}  # fmt: skip


def btc_long_matches(slug: str | None, facts: dict[str, Any]) -> bool:
    """A BTC price market that isn't an Up/Down window: "Will Bitcoin reach $X by …", "dip to", "above $X on …"."""
    s = slug or ""
    if UPDOWN.match(s) or "up-or-down" in s:
        return False
    q = str(facts.get("question") or s.replace("-", " "))
    return bool(_BTC.search(q) and _PRICE_Q.search(q))


BTC_LONG_PROMPT = """## Long-dated BTC (market_type btc-long; the unit is a market)
A market such as "Will Bitcoin reach $X by the end of the year?" or "Will Bitcoin dip to $Y this month?" runs for weeks or months; outcomes are Yes and No, a share pays $1 if its outcome wins, and its price (0 to 1) is \
the market's chance. The unit is a market: one market's life for this wallet, from its first buy to its last sell, \
the resolution, or now. A tile or a market's replay (the market tool) holds every fill the wallet made in that \
market over its whole life (not only the plan's range), its position after each fill, the market's price at the \
stated step (coverage.price_step_s: coarser over long spans; never claim timing finer than the step), and Binance BTCUSDT over the same span (candle closes, with each candle's high and low).
What resolves it: read each market's rule (market tool: rule, rules) and say which applies, never assume one for \
all: rule.kind touch_high means Yes as soon as any Binance BTCUSDT 1-minute candle's High reaches the strike before \
the end (any moment counts); touch_low the same with a Low at or under it; close_above/close_below means one set \
candle's Close (the rules give the time), one moment only. To judge how close BTC came, compare the strike with \
Binance BTCUSDT's highs (touch_high) or lows (touch_low) over the holding period: a candle's high and low cover \
every minute inside it, so the highest high is exact at any step. Never compare these markets with Chainlink \
BTC/USD, a price to beat or 15-minute windows: they don't settle on them.
Several strikes of one event (the same event_slug, e.g. "What price will Bitcoin hit in November?") are separate \
markets; holding several at once (e.g. Yes on one strike, No on another) is a pattern worth showing.
Open markets: profit is valued at today's price (profit_kind "open") and must be called open ("valued at today's \
price"), never a result. A position the wallet sold out of before the end has a realized profit (profit_kind \
"closed"); a resolved one pays $1 a winning share (profit_kind "resolved").
Worth checking: buys after a BTC move or a jump in the market's own price (there's no news feed: say a buy came \
after a move, never that it was news); scaling in over days; how many days before the end it buys and at what \
prices; selling before the resolution vs holding to the end; holding several strikes or both sides; buying the \
side priced near $1 (a high price is a high chance, not a bargain); how long it holds; profit per market."""

BTC_LONG = MarketType(
    id="btc-long", label="Long-dated BTC", unit="market", prompt=BTC_LONG_PROMPT,
    matches=btc_long_matches, rule=btc_rule, min_days=7.0,
    outside={"source": "binance", "symbol": "BTC", "name": "Binance BTCUSDT"},
    aliases=("long-dated-btc", "btc-long-dated", "long-dated-crypto", "crypto-long"),
)  # fmt: skip

# Sessions 2 (politics) and 3 (Premier League) add their entry here.
TYPES: list[MarketType] = [BTC_15M, BTC_LONG]
DEFAULT = BTC_15M


def by_id(x: str | None) -> MarketType | None:
    k = str(x or "").strip().lower().rstrip("-")
    return next((t for t in TYPES if k == t.id or k in t.aliases), None)


def of_scope(scope: dict[str, Any] | None) -> MarketType:
    """The market type a plan's scope studies: ``market_type``, else ``family`` (the 15-minute path's name), else
    BTC 15-minute windows (every plan before market types)."""
    s = scope or {}
    return by_id(s.get("market_type")) or by_id(s.get("family")) or DEFAULT


def of_market(slug: str | None, facts: dict[str, Any]) -> MarketType | None:
    """The first market type a market belongs to, or None (a market no type knows: drawn with no outside line)."""
    return next((t for t in TYPES if t.unit == "market" and t.matches(slug, facts)), None)


def is_window(slug: str | None) -> bool:
    """A crypto Up/Down window (today's replay), as against any other market (a market replay)."""
    return bool(UPDOWN.match(slug or ""))


def described() -> list[dict[str, Any]]:
    """The types as the plan tool lists them."""
    return [{"id": t.id, "label": t.label, "unit": t.unit, "min_days": t.min_days} for t in TYPES]


def sections() -> str:
    """"# The markets" for the agent's instructions: every type's section, in order."""
    return "\n\n".join(t.prompt for t in TYPES)
