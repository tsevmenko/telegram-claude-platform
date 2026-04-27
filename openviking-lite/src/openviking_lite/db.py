"""SQLite schema + helpers for OpenViking-lite.

Two FTS5 virtual tables:

- ``messages`` — chat-session messages (role + content + meta).
- ``resources`` — uploaded markdown resources (URI + content).

Plus ordinary tables for sessions and temp uploads. Everything fits in one
SQLite file; no separate vector store, no migrations beyond the initial
``schema.sql`` here.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# FTS5 reserves special characters and keywords; passing user input straight
# into MATCH raises sqlite3.OperationalError. Strip everything that isn't a
# word/whitespace character and drop FTS5 boolean keywords. Empty result
# returns the no-match sentinel "*" (matches nothing rather than crashing).
_FTS5_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}
_FTS5_NON_WORD = re.compile(r"[^\w\s]+", flags=re.UNICODE)


def _sanitize_fts5(query: str) -> str:
    cleaned = _FTS5_NON_WORD.sub(" ", query or "")
    tokens = [t for t in cleaned.split() if t.upper() not in _FTS5_KEYWORDS]
    if not tokens:
        # Sentinel that matches nothing — avoids '' which is also a syntax error.
        return '"___no_match_sentinel___"'
    return " ".join(tokens)

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

CREATE TABLE IF NOT EXISTS embeddings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,        -- 'message' or 'resource'
    ref_id     TEXT NOT NULL,        -- "<session_id>:<seq>" for messages, uri for resources
    account    TEXT NOT NULL,
    content    TEXT NOT NULL,
    vector     BLOB NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embeddings_kind_account
    ON embeddings(kind, account);
CREATE UNIQUE INDEX IF NOT EXISTS idx_embeddings_unique
    ON embeddings(kind, ref_id);
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

    def add_message(self, sid: str, role: str, content: str, meta: str = "") -> int:
        """Append a message and return its FTS5 rowid (for embedding ref_id)."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages (session_id, role, content, meta) VALUES (?, ?, ?, ?)",
                (sid, role, content, meta),
            )
            return int(cur.lastrowid or 0)

    def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        safe = _sanitize_fts5(query)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, role, content, meta, rank
                FROM messages
                WHERE messages MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe, limit),
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
        safe = _sanitize_fts5(query)
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
                    (safe, account, limit),
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
                    (safe, limit),
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

    # ------------------------------------------------------------------
    # Embeddings (semantic search backing store)
    # ------------------------------------------------------------------

    def upsert_embedding(self, kind: str, ref_id: str, account: str,
                         content: str, vector_bytes: bytes) -> None:
        """Insert or replace an embedding row."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM embeddings WHERE kind = ? AND ref_id = ?",
                (kind, ref_id),
            )
            conn.execute(
                "INSERT INTO embeddings (kind, ref_id, account, content, vector, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kind, ref_id, account, content, vector_bytes, time.time()),
            )

    def candidate_embeddings(
        self,
        *,
        kind: str | None = None,
        account: str | None = None,
        limit: int | None = None,
    ) -> list[tuple[str, bytes, str]]:
        """Return ``(ref_id, vector_blob, content)`` tuples for cosine scoring."""
        clauses = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?"); params.append(kind)
        if account:
            clauses.append("account = ?"); params.append(account)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT ref_id, vector, content FROM embeddings{where}"
        if limit:
            sql += " LIMIT ?"; params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [(r["ref_id"], r["vector"], r["content"]) for r in rows]

    def count_embeddings(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()
        return int(row["n"])
