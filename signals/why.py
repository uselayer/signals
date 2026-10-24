"""One sentence of context under a change on a trader's watch page ("Explained"), written by a model from facts the
engine picks. The model only words it: which facts it gets, and every figure in them, are worked out here (``facts``),
and a sentence with a number, or a comparison, that its facts don't have, or words we never say, is dropped
(``checked``), so the page shows nothing rather than something wrong. Off unless OPENROUTER_API_KEY is set.

Tested 23 Oct on 36 real moves of six traders. Given every fact and left to choose, Claude Haiku 5.5 (and Qwen 3.8
Flash, worse) made comparisons the facts didn't ("a larger position than most of their recent activity"), called
the other side the same side, and padded with their record in the category; given only the facts that stand out, it
only has to join them. About $0.09 per 1,000 sentences, about a second each.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import datetime
from typing import Any

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
MAX_WORDS = 40

SYSTEM = """You write one sentence of context under a trade on Signals, a site that shows what Polymarket traders do.
The line above yours ("already_said") already says what kind of move it was: don't repeat it.
Join the facts given into ONE plain-English sentence of at most 30 words that a newcomer understands. Keep every number
and every phrase like "the other side" exactly as written. Add nothing: no comparison the facts don't make, no reason
for the trade, nothing about what happens next, no advice.
Call the trader "they". Say "trade" or "position", never "bet". No jargon, no emojis, no exclamation marks. Start with
"They" or "This"."""

# words a sentence on the page never has: guesses, advice, "bet", or the model talking about its facts
NEVER = re.compile(r"\b(bets?|betting|bettors?|should|will|expects?|likely|probably|confiden\w*|copy\w*|advice|"
                   r"not given|no fact|facts?|words?\)|none)\b", re.I)  # fmt: skip
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# comparisons a sentence may only make when its facts do
GUARDED = re.compile(r"\b(larger|largest|bigger|biggest|greatest|smaller|smallest|most|least|more|less|higher|highest|"
                     r"lower|lowest|nearly|almost|only|entire|all|every|ever|again|opposite|both)\b", re.I)  # fmt: skip

# what makes a fact worth a sentence: a buy this many times their usual trade, a position this share of their open
# money, a gain or loss this share of what they put in, another trade in the same market of at least this much
BIG_X = 1.5
BIG_SHARE = 0.05
BIG_MOVE = 0.10
SAME_MARKET_MIN_USD = 100.0
MAX_FACTS = 2


def usd(x: float) -> str:
    a = abs(x)
    s = f"${a / 1e6:.2f}M" if a >= 1e6 else f"${a / 1e3:.1f}K" if a >= 1e4 else f"${a:,.0f}"
    return ("-" if x < 0 else "") + s


def cents(p: float) -> str:
    return f"{round(p * 100, 1):g}¢"


def _span(a: str, b: str) -> str:
    h = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
    n, unit = (max(1, round(h * 60)), "minute") if h < 1 else (round(h), "hour") if h < 48 else (round(h / 24), "day")
    return f"{n} {unit}{'s' * (n != 1)}"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def headline(m: dict[str, Any]) -> str:
    """The page's line that says what the change was (``moveHeadline`` in index.html: keep the two the same)."""

    def vs(word: str) -> str:
        paid = m.get("paid")
        if paid is None:
            return word
        return (f"{word}, below what they paid" if m["price"] < paid - 0.005 else f"{word}, above what they paid"
                if m["price"] > paid + 0.005 else f"{word}, at about what they paid")  # fmt: skip

    k = m["kind"]
    if k == "new":
        return "Opened a new position"
    if k == "added":
        if m.get("buy_count", 0) >= 2:
            return (f"Their {_ordinal(m['buy_count'])} buy of this" + (f" in {_span(m['opened_at'], m['at'])}" if m.get("opened_at") else "")
                    + (", each at a higher price" if m.get("rising") else ", each at a lower price" if m.get("falling") else ""))  # fmt: skip
        return "Bought more of a position they already held"
    if k == "sold_some":
        return vs("Sold some and kept the rest")
    if k == "closed":
        return vs("Sold all of it")
    return "Sold" if k == "sold" else "Bought"


