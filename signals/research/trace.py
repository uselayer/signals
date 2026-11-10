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
SOURCE_NUM = re.compile(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def numbers(text: str) -> list[tuple[str, float, float]]:
    """The numbers ``text`` states, each as (as written, value, how far rounding could have moved it)."""
    text = SKIP.sub(" ", text)
    out = []
    for m in NUM.finditer(text):
        raw = m.group(0).strip()
        digits = m["n"].replace(",", "")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = MULT.get((m["mult"] or "").lower(), 1.0)
        value = float(digits) * scale
        # Rounded to its last digit; an integer with grouping commas or a k/M is at least that coarse.
        tol = 0.5 * 10**-decimals * scale + 1e-9
        out.append((raw, value, tol))
    return out


class Sources:
    """Every value the agent was shown or printed, for looking numbers up."""

    def __init__(self, texts: Iterable[str] = ()) -> None:
        self._values: list[float] = []
        self.add(*texts)

    def add(self, *texts: str) -> None:
        vals = []
        for t in texts:
            for s in SOURCE_NUM.findall(t or ""):
                try:
                    vals.append(abs(float(s)))
                except ValueError:
                    continue
        self._values = sorted(set(self._values).union(vals))

    def has(self, value: float, tol: float) -> bool:
        """A value within ``tol`` of ``value``, as is or as a share/price written in percent or cents (×100)."""
        for x in (abs(value), abs(value) / 100):
            i = bisect.bisect_left(self._values, x - tol / (1 if x == abs(value) else 100))
            if i < len(self._values) and self._values[i] <= x + tol / (1 if x == abs(value) else 100):
                return True
        return False


def check(text: str, sources: Sources) -> dict[str, Any]:
    """Which of ``text``'s numbers trace to ``sources``: ``unmatched`` lists the ones that don't, as written."""
    found = numbers(text)
    unmatched = [raw for raw, value, tol in found if not sources.has(value, tol)]
    return {"ok": not unmatched, "checked": len(found), "unmatched": list(dict.fromkeys(unmatched))}
