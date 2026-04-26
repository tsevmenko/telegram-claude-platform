"""SQLite schema + helpers for OpenViking-lite.

Two FTS5 virtual tables:

- ``messages`` — chat-session messages (role + content + meta).
- ``resources`` — uploaded markdown resources (URI + content).

Plus ordinary tables for sessions and temp uploads. Everything fits in one
SQLite file; no separate vector store, no migrations beyond the initial
``schema.sql`` here.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    account    TEXT NOT NULL,
    user       TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5(
    session_id UNINDEXED,
    role,
    content,
    meta UNINDEXED,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS temp_uploads (
    temp_file_id TEXT PRIMARY KEY,
    account      TEXT NOT NULL,
    user         TEXT NOT NULL,
    filename     TEXT NOT NULL,
    body         BLOB NOT NULL,
    created_at   REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS resources USING fts5(
    uri UNINDEXED,
    account UNINDEXED,
    user UNINDEXED,
    content,
    updated_at UNINDEXED,
    tokenize = 'porter unicode61'
);
"""


class DB:
    """Thread-safe SQLite wrapper."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        # SQLite connections are not thread-safe; create a fresh one per call
        # and serialize via _lock for write paths.
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, account: str, user: str) -> str:
        sid = str(uuid.uuid4())
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, account, user, created_at) VALUES (?, ?, ?, ?)",
                (sid, account, user, time.time()),
            )
        return sid

    def session_exists(self, sid: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (sid,)
            ).fetchone()
        return row is not None

    def delete_session(self, sid: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def add_message(self, sid: str, role: str, content: str, meta: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, meta) VALUES (?, ?, ?, ?)",
                (sid, role, content, meta),
            )

    def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, role, content, meta, rank
                FROM messages
                WHERE messages MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Resources (idempotent by URI)
    # ------------------------------------------------------------------

    def store_temp_upload(self, account: str, user: str, filename: str, body: bytes) -> str:
        temp_id = str(uuid.uuid4())
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO temp_uploads (temp_file_id, account, user, filename, body, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (temp_id, account, user, filename, body, time.time()),
            )
        return temp_id

    def consume_temp_upload(self, temp_id: str) -> tuple[str, bytes] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT filename, body FROM temp_uploads WHERE temp_file_id = ?", (temp_id,)
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM temp_uploads WHERE temp_file_id = ?", (temp_id,))
        return row["filename"], row["body"]

    def upsert_resource(self, account: str, user: str, uri: str, content: str) -> None:
        with self._lock, self._connect() as conn:
            # FTS5 doesn't support UPSERT directly — delete + insert.
            conn.execute(
                "DELETE FROM resources WHERE uri = ? AND account = ?", (uri, account)
            )
            conn.execute(
                "INSERT INTO resources (uri, account, user, content, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uri, account, user, content, str(time.time())),
            )

    def search_resources(self, query: str, account: str | None = None,
                         limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if account:
                rows = conn.execute(
                    """
                    SELECT uri, content, updated_at, rank
                    FROM resources
                    WHERE resources MATCH ? AND account = ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, account, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT uri, content, updated_at, rank
                    FROM resources
                    WHERE resources MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def list_resources(self, account: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if account:
                rows = conn.execute(
                    "SELECT uri, updated_at FROM resources WHERE account = ?",
                    (account,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT uri, account, updated_at FROM resources"
                ).fetchall()
        return [dict(r) for r in rows]
