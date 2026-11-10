"""Investigations, kept so follow-ups work: SQLite on the research service's own volume (``RESEARCH_STORE_DIR``).

- ``sessions``: one investigation per row, whose it is (Clerk user id) and its code-execution container, so a
  follow-up's code still has the last turn's variables.
- ``messages``: the conversation exactly as sent to and returned by the API (thinking blocks, code runs and tool
  calls included), so a follow-up replays it unchanged.
- ``events``: what the page was streamed, in order, so an investigation can be redrawn or a dropped stream resumed.
- ``charts``: the Vega-Lite specs the agent made.
- ``runs``: per question, tokens and dollars (Opus 5.5 list prices), rounds, tool calls and whether the number
  check passed: "what one investigation costs" (the brief's open item).
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import UTC, datetime
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, user TEXT NOT NULL, created REAL NOT NULL,
  title TEXT, container TEXT);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user, created);
CREATE TABLE IF NOT EXISTS messages (session TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL,
  content TEXT NOT NULL, hidden INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (session, seq));
CREATE TABLE IF NOT EXISTS events (session TEXT NOT NULL, seq INTEGER NOT NULL, at REAL NOT NULL,
  event TEXT NOT NULL, PRIMARY KEY (session, seq));
CREATE TABLE IF NOT EXISTS charts (id TEXT PRIMARY KEY, session TEXT NOT NULL, created REAL NOT NULL,
  title TEXT, caption TEXT, spec TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT NOT NULL, user TEXT NOT NULL,
  started REAL NOT NULL, ended REAL, day TEXT NOT NULL, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
  cache_read INTEGER DEFAULT 0, cache_write INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0, rounds INTEGER DEFAULT 0,
  tool_calls INTEGER DEFAULT 0, check_ok INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS inv_trades (session TEXT NOT NULL, trade_id TEXT NOT NULL, ts INTEGER NOT NULL,
  slug TEXT, row TEXT NOT NULL, PRIMARY KEY (session, trade_id));
CREATE INDEX IF NOT EXISTS inv_trades_slug ON inv_trades(session, slug, ts);
CREATE TABLE IF NOT EXISTS inv_windows (session TEXT NOT NULL, slug TEXT NOT NULL, updated REAL NOT NULL,
  read TEXT, ready TEXT, summary TEXT, PRIMARY KEY (session, slug));
CREATE TABLE IF NOT EXISTS findings (session TEXT NOT NULL, id TEXT NOT NULL, n INTEGER NOT NULL, updated REAL NOT NULL,
  data TEXT NOT NULL, PRIMARY KEY (session, id));
"""
# (table, column definition): when the session's container was made (they expire after 30 days), and per question
# the code runs, the container's estimated seconds and their dollars (cost_usd includes them).
ADDED = [("sessions", "container_at REAL"), ("runs", "code_runs INTEGER DEFAULT 0"),
         ("runs", "container_s INTEGER DEFAULT 0"), ("runs", "container_usd REAL DEFAULT 0"),
         ("sessions", "wallet TEXT"), ("sessions", "scope TEXT")]  # fmt: skip


def day(t: float | None = None) -> str:
    return datetime.fromtimestamp(t or time.time(), UTC).strftime("%Y-%m-%d")


