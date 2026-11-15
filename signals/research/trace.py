"""Every number in the agent's answer must trace back to data: ``why.checked()``'s rule, for longer answers.

A number in the answer traces when some value in what the agent was given or worked out (tool results, its code's
printed output, the question and the instructions) rounds to it: "$40.1k" traces to 40,055.41, "53¢" and "53%"
to 0.53, "4,173 trades" to 4173. Times and dates (14:02, 2026-11-09, Nov 9), wallet addresses, slugs and list
numbers are not checked. It's a guardrail, not a proof: a small count ("3 windows") can match some unrelated 3.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from typing import Any

MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
SKIP = re.compile(
    r"0x[0-9a-fA-F]+(?:…|\.\.\.)[0-9a-fA-F]+|0x[0-9a-fA-F]{6,}"  # wallets, tx hashes, shortened (0x91…76)
    r"|[a-z0-9]+-updown-\d+m-\d+"  # window slugs
    r"|\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)?"  # ISO dates and times
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"  # times of day
    rf"|\b{MONTHS}\s+\d{{1,2}}\b|\b\d{{1,2}}\s+{MONTHS}"  # Nov 9, 9 Nov
    r"|^\s*\d+[.)]\s",  # list numbers
    re.M,
)
# A number as written: sign, currency, digits with commas, decimals, then k/M/B, % or ¢.
NUM = re.compile(r"(?P<neg>[-−])?\$?(?P<n>\d[\d,]*(?:\.\d+)?)(?:\s?(?P<mult>[kKmMbB])\b)?\s?(?P<unit>%|¢)?")
MULT = {"k": 1e3, "m": 1e6, "b": 1e9}
# A value in the data: a whole number token, never digits inside a hash, an id or a word ("0x21f4c1a1", "15m").
SOURCE_NUM = re.compile(r"(?<![0-9A-Za-z_.])\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![0-9A-Za-z_])")


def located(text: str) -> list[tuple[str, float, float, int, int]]:
    """The numbers ``text`` states: (as written, value, how far rounding could have moved it, start, end), with
    start and end character offsets into ``text`` itself."""
    blanked = SKIP.sub(lambda m: " " * len(m.group(0)), text)  # same length, so offsets hold
    out = []
    for m in NUM.finditer(blanked):
        whole = m.group(0)
        raw = whole.strip()
        start = m.start() + (len(whole) - len(whole.lstrip()))
        digits = m["n"].replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = MULT.get((m["mult"] or "").lower(), 1.0)
        value = float(digits) * scale
        # Rounded to its last digit; an integer with grouping commas or a k/M is at least that coarse.
        tol = 0.5 * 10**-decimals * scale + 1e-9
        out.append((raw, value, tol, start, start + len(raw)))
    return out


def numbers(text: str) -> list[tuple[str, float, float]]:
    """The numbers ``text`` states, each as (as written, value, how far rounding could have moved it)."""
    return [(raw, value, tol) for raw, value, tol, _, _ in located(text)]


class Sources:
    """Every value the agent was shown or printed, for looking numbers up."""

    def __init__(self, texts: Iterable[str] = (), *, data: bool = True) -> None:
        self._values: list[float] = []
        self._data: list[float] = []  # values from the data only (tool results, printed output), for ``nearest``
        self.add(*texts, data=data)

    def add(self, *texts: str, data: bool = True) -> None:
        """Values a number may trace to. ``data`` false for the instructions and the user's words: they let a number
        pass but are never offered as what the data says."""
        vals = []
        for t in texts:
            for s in SOURCE_NUM.findall(t or ""):
                try:
                    vals.append(abs(float(s)))
                except ValueError:
                    continue
        self._values = sorted(set(self._values).union(vals))
        if data:
            self._data = sorted(set(self._data).union(vals))

    def has(self, value: float, tol: float, scaled: bool = True) -> bool:
        """A value within ``tol`` of ``value``: as is, or (``scaled``: not written in dollars) as a share or a
        price written in percent or cents (×100)."""
        for k in (1, 100) if scaled else (1,):
            x, t = abs(value) / k, tol / k
            i = bisect.bisect_left(self._values, x - t)
            if i < len(self._values) and self._values[i] <= x + t:
                return True
        return False

    def nearest(self, value: float, within: float = 0.1, scaled: bool = True) -> float | None:
        """The data's value closest to ``value`` (as is, or a share written ×100 when ``scaled``), when it's within
        ``within`` of it relatively: what the number probably meant to say. None when nothing is that close."""
        best: tuple[float, float] | None = None
        vals = self._data
        for x, k in ((abs(value), 1.0), (abs(value) / 100, 100.0)) if scaled else ((abs(value), 1.0),):
            i = bisect.bisect_left(vals, x)
            for j in (i - 1, i):
                if 0 <= j < len(vals) and x:
                    d = abs(vals[j] - x) / x
                    if d <= within and (best is None or d < best[0]):
                        best = (d, vals[j] * k)
        return None if best is None else best[1]


def flagged(text: str, sources: Sources) -> list[dict[str, Any]]:
    """Each number in ``text`` that doesn't trace: {value_text, start, end, data_value} (offsets into ``text``;
    ``data_value`` the closest value in the data, or None), for the page to strike it and show the data's."""
    return [{"value_text": raw, "start": a, "end": b, "data_value": sources.nearest(value, scaled=_scaled(raw))}
            for raw, value, tol, a, b in located(text) if not sources.has(value, tol, _scaled(raw))]  # fmt: skip


def _scaled(raw: str) -> bool:
    """A dollar amount is never a share or a price ×100: "$98" isn't 0.98."""
    return "$" not in raw


def check(text: str, sources: Sources) -> dict[str, Any]:
    """Which of ``text``'s numbers trace to ``sources``: ``unmatched`` lists the ones that don't, as written."""
    found = numbers(text)
    unmatched = [raw for raw, value, tol in found if not sources.has(value, tol, _scaled(raw))]
    return {"ok": not unmatched, "checked": len(found), "unmatched": list(dict.fromkeys(unmatched))}


# Words the research wording rules never use (AGENTS.md "Research wording", 6 and 5; SYSTEM "# Wording"), with what
# to say instead. A finding, step or answer using one gets one chance to reword it (``case.Case.check``).
BANNED = [
    (re.compile(r"\bbet(?:s|ting|tor|tors)?\b", re.IGNORECASE), "say trade, never bet"),
    (re.compile(r"\bgambl(?:e|es|ed|ing)\b", re.IGNORECASE), "say trade"),
    (re.compile(r"\bROI\b"), "say the profit worked out from fills"),
    (re.compile(r"\b(?:edge|alpha)\b", re.IGNORECASE), "say what the data shows, never edge or alpha"),
    (re.compile(r"\bsmart money\b", re.IGNORECASE), "describe what the data shows"),
    (re.compile(r"\bwin streak\b", re.IGNORECASE), "count the markets or windows"),
    (re.compile(r"\b(?:its|it's|it is) a bot\b", re.IGNORECASE), "intent is never fact"),
    (re.compile(r"\bfront[- ]?runs?\b|\bfront[- ]?running\b", re.IGNORECASE), "intent is never fact"),
    (re.compile(r"\b(?:worth following|you could|buy when)\b", re.IGNORECASE), "no advice"),
]


def banned_words(text: str) -> list[tuple[str, str]]:
    """The banned words ``text`` uses, as written, each with what to do instead."""
    out = []
    for rx, why in BANNED:
        for m in rx.finditer(text or ""):
            out.append((m.group(0), why))
    return out
