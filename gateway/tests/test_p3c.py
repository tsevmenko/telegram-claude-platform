"""Tests for Phase 3c: extended /status + graceful /reset / /new + /reset force.

Exercises the multi-line status renderer, handoff-on-reset, and force flag.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_gateway.consumer import AgentConsumer, IncomingMessage


def _make_consumer(workspace: Path, state_dir: Path) -> AgentConsumer:
    """Build a consumer with a real SessionStore and stubbed bot/runner."""
    from agent_gateway.claude_cli.session import SessionStore

    cfg = SimpleNamespace(workspace=str(workspace), bot_username="test_bot", timeout_sec=10)
    bot = MagicMock()
    bot.send_message = AsyncMock()
    runner = MagicMock()
    runner.kill = AsyncMock(return_value=False)
    runner.active = {}
    sessions = SessionStore(state_dir)
    return AgentConsumer(
        agent_name="test",
        agent_cfg=cfg,
        bot=bot,
        session_store=sessions,
        runner=runner,
    )


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Build a realistic workspace with all 4 memory files seeded."""
    wsp_root = tmp_path / "wsp"
    workspace = wsp_root / ".claude"
    state = wsp_root / "state"
    (workspace / "core" / "warm").mkdir(parents=True)
    (workspace / "core" / "hot").mkdir(parents=True)
    state.mkdir(parents=True)
    (workspace / "core" / "rules.md").write_text("rules content " * 50)
    (workspace / "core" / "warm" / "decisions.md").write_text("warm content\n" * 10)
    (workspace / "core" / "hot" / "recent.md").write_text(
        "# HOT\n\n### 2026-04-25 09:00 [tg-text]\n**User:** hi\n**Test:** hello\n"
        "\n### 2026-04-25 09:15 [tg-text]\n**User:** more\n**Test:** sure\n"
        "\n### 2026-04-25 10:00 [tg-text]\n**User:** another\n**Test:** ok\n"
    )
    (workspace / "core" / "MEMORY.md").write_text("# MEMORY\n")
    return workspace, state


# ---------------------------------------------------------------------------
# /status extended
# ---------------------------------------------------------------------------


