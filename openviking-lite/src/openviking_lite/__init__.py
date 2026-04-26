"""OpenViking-lite — minimal SQLite-FTS5 backend for L4 semantic memory.

Implements the subset of the OpenViking HTTP API used by the gateway:
sessions, messages, extract (no-op stub), resources (file storage + indexing).
Full-text search via SQLite FTS5 — no embeddings, no vector DB.
"""

__version__ = "0.0.1"
