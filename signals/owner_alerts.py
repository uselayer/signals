"""The owner's alerts: a Telegram message to the owner when the hosted app breaks, so an outage isn't found days later
by a visitor (2026-11-02→04: the volume filled up, Traders answered 500 for ~50 hours, and the only trace was the
logs). Three checks, each minute (``app._monitor_loop``):

- the store's disk: DISK_WARN of its space or of its inodes (files) used; at 100% SQLite can't read directory.db;
- server errors: any answer of 500, or an error raised, in the last ERRORS_WINDOW_S (``ServerErrors`` records them);
- trader scoring: the background evaluation failing every round for SCORING_FAILING_S.

A problem is told once when it starts, again every REMIND_S while it lasts, and once more when it's gone ("Fixed").
Nothing here touches the disk (it must work when the disk is what broke): what was told is kept in memory, so a restart
may tell an ongoing problem again, never miss one. A message that couldn't be sent is tried again the next minute."""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DISK_WARN = 0.85  # a share of the disk's space, or of its inodes, in use that's told
ERRORS_WINDOW_S = 600  # server errors are counted over this long
SCORING_FAILING_S = 1800  # the evaluation failing this long, every round, is told
REMIND_S = 6 * 3600  # an ongoing problem is told again this often
GB = 1e9


class Errors:
    """The server errors of the last ``window`` seconds (when, the path, why), from any thread."""

    def __init__(self, window: float = ERRORS_WINDOW_S) -> None:
        self.window = window
        self._rows: deque[tuple[float, str, str]] = deque()
        self._lock = threading.Lock()

    def add(self, path: str, why: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._rows.append((now, path, why))
            self._trim(now)

    def recent(self, now: float | None = None) -> list[tuple[float, str, str]]:
        now = time.time() if now is None else now
        with self._lock:
            self._trim(now)
            return list(self._rows)

    def _trim(self, now: float) -> None:
        while self._rows and self._rows[0][0] < now - self.window:
            self._rows.popleft()


errors = Errors()


class ServerErrors:
    """ASGI middleware: every answer of 500, and every error raised past the routes (Starlette answers those 500),
    into ``errors`` with its path (never the query, which can hold a search) and why."""

    def __init__(self, app: Callable[..., Awaitable[None]], into: Errors | None = None) -> None:
        self.app, self._into = app, into

    def _e(self) -> Errors:
        return self._into or errors

    async def __call__(self, scope: MutableMapping[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        told = False

        async def watched(message: MutableMapping[str, Any]) -> None:
            nonlocal told
            if message["type"] == "http.response.start" and message.get("status") == 500 and not told:
                told = True
                self._e().add(path, "answered 500")
            await send(message)

        try:
            await self.app(scope, receive, watched)
        except Exception as e:
            if not told:
                self._e().add(path, f"{type(e).__name__}: {e}"[:160])
            raise


def disk_problem(folder: Path, warn: float = DISK_WARN) -> str | None:
    """What's wrong with the disk under ``folder``, in a sentence, or None while there's room."""
    try:
        total, used, _ = shutil.disk_usage(folder)
        st = os.statvfs(folder)
    except OSError as e:
        return f"The disk couldn't be checked ({type(e).__name__}: {e})."
    share = used / total if total else 0.0
    inodes = 1 - st.f_ffree / st.f_files if st.f_files else 0.0
    if share >= warn:
        return (f"The disk is {share:.0%} full ({used / GB:.1f} of {total / GB:.1f} GB). When it's full, the Traders "
                "page stops working. Make the volume bigger on Railway, or clear space.")  # fmt: skip
    if inodes >= warn:
        return (f"The disk has used {inodes:.0%} of its file slots. When they run out, the Traders page stops working. "
                "Clear old files (the price cache) or make the volume bigger on Railway.")  # fmt: skip
    return None


def errors_problem(rows: list[tuple[float, str, str]], window: float = ERRORS_WINDOW_S) -> str | None:
    """The server errors of the last ``window`` in a sentence (how many, on which pages, the latest why), or None."""
    if not rows:
        return None
    by_path: dict[str, int] = {}
    for _, path, _ in rows:
        by_path[path] = by_path.get(path, 0) + 1
    where = ", ".join(f"{p} ×{n}" if n > 1 else p for p, n in sorted(by_path.items(), key=lambda x: -x[1])[:4])
    n = len(rows)
    return (f"{n} request{'s' if n != 1 else ''} failed with a server error in the last {window / 60:.0f} minutes "
            f"({where}). Visitors see \"Couldn't load this\". Latest: {rows[-1][2]}")  # fmt: skip


def scoring_problem(error: str | None, since: float | None, now: float, after: float = SCORING_FAILING_S) -> str | None:
    """Trader scoring failing every round since ``since`` (with ``error``), told once it's lasted ``after``."""
    if not error or since is None or now - since < after:
        return None
    return (f"Trader scoring has failed every round for {_ago(now - since)}: {error}. The leaderboard isn't getting "
            "new or updated records.")  # fmt: skip


FIXED = {
    "disk": "The disk has room again.",
    "errors": f"No server errors for {ERRORS_WINDOW_S // 60} minutes.",
    "scoring": "Trader scoring is working again.",
    "login_button": "Alerts carry the sign-in button again.",
}


def login_button_problem(refused: str | None, bot: str | None = None) -> str | None:
    """Telegram refused an alert for its sign-in button (``refused``: its words), so alerts go out without the button
    until a restart. What to do: link the bot to the site in BotFather, or switch the button off."""
    if not refused:
        return None
    who = f"@{bot}" if bot else "the bot"
    return (f"Telegram refused an alert for its sign-in button ({refused}). Alerts go out without the button until the "
            f"next restart. In BotFather, /setdomain → {who} → usesignals.app, then redeploy; or set SIGNALS_TG_LOGIN=0.")


@dataclass
class Problem:
    since: float
    text: str
    told_at: float | None = None


class Watch:
    """What's wrong now and what the owner was told, in memory. ``update`` each minute with each check's sentence
    (None: fine); ``send`` delivers one message and says whether it went."""

    def __init__(self, send: Callable[[str], bool]) -> None:
        self.send = send
        self.problems: dict[str, Problem] = {}

    def update(self, key: str, text: str | None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        p = self.problems.get(key)
        if text is None:
            if p is not None:
                del self.problems[key]
                if p.told_at is not None:  # only a problem the owner heard about is worth a "fixed"
                    self.send(f"Signals, fixed: {FIXED.get(key, 'it')} It lasted {_ago(now - p.since)}.")
            return
        if p is None:
            p = self.problems[key] = Problem(now, text)
        p.text = text
        if p.told_at is None:
            if self.send(f"Signals needs a look: {text}"):
                p.told_at = now
        elif now - p.told_at >= REMIND_S:
            if self.send(f"Signals, still broken ({_ago(now - p.since)} so far): {text}"):
                p.told_at = now


def _ago(seconds: float) -> str:
    m = max(1, round(seconds / 60))
    return f"{m} min" if m < 120 else f"{seconds / 3600:.0f} hours"
