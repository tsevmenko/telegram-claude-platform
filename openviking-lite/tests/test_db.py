"""SQLite FTS5 layer tests."""

from __future__ import annotations

from pathlib import Path

from openviking_lite.db import DB


def _db(tmp_path: Path) -> DB:
    return DB(tmp_path / "test.db")


def test_create_and_lookup_session(tmp_path: Path):
    db = _db(tmp_path)
    sid = db.create_session("acme", "alice")
    assert db.session_exists(sid) is True
    assert db.session_exists("nope") is False


def test_delete_session_removes_messages(tmp_path: Path):
    db = _db(tmp_path)
    sid = db.create_session("acme", "alice")
    db.add_message(sid, "user", "the cat sat on the mat")
    db.add_message(sid, "assistant", "noted")
    assert len(db.search_messages("cat")) == 1
    db.delete_session(sid)
    assert db.session_exists(sid) is False
    assert db.search_messages("cat") == []


def test_search_messages_fts5(tmp_path: Path):
    db = _db(tmp_path)
    sid = db.create_session("acme", "alice")
    db.add_message(sid, "user", "kubernetes deployment with rolling updates")
    db.add_message(sid, "user", "discussing python asyncio queues")
    db.add_message(sid, "user", "another one about kubernetes")
    hits = db.search_messages("kubernetes")
    assert len(hits) == 2
    contents = [h["content"] for h in hits]
    assert any("rolling updates" in c for c in contents)


def test_temp_upload_and_consume(tmp_path: Path):
    db = _db(tmp_path)
    temp_id = db.store_temp_upload("acme", "alice", "memo.md", b"hello world")
    consumed = db.consume_temp_upload(temp_id)
    assert consumed is not None
    fname, body = consumed
    assert fname == "memo.md"
    assert body == b"hello world"
    # Idempotent: second consume returns None.
    assert db.consume_temp_upload(temp_id) is None


def test_resource_upsert_is_idempotent(tmp_path: Path):
    db = _db(tmp_path)
    db.upsert_resource("acme", "alice", "viking://r/1", "version 1")
    db.upsert_resource("acme", "alice", "viking://r/1", "version 2")
    rows = db.list_resources("acme")
    assert len(rows) == 1
    hits = db.search_resources("version", account="acme")
    assert len(hits) == 1
    assert "version 2" in hits[0]["content"]


def test_search_resources_account_scoped(tmp_path: Path):
    db = _db(tmp_path)
    db.upsert_resource("a", "x", "viking://r/1", "shared knowledge about ferns")
    db.upsert_resource("b", "y", "viking://r/2", "shared knowledge about cacti")
    a_hits = db.search_resources("knowledge", account="a")
    b_hits = db.search_resources("knowledge", account="b")
    all_hits = db.search_resources("knowledge")
    assert len(a_hits) == 1 and "ferns" in a_hits[0]["content"]
    assert len(b_hits) == 1 and "cacti" in b_hits[0]["content"]
    assert len(all_hits) == 2
