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
    # how many of the wallet's busiest markets' facts are read at most to find this type's (60 a batch): more for a
    # type its slugs can't narrow (politics, told apart by Gamma's tags)
    looks_at: int = 60
    # a market read and left out that's close to this type (said in coverage), for a type told apart by its tags
    near: Callable[[dict[str, Any]], bool] | None = None
    # with no outside line: why, in one sentence, for the replay's coverage
    no_outside: str | None = None


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
            "says": words.format(k=k, one="Binance BTCUSDT 1-minute candle's" if binance
                                 else f"{source or 'the named source'}'s")}  # fmt: skip


def btc_long_matches(slug: str | None, facts: dict[str, Any]) -> bool:
    """A BTC price market that isn't an Up/Down window: "Will Bitcoin reach $X by …", "dip to", "above $X on …"."""
    s = slug or ""
    if UPDOWN.match(s) or "up-or-down" in s:
        return False
    q = str(facts.get("question") or s.replace("-", " "))
    return bool(_BTC.search(q) and _PRICE_Q.search(q))


BTC_LONG_PROMPT = """## Long-dated BTC (market_type btc-long; the unit is a market)
A market such as "Will Bitcoin reach $X by the end of the year?" or "Will Bitcoin dip to $Y this month?" runs for \
weeks or months; outcomes are Yes and No, a share pays $1 if its outcome wins, and its price (0 to 1) is \
the market's chance. The unit is a market: one market's life for this wallet, from its first buy to its last sell, \
the resolution, or now. A tile or a market's replay (the market tool) holds every fill the wallet made in that \
market over its whole life (not only the plan's range), its position after each fill, the market's price at the \
stated step (coverage.price_step_s: coarser over long spans; never claim timing finer than the step), and Binance \
BTCUSDT over the same span (candle closes, with each candle's high and low).
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



# ---- politics (elections, who gets appointed, "will X happen by <date>": Polymarket's Politics category) ----

POLITICS_TAGS = {"politics", "elections", "geopolitics", "world", "trump", "us election", "global elections",
                 "midterms", "congress", "senate", "white house", "us politics", "world elections"}  # fmt: skip


def politics_matches(slug: str | None, facts: dict[str, Any]) -> bool:
    """A Politics market as Signals' Politics chip counts it: Gamma's tags, read by the SDK's ``category_of``
    (``facts["category"]``). A slug alone can't say (no facts yet): it isn't ruled out, except an Up/Down window."""
    if UPDOWN.match(slug or ""):
        return False
    if not facts:
        return True
    cat = facts.get("category")
    if cat is None and "tags" in facts:
        from uselayer.whale_scores import category_of

        cat = category_of({"tags": [{"label": t} for t in facts.get("tags") or []]})
    return cat == "Politics"


def politics_near(facts: dict[str, Any]) -> bool:
    """Read and left out, but close: a market with a politics tag whose category came out as something else (a Fed
    decision tagged Trump is Economy)."""
    return facts.get("category") != "Politics" and bool({str(t).lower() for t in facts.get("tags") or []} & POLITICS_TAGS)


# a sentence ends at . ! or ? before a capital, but not after "U.S." or "Mr."
_SENTENCE = re.compile(r"(?<![A-Z]\.[A-Z]\.)(?<!\b(?:Mr|Ms|Dr|St|Jr|Sr)\.)(?<=[.!?])\s+(?=[A-Z\"“])")
_RESOLVES = re.compile(r"\bresolve[sd]?\b", re.IGNORECASE)
_RESULT_RULE = re.compile(r"resolve (?:according )?to the (?:winner|party that wins|individual|next individual|candidate)|"
                          r"resolve to the next individual|\bwins? and accepts\b|\bwins? the\b.*\b(?:election|nomination|race)",
                          re.IGNORECASE)  # fmt: skip
_RESULT_Q = re.compile(r"\b(win|wins|winner|elected|election|nominee|nomination|next|control|balance of power|"
                       r"majority leader|speaker|prime minister|president)\b", re.IGNORECASE)  # fmt: skip
_DATE_RULE = re.compile(r"by the (?:specified|listed) date|between market creation and|through the (?:listed|specified) "
                        r"date|\bby (?:January|February|March|April|May|June|July|August|September|October|November|"
                        r"December) \d", re.IGNORECASE)  # fmt: skip
_DATE_Q = re.compile(r"\b(by|before|through|until|in) (?:the end of )?(?:January|February|March|April|May|June|July|"
                     r"August|September|October|November|December|\d{4})", re.IGNORECASE)  # fmt: skip
# one leg of a "which / where / who" event (one market per country, place or person): one outcome of several
_ONE_OF_EVENT = re.compile(r"^\s*(?:which|where|who)\b", re.IGNORECASE)
_ONE_OF_RULE = re.compile(r"resolve according to the (?:country|location|city|place|venue|person|company)\b", re.IGNORECASE)
_NONE_LEG = re.compile(r"^\s*(?:will\s+)?(?:no|none)\b", re.IGNORECASE)  # "Will no meeting occur by …": a date leg
_SOURCE = re.compile(r"(?:primary )?resolution source (?:for this market )?(?:is|will be) ([^.]{3,160})", re.IGNORECASE)
_NAMED = ("Associated Press", "Fox News", "NBC", "CNN", "official certification", "official results",
          "consensus of credible sources", "consensus of official")  # fmt: skip


def _clip_words(text: str, n: int = 240) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: t.rfind(" ", 0, n)].rstrip(",;:") + "…"


def politics_rule(facts: dict[str, Any]) -> dict[str, Any] | None:
    """What resolves one politics market, read from its own rules (Gamma's ``description``), never assumed for the
    type. ``quote``: the rules' own sentence that resolves it, short. ``kind``: ``result`` (who wins, is appointed
    or controls: an election or an appointment), ``one_of`` (one leg of a "which / where / who" event: Yes if
    this outcome is the one, decided by the deadline; never "by a date"), ``by_date`` (Yes, or No, if something
    happens by the market's date; also an event's "none by <date>" leg), else ``other`` (the parser isn't sure:
    read the quote). A kind is given only when the question and the
    rules agree on it. ``source``: what the rules name to resolve it (the Associated Press, official results…),
    else the market's resolution source, else None. ``says``: one sentence for the page."""
    rules = " ".join(str(facts.get("description") or "").split())
    q = str(facts.get("question") or "")
    sentences = _SENTENCE.split(rules)
    quote = next((x for x in sentences if _RESOLVES.search(x)), sentences[0] if sentences and sentences[0] else "")
    quote = _clip_words(quote)
    item = str(facts.get("group_item") or "")
    # only one outcome of the event can be the one: its rules say so, or a which/where/who event Polymarket runs as
    # negRisk ("Who will Trump insult by …?" isn't: several can be Yes, so each stays a date market)
    one_of = bool(item) and bool(_ONE_OF_RULE.search(rules) or (
        facts.get("neg_risk") and _ONE_OF_EVENT.match(str(facts.get("event_title") or ""))))
    if _RESULT_RULE.search(rules) and _RESULT_Q.search(q):
        kind = "result"
    elif one_of and not (_NONE_LEG.match(q) or _NONE_LEG.match(item)):
        kind = "one_of"
    elif _DATE_RULE.search(rules) and _DATE_Q.search(q):
        kind = "by_date"
    else:
        kind = "other"
    m = _SOURCE.search(rules)
    source = _clip_words(m[1], 120) if m else None
    if not source:
        named = [x for x in _NAMED if x.lower() in rules.lower()]
        source = ", ".join(named) if named else (facts.get("resolution_source") or None)
    deadline = facts.get("end_iso")
    lead = {"result": "The result", "by_date": "Whether it happens by the date in its rules",
            "one_of": f"Whether {item} is the one of its event's outcomes"
                      + (f", decided by {deadline[:10]}" if deadline else ""),
            "other": "Its rules say"}[kind]  # what the page shows after "What resolves it:"
    says = f"{lead}: “{quote}”" if quote else f"{lead}."
    return {"kind": kind, "strike": None, "source": source, "deadline": deadline, "quote": quote or None,
            "says": says}  # fmt: skip


