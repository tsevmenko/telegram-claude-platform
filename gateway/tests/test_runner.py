"""ClaudeRunner integration smoke tests with a fake claude binary.

Exercises the async streaming pipeline end-to-end without a real Anthropic
API call. Uses a tiny shell script that pretends to be `claude -p
--output-format stream-json` and emits a fixed sequence of events.

The first version of stream_turn() wrapped the timeout-aware async generator
in `asyncio.wait_for(...)` which converts it into a coroutine — and `async
for` on a coroutine raises TypeError at runtime. These tests guard against
that regression.
"""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from agent_gateway.claude_cli.runner import ClaudeRunner, _stream_with_timeout
from agent_gateway.claude_cli.stream_parser import StreamEvent
from agent_gateway.config import AgentConfig


# ---------------------------------------------------------------------------
# Fake claude binary: a shell script that emits stream-json lines.
# ---------------------------------------------------------------------------


FAKE_CLAUDE_SCRIPT = """#!/usr/bin/env bash
# Read stdin (the user prompt) but ignore it; emit a fixed event sequence.
cat >/dev/null
cat <<'EOF'
{"type":"system","subtype":"init","session_id":"sid-test","model":"sonnet","tools":[]}
{"type":"assistant","message":{"content":[{"type":"text","text":"hi from fake"}]}}
{"type":"result","subtype":"success","is_error":false,"result":"hi from fake","duration_ms":42}
EOF
"""


@pytest.fixture
def fake_claude(tmp_path: Path) -> Path:
    binary = tmp_path / "claude"
    binary.write_text(FAKE_CLAUDE_SCRIPT)
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return binary


@pytest.fixture
def agent_cfg(tmp_workspace: Path) -> AgentConfig:
    return AgentConfig(
        enabled=True,
        bot_token="test:fake",
        bot_username="fake_bot",
        workspace=str(tmp_workspace),
        model="sonnet",
        timeout_sec=10,
        bypass_permissions=False,
    )


# ---------------------------------------------------------------------------
# stream_turn end-to-end (must NOT raise TypeError on async for)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_turn_yields_events(fake_claude: Path, agent_cfg: AgentConfig):
    runner = ClaudeRunner(claude_binary=str(fake_claude))
    events: list[StreamEvent] = []
    async for ev in runner.stream_turn(
        agent="vesna",
        agent_cfg=agent_cfg,
        chat_id=42,
        sid="sid-test",
        new_session=True,
        user_text="hi",
    ):
        events.append(ev)

    kinds = [e.kind for e in events]
    # We must see at least one init, one text, and one final — and the bug
    # we hit on production was that NO events were yielded because async-for
    # raised TypeError on a coroutine. This assert is the regression guard.
    assert "init" in kinds, f"missing init in {kinds}"
    assert "final" in kinds, f"missing final in {kinds}"


@pytest.mark.asyncio
async def test_stream_turn_clears_active_proc(fake_claude: Path, agent_cfg: AgentConfig):
    runner = ClaudeRunner(claude_binary=str(fake_claude))
    async for _ in runner.stream_turn(
        agent="vesna", agent_cfg=agent_cfg, chat_id=1,
        sid="x", new_session=True, user_text="hi",
    ):
        pass
    assert ("vesna", 1) not in runner.active


# ---------------------------------------------------------------------------
# _stream_with_timeout is itself a valid async iterator
# ---------------------------------------------------------------------------


async def _gen():
    yield StreamEvent(kind="text", data={"text": "a"})
    yield StreamEvent(kind="text", data={"text": "b"})


@pytest.mark.asyncio
async def test_stream_with_timeout_is_async_iterator():
    out: list[str] = []
    async for ev in _stream_with_timeout(_gen(), timeout=1.0):
        out.append(ev.data.get("text", ""))
    assert out == ["a", "b"]


@pytest.mark.asyncio
async def test_stream_with_timeout_propagates_timeout():
    async def slow():
        await asyncio.sleep(2)
        yield StreamEvent(kind="text", data={"text": "never"})

    with pytest.raises(asyncio.TimeoutError):
        async for _ in _stream_with_timeout(slow(), timeout=0.1):
            pass
