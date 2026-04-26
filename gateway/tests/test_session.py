"""SessionStore tests."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.claude_cli.session import SessionStore


def test_get_returns_none_for_unknown(tmp_path: Path):
    store = SessionStore(tmp_path)
    assert store.get("agent", 42) is None


def test_get_or_create_first_call_returns_new(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid, created = store.get_or_create("leto", 100)
    assert created
    assert len(sid) == 36  # uuid4 string length


def test_get_or_create_persists(tmp_path: Path):
    store = SessionStore(tmp_path)
    sid1, _ = store.get_or_create("leto", 100)
    sid2, created2 = store.get_or_create("leto", 100)
    assert sid1 == sid2
    assert not created2


def test_per_agent_per_chat_isolation(tmp_path: Path):
    store = SessionStore(tmp_path)
    a, _ = store.get_or_create("leto", 100)
    b, _ = store.get_or_create("vesna", 100)
    c, _ = store.get_or_create("leto", 200)
    assert len({a, b, c}) == 3


def test_reset_removes_file(tmp_path: Path):
    store = SessionStore(tmp_path)
    store.get_or_create("leto", 100)
    assert (tmp_path / "sid-leto-100.txt").exists()
    store.reset("leto", 100)
    assert not (tmp_path / "sid-leto-100.txt").exists()
    assert store.get("leto", 100) is None
