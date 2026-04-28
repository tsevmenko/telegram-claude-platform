"""Tests for Phase 3a UX wins: setMyCommands, HTML parse-error fallback, /compact OOB.

These exercise gateway code paths that are otherwise hard to reach without a
live Telegram connection. We use minimal stubs — full aiogram mocking lives
in `test_smoke.py` / `test_runner.py`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from agent_gateway.consumer import (
    AgentConsumer,
    IncomingMessage,
    _is_parse_error,
)
from agent_gateway.multi_agent import _BOT_COMMANDS
from agent_gateway.tg.producer import OOB_COMMANDS


# ---------------------------------------------------------------------------
# OOB_COMMANDS includes /compact
# ---------------------------------------------------------------------------


def test_compact_is_registered_oob_command() -> None:
    assert "/compact" in OOB_COMMANDS


def test_compact_in_botfather_menu() -> None:
    """The slash-menu shown in BotFather must list /compact."""
    cmds = {c.command for c in _BOT_COMMANDS}
    assert "compact" in cmds
    assert "stop" in cmds
    assert "status" in cmds
    assert "reset" in cmds
    assert "new" in cmds


# ---------------------------------------------------------------------------
# _is_parse_error
# ---------------------------------------------------------------------------


def _make_bad_request(message: str) -> TelegramBadRequest:
    """Construct a TelegramBadRequest cleanly across aiogram versions."""
    err = TelegramBadRequest.__new__(TelegramBadRequest)
    err.message = message
    err.method = MagicMock()
    return err


@pytest.mark.parametrize(
    "msg",
    [
        "Bad Request: can't parse entities: Unsupported start tag \"foo\" at byte offset 12",
        "Bad Request: Can't find end of the entity starting at byte offset 0",
        "Bad Request: Unsupported start tag \"a href\" at byte offset 99",
        "Bad Request: Unmatched end tag at byte offset 50",
    ],
)
def test_is_parse_error_detects_html_failures(msg: str) -> None:
    err = _make_bad_request(msg)
    assert _is_parse_error(err) is True


@pytest.mark.parametrize(
    "msg",
    [
        "Bad Request: message is not modified",
        "Bad Request: chat not found",
        "Too Many Requests: retry after 12",
    ],
)
def test_is_parse_error_ignores_non_html_errors(msg: str) -> None:
    err = _make_bad_request(msg)
    assert _is_parse_error(err) is False


# ---------------------------------------------------------------------------
# /compact OOB integration
# ---------------------------------------------------------------------------


def _make_consumer(workspace: Path) -> AgentConsumer:
    """Build an AgentConsumer with stubbed bot/runner/sessions/l4."""
    cfg = SimpleNamespace(
        workspace=str(workspace),
        bot_username="test_bot",
        timeout_sec=10,
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.set_message_reaction = AsyncMock()
    runner = MagicMock()
    runner.kill = AsyncMock(return_value=False)
    runner.active = {}
    sessions = MagicMock()
    sessions.get_or_create = MagicMock(return_value=("sid-test", True))
    sessions.reset = MagicMock()
    return AgentConsumer(
        agent_name="test",
        agent_cfg=cfg,
        bot=bot,
        session_store=sessions,
        runner=runner,
    )


@pytest.mark.asyncio
async def test_oob_compact_runs_trim_hot_and_reports_size_delta(
    tmp_path: Path,
) -> None:
    """`/compact` must spawn trim-hot.sh, then report size delta to operator.

    We provide a stub trim-hot.sh that truncates recent.md. Real script lives
    in workspace-template/scripts/ but isn't installed in this test setup.
    """
    wsp_root = tmp_path / "wsp"
    workspace = wsp_root / ".claude"
    (workspace / "core" / "hot").mkdir(parents=True)
    (workspace / "core" / "hot" / "recent.md").write_text("a" * 5000)

    scripts = wsp_root / "scripts"
    scripts.mkdir()
    stub = scripts / "trim-hot.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "test" > "{workspace}/core/hot/recent.md"\n'
        "exit 0\n"
    )
    stub.chmod(0o755)

    consumer = _make_consumer(workspace)
    msg = IncomingMessage(
        chat_id=123,
        user_id=456,
        message_id=789,
        thread_id=None,
        text="/compact",
        is_oob=True,
        oob_command="/compact",
    )

    await consumer._handle_oob(msg)

    # Bot received exactly one send_message call with a status string.
    assert consumer.bot.send_message.await_count == 1
    sent = consumer.bot.send_message.call_args
    text = sent.kwargs["text"]
    assert "compact done" in text
    assert "saved" in text
    # Size went from 5000 down to ~5 bytes — must show positive savings.
    assert "+4." in text or "+5." in text


@pytest.mark.asyncio
async def test_oob_compact_reports_missing_script(tmp_path: Path) -> None:
    """If trim-hot.sh isn't planted, report cleanly instead of crashing."""
    wsp_root = tmp_path / "wsp"
    workspace = wsp_root / ".claude"
    (workspace / "core" / "hot").mkdir(parents=True)
    # Intentionally NO scripts/trim-hot.sh.

    consumer = _make_consumer(workspace)
    msg = IncomingMessage(
        chat_id=1,
        user_id=2,
        message_id=3,
        thread_id=None,
        text="/compact",
        is_oob=True,
        oob_command="/compact",
    )

    await consumer._handle_oob(msg)
    text = consumer.bot.send_message.call_args.kwargs["text"]
    assert "compact: script not found" in text


@pytest.mark.asyncio
async def test_oob_compact_kills_runaway_after_timeout(tmp_path: Path) -> None:
    """A trim-hot.sh that hangs forever should be killed at 120s.

    We use a small timeout via monkey-patch for the test.
    """
    wsp_root = tmp_path / "wsp"
    workspace = wsp_root / ".claude"
    (workspace / "core" / "hot").mkdir(parents=True)
    scripts = wsp_root / "scripts"
    scripts.mkdir()
    stub = scripts / "trim-hot.sh"
    stub.write_text("#!/usr/bin/env bash\nsleep 30\n")
    stub.chmod(0o755)

    consumer = _make_consumer(workspace)

    # Patch wait_for to a 0.5s timeout for this test only.
    real_wait_for = asyncio.wait_for

    async def _short_wait(coro: Any, timeout: float) -> Any:
        return await real_wait_for(coro, timeout=0.5)

    msg = IncomingMessage(
        chat_id=1,
        user_id=2,
        message_id=3,
        thread_id=None,
        text="/compact",
        is_oob=True,
        oob_command="/compact",
    )

    import agent_gateway.consumer as cm

    cm.asyncio.wait_for = _short_wait  # type: ignore[assignment]
    try:
        await consumer._handle_oob(msg)
    finally:
        cm.asyncio.wait_for = real_wait_for  # restore

    text = consumer.bot.send_message.call_args.kwargs["text"]
    assert "exceeded" in text or "killed" in text
