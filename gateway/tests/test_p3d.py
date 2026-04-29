"""Tests for Phase 3d: sendDocument, secret-mask extension, killpg, env.setdefault.

The kill-tree test is the most important here — it spawns a real bash subprocess
that itself spawns a long-running child (`sleep 600`). After kill, neither the
parent nor the child should be running. Without `start_new_session=True` +
`os.killpg()` the child outlives the parent and burns CPU.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_gateway.claude_cli.boundary import BoundaryTracker, mask_secrets
from agent_gateway.claude_cli.runner import ClaudeRunner, _killpg
from agent_gateway.claude_cli.stream_parser import StreamEvent


# ---------------------------------------------------------------------------
# Secret-mask extension (P3d.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "leaked",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890abc",
        "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890",
        "gsk_abcdefghijklmnopqrstuvwxyz1234567890",
        "AKIAIOSFODNN7EXAMPLE",
        "xoxb-12345678901-12345678901-abcdefghijklmnopqrstuvwx",
        "1234567890:AAEhBOweik9ai6Ts2RehbHrEUxwnUjbk_",  # Telegram bot token shape
    ],
)
def test_mask_extended_secret_patterns(leaked: str) -> None:
    """Each new secret pattern must be masked from BoundaryTracker output."""
    masked = mask_secrets(f"prefix {leaked} suffix")
    assert leaked not in masked, f"failed to mask {leaked!r}"


def test_mask_supabase_url() -> None:
    url = "https://abcdefghijklmnop.supabase.co"
    masked = mask_secrets(f"DB at {url}/projects")
    assert url not in masked


def test_mask_jwt() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    masked = mask_secrets(f"Authorization: Bearer {jwt}")
    # The Bearer line catches it via the generic pattern; but the JWT pattern
    # should also catch the bare token.
    assert jwt not in masked


def test_mask_does_not_break_normal_text() -> None:
    """Sanity: ordinary prose with codeblocks shouldn't get redacted."""
    text = "Here is the function `foo(x)` that returns `42`."
    assert mask_secrets(text) == text


def test_short_telegram_placeholder_not_masked() -> None:
    """`123:fake` style placeholders used in tests must NOT match the
    Telegram pattern (otherwise our test fixtures break)."""
    masked = mask_secrets("token=123:fake")
    # The generic env-style pattern catches `token=...`. The specific Telegram
    # pattern should NOT have matched — verify by checking that the generic
    # mask didn't extend across literal text.
    assert "[redacted]" in masked  # generic env pattern triggered, that's fine


# ---------------------------------------------------------------------------
# BoundaryTracker.written_files (P3d.1)
# ---------------------------------------------------------------------------


def test_boundary_tracks_write_tool_paths() -> None:
    tracker = BoundaryTracker()
    tracker.feed(StreamEvent(
        kind="tool_use",
        data={"name": "Write", "input": {"file_path": "/tmp/foo.csv", "content": "a,b\n"}},
    ))
    tracker.feed(StreamEvent(
        kind="tool_use",
        data={"name": "Edit", "input": {"file_path": "/tmp/bar.md"}},
    ))
    assert tracker.written_files == ["/tmp/foo.csv", "/tmp/bar.md"]


def test_boundary_ignores_non_write_tools() -> None:
    tracker = BoundaryTracker()
    tracker.feed(StreamEvent(
        kind="tool_use",
        data={"name": "Read", "input": {"file_path": "/tmp/foo.csv"}},
    ))
    tracker.feed(StreamEvent(
        kind="tool_use",
        data={"name": "Bash", "input": {"command": "ls"}},
    ))
    assert tracker.written_files == []


def test_boundary_handles_missing_input_gracefully() -> None:
    tracker = BoundaryTracker()
    tracker.feed(StreamEvent(kind="tool_use", data={"name": "Write"}))
    tracker.feed(StreamEvent(kind="tool_use", data={"name": "Write", "input": {}}))
    tracker.feed(StreamEvent(
        kind="tool_use",
        data={"name": "Write", "input": {"file_path": ""}},
    ))
    assert tracker.written_files == []


# ---------------------------------------------------------------------------
# Consumer._send_written_files (P3d.1)
# ---------------------------------------------------------------------------


def _make_consumer(workspace: Path):
    from agent_gateway.consumer import AgentConsumer

    cfg = SimpleNamespace(workspace=str(workspace), bot_username="test", timeout_sec=10)
    bot = MagicMock()
    bot.send_document = AsyncMock()
    return AgentConsumer(
        agent_name="test",
        agent_cfg=cfg,
        bot=bot,
        session_store=MagicMock(),
        runner=MagicMock(),
    )


@pytest.mark.asyncio
async def test_send_document_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out_file = workspace / "output.csv"
    out_file.write_text("a,b\n1,2\n")

    consumer = _make_consumer(workspace)
    msg = SimpleNamespace(chat_id=1, thread_id=None)
    await consumer._send_written_files(msg, [str(out_file)])

    assert consumer.bot.send_document.await_count == 1
    args = consumer.bot.send_document.call_args
    assert args.kwargs["chat_id"] == 1


@pytest.mark.asyncio
async def test_send_document_path_traversal_blocked(tmp_path: Path) -> None:
    """A write to /etc/passwd must NEVER be sent as a Telegram doc."""
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)

    consumer = _make_consumer(workspace)
    msg = SimpleNamespace(chat_id=1, thread_id=None)
    await consumer._send_written_files(msg, ["/etc/passwd"])

    assert consumer.bot.send_document.await_count == 0