def facts(m: dict[str, Any], view: dict[str, Any], record: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the sentence about move ``m`` (``watch.view``'s) says, from the watch read ``view`` and their kept record
    (``typical_usd``): the line above it, and the MAX_FACTS facts that stand out most, in this order: a buy well over
    their usual trade, a sale against what they paid, a position up or down a lot, a big share of their open money,
    their other trades in this market within a day. None when nothing stands out: then there's no sentence (the facts
    under it already say the rest, their record in the category among them)."""
    buy, said = m["action"] == "buy", []
    typical = (record or {}).get("typical_usd")
    if buy and typical and m["usd"] / typical >= BIG_X:
        said.append(f"this trade was {m['usd'] / typical:.1f}x their usual trade of {usd(typical)}")
    if not buy and m.get("paid"):
        gain = (m["price"] - m["paid"]) * m["size"]
        said.append(f"they sold at {cents(m['price'])} against {cents(m['paid'])} paid, about {usd(abs(gain))} "
                    f"{'gained' if gain >= 0 else 'lost'} on what they sold")  # fmt: skip
    h = next((x for x in view.get("holdings") or [] if x["market"] == m["market"]), None)
    if h and h.get("put_in") and h.get("value") is not None and abs(h["value"] - h["put_in"]) >= BIG_MOVE * h["put_in"]:
        gain = h["value"] - h["put_in"]
        said.append(f"the whole position, {usd(h['put_in'])} put in, is worth {usd(h['value'])} now, "
                    f"{'up' if gain >= 0 else 'down'} {usd(abs(gain))}")  # fmt: skip
    if h and h.get("put_in") and view.get("put_in") and h["put_in"] / view["put_in"] >= BIG_SHARE:
        rank = 1 + sum(1 for x in view["holdings"] if (x.get("put_in") or 0) > h["put_in"])
        said.append(f"this position is {h['put_in'] / view['put_in']:.0%} of the {usd(view['put_in'])} they have in "
                    f"open positions, {'their biggest' if rank == 1 else f'their #{rank} biggest'}")  # fmt: skip
    at = datetime.fromisoformat(m["at"]).timestamp()
    same = [x for x in view.get("moves") or [] if x.get("url") and x["url"] == m.get("url") and x is not m
            and x["usd"] >= SAME_MARKET_MIN_USD and abs(datetime.fromisoformat(x["at"]).timestamp() - at) < 86400]  # fmt: skip
    if same:
        said.append("they also " + " and ".join(
            f"{'bought' if x['action'] == 'buy' else 'sold'} {usd(x['usd'])} of {x.get('outcome')} "
            f"({'the same outcome' if x['market'] == m['market'] else 'the other side'}) "
            f"{_span(min(x['at'], m['at']), max(x['at'], m['at']))} {'before' if x['at'] < m['at'] else 'after'} this"
            for x in sorted(same, key=lambda x: -x["usd"])[:2]))  # fmt: skip
    if not said:
        return None
    return {"already_said": headline(m), "outcome": m.get("outcome"), "facts": said[:MAX_FACTS]}


def checked(text: str, f: dict[str, Any]) -> str | None:
    """The sentence as the page may show it, or None: under MAX_WORDS, none of NEVER's words, every number in it one
    the facts have, and no comparison (GUARDED) the facts don't make."""
    text = " ".join(text.split()).strip().strip('"')
    if not text or len(text.split()) > MAX_WORDS or NEVER.search(text):
        return None
    given = json.dumps(f, ensure_ascii=False)
    known = set(NUMBER.findall(given))
    if any(n.rstrip(".,") not in known for n in NUMBER.findall(text)):
        return None
    if any(w.lower() not in given.lower() for w in GUARDED.findall(text)):
        return None
    return text


def key_of(f: dict[str, Any], model: str) -> str:
    """The same facts get the same sentence: kept by this."""
    return hashlib.sha256(json.dumps([model, f], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def ask(f: dict[str, Any], *, key: str, model: str, timeout: float = 10.0) -> tuple[str | None, float | None]:
    """The model's sentence for facts ``f`` (``checked``, or None) and what it cost in dollars (OpenRouter's count)."""
    # no thinking: on OpenRouter it shares max_tokens with the answer, and joining given facts needs none
    body = {"model": model, "temperature": 0.2, "max_tokens": 200, "reasoning": {"enabled": False},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(f, ensure_ascii=False)}]}  # fmt: skip
    req = urllib.request.Request(ENDPOINT, json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})  # fmt: skip
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    text = (out.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    return checked(text, f), (out.get("usage") or {}).get("cost")