class Store:
    def __init__(self, path: str | None = None) -> None:
        if path is None:
            folder = os.environ.get("RESEARCH_STORE_DIR", os.path.expanduser("~/.signals-research"))
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "research.db")
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)
            for table, col in ADDED:  # columns added after a store was first made
                have = {r[1] for r in self._db.execute(f"PRAGMA table_info({table})")}
                if col.split()[0] not in have:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {col}")

    def _q(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # ---- sessions ----

    def new_session(self, user: str, title: str | None = None) -> str:
        sid = secrets.token_urlsafe(12)
        self._q("INSERT INTO sessions (id, user, created, title) VALUES (?, ?, ?, ?)", (sid, user, time.time(), title))
        return sid

    def session(self, sid: str, user: str) -> dict[str, Any] | None:
        """The session, only for the user it belongs to."""
        rows = self._q("SELECT * FROM sessions WHERE id = ? AND user = ?", (sid, user))
        return dict(rows[0]) if rows else None

    def session_any(self, sid: str) -> dict[str, Any] | None:
        """The session whoever it belongs to: for the agent, after the server checked the owner."""
        rows = self._q("SELECT * FROM sessions WHERE id = ?", (sid,))
        return dict(rows[0]) if rows else None

    def sessions(self, user: str, limit: int = 50) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT id, created, title FROM sessions WHERE user = ? ORDER BY created DESC LIMIT ?", (user, limit))]  # fmt: skip

    def set_container(self, sid: str, container: str | None) -> None:
        """The session's code container, and when it was first given (None: none, a new one next time)."""
        self._q("UPDATE sessions SET container = ?, container_at = ? WHERE id = ?",
                (container, time.time() if container else None, sid))  # fmt: skip

    def set_title(self, sid: str, title: str) -> None:
        self._q("UPDATE sessions SET title = COALESCE(title, ?) WHERE id = ?", (title, sid))

    # ---- the conversation ----

    def messages(self, sid: str) -> list[dict[str, Any]]:
        return [{"role": r["role"], "content": json.loads(r["content"])}
                for r in self._q("SELECT role, content FROM messages WHERE session = ? ORDER BY seq", (sid,))]  # fmt: skip

    def add_message(self, sid: str, role: str, content: Any, hidden: bool = False) -> None:
        with self._lock:
            seq = self._db.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM messages WHERE session = ?", (sid,)).fetchone()[0]
            self._db.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", (sid, seq, role, json.dumps(content), int(hidden)))

    def replace_last_message(self, sid: str, content: Any) -> None:
        """The conversation's last message, with new content (the user's words joining a tool's result)."""
        self._q("UPDATE messages SET content = ? WHERE session = ? AND seq = "
                "(SELECT MAX(seq) FROM messages WHERE session = ?)", (json.dumps(content), sid, sid))  # fmt: skip

    # ---- events ----

    def add_event(self, sid: str, event: dict[str, Any]) -> int:
        with self._lock:
            seq = self._db.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM events WHERE session = ?", (sid,)).fetchone()[0]
            self._db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (sid, seq, time.time(), json.dumps(event, default=str)))
        return int(seq)

    def events(self, sid: str, after: int = -1) -> list[dict[str, Any]]:
        return [json.loads(r["event"]) | {"seq": r["seq"]}
                for r in self._q("SELECT seq, event FROM events WHERE session = ? AND seq > ? ORDER BY seq", (sid, after))]  # fmt: skip

    # ---- charts ----

    def add_chart(self, sid: str, title: str, spec: dict[str, Any], caption: str | None) -> str:
        cid = "c_" + secrets.token_urlsafe(8)
        self._q("INSERT INTO charts VALUES (?, ?, ?, ?, ?, ?)", (cid, sid, time.time(), title, caption, json.dumps(spec)))
        return cid

    def chart(self, cid: str, user: str) -> dict[str, Any] | None:
        rows = self._q("SELECT c.* FROM charts c JOIN sessions s ON s.id = c.session WHERE c.id = ? AND s.user = ?",
                       (cid, user))  # fmt: skip
        if not rows:
            return None
        r = dict(rows[0])
        return r | {"spec": json.loads(r["spec"])}

    # ---- what the investigation read: the wallet's fills and its windows (the case file draws from these) ----

    def set_scope(self, sid: str, scope: dict[str, Any]) -> None:
        """The scope of the plan last proposed ({wallet, family, from, to}): what Start builds tiles for."""
        self._q("UPDATE sessions SET scope = ? WHERE id = ?", (json.dumps(scope), sid))

    def scope(self, sid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT scope FROM sessions WHERE id = ?", (sid,))
        return json.loads(rows[0]["scope"]) if rows and rows[0]["scope"] else None

    def set_wallet(self, sid: str, wallet: str) -> None:
        self._q("UPDATE sessions SET wallet = COALESCE(wallet, ?) WHERE id = ?", (wallet, sid))

    def add_trades(self, sid: str, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO inv_trades VALUES (?, ?, ?, ?, ?)",
                                 [(sid, r["id"], r["ts"], r.get("slug"), json.dumps(r)) for r in rows])  # fmt: skip

    def trades(self, sid: str, slug: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT row FROM inv_trades WHERE session = ?", (sid,)
        if slug is not None:
            sql, args = sql + " AND slug = ?", (sid, slug)
        return [json.loads(r["row"]) for r in self._q(sql + " ORDER BY ts", args)]

    def trade(self, sid: str, trade_id: str) -> dict[str, Any] | None:
        rows = self._q("SELECT row FROM inv_trades WHERE session = ? AND trade_id = ?", (sid, trade_id))
        return json.loads(rows[0]["row"]) if rows else None

    def put_window(self, sid: str, slug: str, **parts: Any) -> None:
        """Keeps any of ``read`` (the window tool's answer), ``ready`` and ``summary``; the others stay."""
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO inv_windows (session, slug, updated) VALUES (?, ?, ?)",
                             (sid, slug, time.time()))  # fmt: skip
            for k, v in parts.items():
                if k in ("read", "ready", "summary"):
                    self._db.execute(f"UPDATE inv_windows SET {k} = ?, updated = ? WHERE session = ? AND slug = ?",  # noqa: S608
                                     (json.dumps(v), time.time(), sid, slug))  # fmt: skip

    def window(self, sid: str, slug: str) -> dict[str, Any]:
        """{read, ready, summary} kept for this window (each None when not yet)."""
        rows = self._q("SELECT read, ready, summary FROM inv_windows WHERE session = ? AND slug = ?", (sid, slug))
        if not rows:
            return {"read": None, "ready": None, "summary": None}
        return {k: json.loads(rows[0][k]) if rows[0][k] else None for k in ("read", "ready", "summary")}

    def unshown(self, sid: str) -> list[str]:
        """Windows read in this investigation that have no tile (summary) yet."""
        return [r["slug"] for r in self._q(
            "SELECT slug FROM inv_windows WHERE session = ? AND read IS NOT NULL AND summary IS NULL ORDER BY slug",
            (sid,))]  # fmt: skip

    def summaries(self, sid: str) -> list[dict[str, Any]]:
        return [json.loads(r["summary"]) for r in self._q(
            "SELECT summary FROM inv_windows WHERE session = ? AND summary IS NOT NULL ORDER BY slug", (sid,))]  # fmt: skip

    # ---- findings: the evidence cards, each with the versions it had ----

    def add_finding(self, sid: str, data: dict[str, Any]) -> str:
        """A new finding, F<n> in this investigation; returns its id."""
        with self._lock:
            n = self._db.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM findings WHERE session = ?", (sid,)).fetchone()[0]
            fid = f"F{n}"
            self._db.execute("INSERT INTO findings VALUES (?, ?, ?, ?, ?)",
                             (sid, fid, n, time.time(), json.dumps({**data, "finding_id": fid})))  # fmt: skip
        return fid

    def update_finding(self, sid: str, fid: str, data: dict[str, Any]) -> None:
        self._q("UPDATE findings SET data = ?, updated = ? WHERE session = ? AND id = ?",
                (json.dumps({**data, "finding_id": fid}), time.time(), sid, fid))  # fmt: skip

    def finding(self, sid: str, fid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT data FROM findings WHERE session = ? AND id = ?", (sid, fid))
        return json.loads(rows[0]["data"]) if rows else None

    def findings(self, sid: str) -> list[dict[str, Any]]:
        return [json.loads(r["data"]) for r in self._q("SELECT data FROM findings WHERE session = ? ORDER BY n", (sid,))]

    # ---- costs ----

    def start_run(self, sid: str, user: str) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO runs (session, user, started, day) VALUES (?, ?, ?, ?)",
                                   (sid, user, time.time(), day()))  # fmt: skip
            return int(cur.lastrowid or 0)

    def update_run(self, run: int, **fields: Any) -> None:
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            self._q(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run))  # noqa: S608 (column names are ours)

    def unfinished_runs(self) -> list[dict[str, Any]]:
        """Runs with no end written: at startup, the ones the last process died in (oldest first)."""
        return [dict(r) for r in self._q("SELECT id, session, user, started FROM runs WHERE ended IS NULL ORDER BY id")]

    def latest_runs(self, sessions: set[str]) -> dict[str, int]:
        """Each session's newest run."""
        if not sessions:
            return {}
        marks = ", ".join("?" for _ in sessions)
        return {r["session"]: r["id"] for r in self._q(
            f"SELECT session, MAX(id) AS id FROM runs WHERE session IN ({marks}) GROUP BY session", tuple(sessions))}  # noqa: S608 # fmt: skip

    def spent_today(self, user: str | None = None) -> float:
        sql, args = "SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE day = ?", (day(),)
        if user is not None:
            sql, args = sql + " AND user = ?", (*args, user)
        return float(self._q(sql, args)[0][0])

    def runs(self, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
