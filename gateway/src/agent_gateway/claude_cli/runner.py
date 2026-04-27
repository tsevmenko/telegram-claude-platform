"""Run the ``claude`` CLI as a subprocess and stream parsed events.

Switch to ``--output-format stream-json`` so the consumer can render live
progress in Telegram. Each line of stdout is a self-contained JSON object
that ``stream_parser`` translates into a typed ``StreamEvent``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from agent_gateway.claude_cli.stream_parser import StreamEvent, parse_stream
from agent_gateway.config import AgentConfig

log = logging.getLogger(__name__)


@dataclass
class ActiveProc:
    """Tracked subprocess for kill-tree on /stop."""

    process: asyncio.subprocess.Process
    sid: str
    chat_id: int
    agent: str
    started_at: float = field(default_factory=lambda: 0.0)


class ClaudeRunner:
    """Spawn ``claude`` CLI per turn. Tracks active processes for kill."""

    def __init__(self, claude_binary: str = "claude") -> None:
        self.claude_binary = claude_binary
        self.active: dict[tuple[str, int], ActiveProc] = {}

    async def stream_turn(
        self,
        agent: str,
        agent_cfg: AgentConfig,
        chat_id: int,
        sid: str,
        new_session: bool,
        user_text: str,
    ) -> AsyncIterator[StreamEvent]:
        """Run a single claude invocation and yield parsed events."""
        cmd = self._build_cmd(agent_cfg, sid, new_session)
        env = self._build_env(agent_cfg)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=agent_cfg.workspace,
            env=env,
        )

        active = ActiveProc(process=proc, sid=sid, chat_id=chat_id, agent=agent)
        self.active[(agent, chat_id)] = active

        # Feed the user message and close stdin so claude knows the prompt is final.
        if proc.stdin:
            proc.stdin.write(user_text.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

        async def _line_iter() -> AsyncIterator[str]:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8", errors="replace")

        try:
            try:
                # Iterate the timeout-wrapping async generator directly.
                # Wrapping it in asyncio.wait_for() would coerce it into a
                # coroutine, which breaks the `async for` protocol — the
                # per-event timeout is already enforced inside
                # _stream_with_timeout.
                async for ev in _stream_with_timeout(
                    parse_stream(_line_iter()), agent_cfg.timeout_sec
                ):
                    yield ev
            except asyncio.TimeoutError:
                proc.kill()
                yield StreamEvent(
                    kind="final",
                    data={
                        "is_error": True,
                        "subtype": "timeout",
                        "text": f"[timeout: agent did not finish in {agent_cfg.timeout_sec}s]",
                    },
                )
        finally:
            self.active.pop((agent, chat_id), None)
            try:
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass
            if proc.returncode and proc.returncode != 0:
                err_text = b""
                if proc.stderr:
                    try:
                        err_text = await proc.stderr.read()
                    except Exception:  # noqa: BLE001
                        pass
                if err_text:
                    log.warning(
                        "[%s] claude exited %s: %s",
                        agent,
                        proc.returncode,
                        err_text.decode("utf-8", errors="replace")[:500],
                    )

    async def kill(self, agent: str, chat_id: int) -> bool:
        active = self.active.get((agent, chat_id))
        if not active:
            return False
        try:
            active.process.kill()
            await active.process.wait()
        except ProcessLookupError:
            pass
        finally:
            self.active.pop((agent, chat_id), None)
        return True

    def _build_cmd(self, agent_cfg: AgentConfig, sid: str, new_session: bool) -> list[str]:
        cmd: list[str] = [
            self.claude_binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if new_session:
            cmd += ["--session-id", sid]
        else:
            cmd += ["--resume", sid]
        cmd += ["--model", agent_cfg.model]
        if agent_cfg.bypass_permissions:
            cmd += ["--dangerously-skip-permissions"]
        if agent_cfg.system_reminder:
            cmd += ["--append-system-prompt", agent_cfg.system_reminder]
        return cmd

    def _build_env(self, agent_cfg: AgentConfig) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("HOME", str(Path(agent_cfg.workspace).parent.parent))
        return env


async def _stream_with_timeout(
    stream: AsyncIterator[StreamEvent], timeout: float
) -> AsyncIterator[StreamEvent]:
    """Wrap an async iterator with a per-call timeout via asyncio.wait_for."""
    while True:
        try:
            ev = await asyncio.wait_for(stream.__anext__(), timeout=timeout)
        except StopAsyncIteration:
            break
        yield ev