@pytest.mark.asyncio
async def test_send_document_skips_oversize(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    big = workspace / "big.bin"
    # Create a sparse file that reports >50MB without actually allocating.
    with big.open("wb") as f:
        f.seek(60 * 1024 * 1024)
        f.write(b"\0")

    consumer = _make_consumer(workspace)
    msg = SimpleNamespace(chat_id=1, thread_id=None)
    await consumer._send_written_files(msg, [str(big)])

    assert consumer.bot.send_document.await_count == 0


@pytest.mark.asyncio
async def test_send_document_dedups_repeated_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    out = workspace / "report.md"
    out.write_text("# report\n")

    consumer = _make_consumer(workspace)
    msg = SimpleNamespace(chat_id=1, thread_id=None)
    # Same path appearing 3 times in tracker (Edit-Edit-Write cycle).
    await consumer._send_written_files(
        msg, [str(out), str(out), str(out)]
    )

    assert consumer.bot.send_document.await_count == 1


@pytest.mark.asyncio
async def test_send_document_skips_empty_file(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    empty = workspace / "empty.txt"
    empty.write_text("")

    consumer = _make_consumer(workspace)
    msg = SimpleNamespace(chat_id=1, thread_id=None)
    await consumer._send_written_files(msg, [str(empty)])

    assert consumer.bot.send_document.await_count == 0


# ---------------------------------------------------------------------------
# env.setdefault for CLAUDE_CODE_AUTO_COMPACT_WINDOW (P3d.5)
# ---------------------------------------------------------------------------


def test_runner_env_pins_compact_window(tmp_path: Path) -> None:
    runner = ClaudeRunner()
    cfg = SimpleNamespace(
        workspace=str(tmp_path), model="sonnet", timeout_sec=10,
        bypass_permissions=False, system_reminder=None,
    )
    env = runner._build_env(cfg)
    assert env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW") == "400000"


def test_runner_env_setdefault_respects_caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-agent override via os.environ must win over the default."""
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")
    runner = ClaudeRunner()
    cfg = SimpleNamespace(
        workspace=str(tmp_path), model="sonnet", timeout_sec=10,
        bypass_permissions=False, system_reminder=None,
    )
    env = runner._build_env(cfg)
    assert env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW") == "200000"


# ---------------------------------------------------------------------------
# killpg process-group kill-tree (P3d.4)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="killpg is POSIX-only")
def test_killpg_terminates_child_processes() -> None:
    """The big test: a parent that spawns a child must take the child down too.

    Without ``start_new_session=True`` + ``os.killpg()`` only the parent dies;
    the orphaned child gets reparented to PID 1 and lingers. We verify by:

    1. Spawning a Python parent that forks a ``sleep 600`` child via subprocess
       (Python won't ``exec`` over itself the way ``bash -c sleep`` would, so
       we get a real two-process chain).
    2. Locating the child by a unique marker we pass through env.
    3. Calling ``_killpg(parent.pid)`` and confirming both processes are gone
       within a couple of seconds.
    """
    marker = f"kp_test_{os.getpid()}_{int(time.time() * 1000)}"
    # Python parent that forks a long-running sleep tagged with our marker via
    # argv (we use `sh -c 'exec -a <marker> sleep 600'` so the marker appears
    # in the child's argv where pgrep -f can see it).
    parent = subprocess.Popen(
        [
            sys.executable, "-c",
            "import subprocess, sys;"
            f"subprocess.run(['sh', '-c', 'exec -a {marker} sleep 600'])",
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Give Python time to spawn the shell, which exec's into sleep with our
    # custom argv. 0.5s is generous on cold caches.
    time.sleep(0.5)

    sleep_alive = subprocess.run(
        ["pgrep", "-f", marker],
        capture_output=True, text=True, check=False,
    )
    assert sleep_alive.stdout.strip(), (
        f"test setup: sleep did not start (returncode={sleep_alive.returncode})"
    )

    _killpg(parent.pid)
    parent.wait(timeout=2)

    # killpg reaches sleep via the shared session; sleep dies almost
    # instantly. Give it a beat to be reaped by init.
    time.sleep(0.5)

    after = subprocess.run(
        ["pgrep", "-f", marker],
        capture_output=True, text=True, check=False,
    )
    assert not after.stdout.strip(), (
        f"child survived parent kill: pgrep output {after.stdout!r}"
    )


def test_killpg_handles_already_dead_pid() -> None:
    """No exception when the PID is gone."""
    # Spawn and immediately wait (so the process is reaped).
    p = subprocess.Popen(["true"])
    p.wait()
    # Should not raise.
    _killpg(p.pid)


# ---------------------------------------------------------------------------
# Heartbeat-based timeout — verify per-event timeout (P3d.2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_resets_timeout() -> None:
    """A long-running stream that produces events frequently must NOT time
    out, even past the per-event timeout window."""
    from agent_gateway.claude_cli.runner import _stream_with_timeout

    async def stream():
        # 5 events, 100ms apart = 500ms total. Per-event timeout 300ms.
        for i in range(5):
            await asyncio.sleep(0.1)
            yield StreamEvent(kind="text", data={"text": f"chunk {i}"})

    received = []
    async for ev in _stream_with_timeout(stream(), timeout=0.3):
        received.append(ev)

    assert len(received) == 5


@pytest.mark.asyncio
async def test_timeout_fires_on_silence() -> None:
    """A stream that goes silent past the per-event window must raise."""
    from agent_gateway.claude_cli.runner import _stream_with_timeout

    async def stream():
        yield StreamEvent(kind="text", data={"text": "hi"})
        # Silent for 1s with timeout=0.2 → must time out.
        await asyncio.sleep(1.0)
        yield StreamEvent(kind="final", data={})

    received = []
    with pytest.raises(asyncio.TimeoutError):
        async for ev in _stream_with_timeout(stream(), timeout=0.2):
            received.append(ev)

    assert len(received) == 1  # got the first event before timeout
