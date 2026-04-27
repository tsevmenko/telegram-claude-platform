"""FTS5 query sanitisation tests.

Regression guard for the bug where any user query containing FTS5 special
chars (``?``, ``:``, ``"``, ``-`` etc.) raised
``sqlite3.OperationalError: fts5: syntax error near "?"``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openviking_lite.db import DB, _sanitize_fts5
from openviking_lite.embeddings import encode


def test_sanitize_strips_question_mark():
    assert "?" not in _sanitize_fts5("какой rate limit у API нашего сервиса?")


def test_sanitize_strips_quotes():
    assert "\"" not in _sanitize_fts5('he said "hello" loudly')
    assert "'" not in _sanitize_fts5("don't worry")


def test_sanitize_strips_special_punctuation():
    s = _sanitize_fts5("foo: bar.baz; (test) [more] {even} *star* +plus -minus / slash")
    for ch in ":.;()[]{}*+-/":
        assert ch not in s


def test_sanitize_keeps_words():
    s = _sanitize_fts5("kubernetes deployment strategies")
    assert "kubernetes" in s
    assert "deployment" in s
    assert "strategies" in s


def test_sanitize_drops_boolean_keywords():
    """FTS5 'AND', 'OR', 'NOT', 'NEAR' as bare tokens trigger boolean parser."""
    s = _sanitize_fts5("kubernetes AND docker OR podman NOT helm")
    upper = s.upper().split()
    assert "AND" not in upper
    assert "OR" not in upper
    assert "NOT" not in upper
    # But the actual subjects survive
    assert "kubernetes" in s
    assert "docker" in s
    assert "podman" in s


def test_sanitize_empty_returns_no_match_sentinel():
    s = _sanitize_fts5("")
    assert s != ""  # sentinel guards against syntax error from empty MATCH
    s = _sanitize_fts5("?!?!")  # all stripped
    assert s != ""


def test_sanitize_preserves_cyrillic():
    s = _sanitize_fts5("какой rate limit у API нашего сервиса?")
    assert "какой" in s
    assert "rate" in s
    assert "limit" in s


def test_search_resources_does_not_crash_on_question_mark(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    db.upsert_resource("acme", "alice", "viking://r/1", "kubernetes deployment strategies")
    # The bug: this query used to raise sqlite3.OperationalError.
    hits = db.search_resources("какой rate limit у API нашего сервиса?", account="acme", limit=5)
    assert isinstance(hits, list)


def test_search_messages_does_not_crash_on_question_mark(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    sid = db.create_session("acme", "alice")
    db.add_message(sid, "user", "rate limit is 100 per minute")
    hits = db.search_messages("какой rate limit у API нашего сервиса?", limit=5)
    assert isinstance(hits, list)


def test_search_with_special_chars_finds_relevant_match(tmp_path: Path):
    db = DB(tmp_path / "ov.db")
    db.upsert_resource("acme", "alice", "viking://r/1",
                       "API rate limit is 100 requests per minute")
    db.upsert_resource("acme", "alice", "viking://r/2",
                       "deployment strategy uses RollingUpdate")
    # Query with ? still finds the rate-limit resource.
    hits = db.search_resources("rate limit?", account="acme", limit=5)
    assert any("rate limit" in h["content"] for h in hits)