def test_status_idle_shows_no_session_when_no_sid_file(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    rendered = consumer._render_status(chat_id=123)
    assert "status: idle" in rendered
    assert "session: (none)" in rendered


def test_status_active_when_runner_has_chat(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    consumer.runner.active = {("test", 123): "fake-active-proc"}
    rendered = consumer._render_status(chat_id=123)
    assert "status: working" in rendered


def test_status_shows_file_sizes(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    rendered = consumer._render_status(chat_id=999)
    # All four memory files seeded — should appear with sizes.
    for label in ("rules.md", "decisions.md", "recent.md", "MEMORY.md"):
        assert label in rendered
        # Size formatted as `X.Y KB` somewhere on the same line as label.
        line = next(ln for ln in rendered.splitlines() if label in ln)
        assert "KB" in line


def test_status_shows_session_age(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    sid, _ = consumer.sessions.get_or_create("test", 555)

    # Backdate the sid file by 2 hours.
    sid_path = consumer.sessions.path_for("test", 555)
    backdated = time.time() - 2 * 3600
    import os

    os.utime(sid_path, (backdated, backdated))

    rendered = consumer._render_status(chat_id=555)
    assert "session:" in rendered
    assert "2h" in rendered
    # First 8 chars of sid should appear.
    assert sid[:8] in rendered


def test_status_counts_turns(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    rendered = consumer._render_status(chat_id=1)
    # Seeded recent.md has 3 entries.
    assert "turns in HOT: 3" in rendered


def test_status_handles_missing_files(tmp_path: Path) -> None:
    """Empty workspace should render without crashing."""
    workspace = tmp_path / "empty" / ".claude"
    state = tmp_path / "empty" / "state"
    workspace.mkdir(parents=True)
    state.mkdir(parents=True)
    consumer = _make_consumer(workspace, state)
    rendered = consumer._render_status(chat_id=1)
    assert "status: idle" in rendered
    assert "(missing)" in rendered


# ---------------------------------------------------------------------------
# /reset + /new — graceful (default) saves handoff before kill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graceful_reset_writes_handoff_first(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    # Establish a session so reset has something to clear.
    consumer.sessions.get_or_create("test", 1)

    msg = IncomingMessage(
        chat_id=1, user_id=2, message_id=3, thread_id=None,
        text="/reset", is_oob=True, oob_command="/reset",
    )
    await consumer._handle_oob(msg)

    handoff = workspace / "core" / "hot" / "handoff.md"
    assert handoff.is_file(), "graceful /reset must write handoff.md"
    body = handoff.read_text()
    assert "# Handoff" in body
    # All three seeded entries should be in the handoff.
    assert "**User:** hi" in body
    assert "**User:** more" in body
    assert "**User:** another" in body

    # Session should be cleared.
    assert consumer.sessions.get("test", 1) is None

    # Bot reply mentions handoff.
    sent = consumer.bot.send_message.call_args.kwargs["text"]
    assert "handoff saved" in sent or "handoff" in sent


@pytest.mark.asyncio
async def test_reset_force_skips_handoff(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    consumer.sessions.get_or_create("test", 1)

    msg = IncomingMessage(
        chat_id=1, user_id=2, message_id=3, thread_id=None,
        text="/reset force", is_oob=True, oob_command="/reset",
    )
    await consumer._handle_oob(msg)

    handoff = workspace / "core" / "hot" / "handoff.md"
    # Force path should NOT have written handoff (file may pre-exist as empty
    # but in our seed it didn't, so absence here = test passed).
    assert not handoff.is_file(), "/reset force must not write handoff.md"

    sent = consumer.bot.send_message.call_args.kwargs["text"]
    assert "force" in sent
    assert "skip" in sent.lower()


@pytest.mark.asyncio
async def test_new_command_equals_graceful_reset(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    consumer.sessions.get_or_create("test", 1)

    msg = IncomingMessage(
        chat_id=1, user_id=2, message_id=3, thread_id=None,
        text="/new", is_oob=True, oob_command="/new",
    )
    await consumer._handle_oob(msg)

    # /new must have written handoff just like graceful /reset.
    assert (workspace / "core" / "hot" / "handoff.md").is_file()
    assert consumer.sessions.get("test", 1) is None


@pytest.mark.asyncio
async def test_graceful_reset_appends_breadcrumb_to_memory(tmp_path: Path) -> None:
    workspace, state = _seed_workspace(tmp_path)
    consumer = _make_consumer(workspace, state)
    consumer.sessions.get_or_create("test", 1)

    msg = IncomingMessage(
        chat_id=1, user_id=2, message_id=3, thread_id=None,
        text="/reset", is_oob=True, oob_command="/reset",
    )
    await consumer._handle_oob(msg)

    memory_text = (workspace / "core" / "MEMORY.md").read_text()
    assert "(session ended)" in memory_text
    assert "handed off" in memory_text


@pytest.mark.asyncio
async def test_reset_with_empty_recent_replies_skipped(tmp_path: Path) -> None:
    """If recent.md has no entries, handoff is skipped but session still resets."""
    wsp_root = tmp_path / "wsp"
    workspace = wsp_root / ".claude"
    state = wsp_root / "state"
    (workspace / "core" / "hot").mkdir(parents=True)
    state.mkdir(parents=True)
    (workspace / "core" / "hot" / "recent.md").write_text("# HOT\n")  # no entries

    consumer = _make_consumer(workspace, state)
    consumer.sessions.get_or_create("test", 1)

    msg = IncomingMessage(
        chat_id=1, user_id=2, message_id=3, thread_id=None,
        text="/reset", is_oob=True, oob_command="/reset",
    )
    await consumer._handle_oob(msg)

    sent = consumer.bot.send_message.call_args.kwargs["text"]
    assert "empty session" in sent or "skipped" in sent
    # Session still cleared.
    assert consumer.sessions.get("test", 1) is None