POLITICS_PROMPT = """## Politics (market_type politics; the unit is a market)
A politics market is one Polymarket files under Politics (its own tags, as Signals' Politics chip counts them): an \
election ("Will the Democrats win the Michigan Senate race?"), who is appointed ("Will X be the next Prime \
Minister?"), or whether something happens by a date ("Will the US x Iran ceasefire continue through the end of the month?"). \
Outcomes are Yes and No; a share pays $1 if its outcome wins, and its price (0 to 1) is the market's chance. The \
unit is a market: one market's life for this wallet, from its first buy to its last sell or merge, the resolution, \
or now. A tile or a market's replay (the market tool) holds every fill over the market's whole life, its merges, \
splits and conversions (moves), its position after each, and the market's own price at the stated step \
(coverage.price_step_s: never claim timing finer than the step).
What resolves it: read each market's rule (rule.kind, rule.quote, rule.source) and its rules text, and say which \
applies; never assume one for all. rule.kind result: who wins, is appointed or controls (the source the rules \
name: a news call, official results or certification); by_date: Yes (or No, in its own words) if the thing \
happens by the market's date; one_of: one leg of a "which / where / who" event (one market per country, place or \
person): Yes if this outcome is the one, decided by rule.deadline, never "by a date"; other: the parser wasn't \
sure, so quote the rules instead of naming a kind.
There is no outside line: no news feed, no polls, no vote counts, no results data beyond the market's own result. \
So never say a trade followed news, a poll, a debate or a result coming in, never that it "knew" or "expected" \
anything, and never what the outcome "should" have been. Say a buy came after a move in the market's own price, \
with the move's size and time. Never give your own view of an election or a candidate.
Multi-outcome events: "Who will win…?" is one market per candidate (or per date) under one event (event_slug, \
event_title; group_item is the market's name in the event, often neg_risk). A tile stays one market, but count \
across the event: wallet_markets.events lists each event with two or more of its markets and what it bought of \
each side, including markets past the tiles shown. Holding Yes on one candidate and No on the others, or several \
candidates of the same race, is a pattern worth showing.
Moves: a merge turns pairs of Yes and No into $1 each (a way out before the end, like a sell); a split turns \
dollars into pairs; a conversion (neg_risk) swaps No shares across the event's markets, and Polymarket doesn't \
say which, so that market's profit isn't counted. value.exit says how it left: sold, merged, held to the result, \
or still open; coverage.moves_read false means its moves couldn't be read: then never say it held to the result.
Open markets: profit is valued at today's price (profit_kind "open") and must be called open, never a result. \
Many US races resolved after the midterm election day; a market closed but not yet resolved has no result.
Worth checking: buys after big moves in the market's own price; scaling in over weeks; how many days before the \
end it buys and at what prices; selling or merging before the result vs holding to the end; both sides of one \
market; Yes on one candidate and No on others; many long shots bought cheaply (a low price is a low chance, \
not a bargain); buying the side priced near $1; how long it holds; profit per market and per event."""

POLITICS = MarketType(
    id="politics", label="Politics", unit="market", prompt=POLITICS_PROMPT,
    matches=politics_matches, rule=politics_rule, min_days=7.0, looks_at=180, near=politics_near,
    no_outside=("No outside series for politics markets: the replay is the market's own price, the wallet's fills "
                "and its position. There's no news or polls feed, so no trade here can be tied to news."),
    aliases=("politics-markets", "elections", "election", "us-politics", "geopolitics"),
)  # fmt: skip

# Session 3 (Premier League) adds its entry here.
TYPES: list[MarketType] = [BTC_15M, BTC_LONG, POLITICS]
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
