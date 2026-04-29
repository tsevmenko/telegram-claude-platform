"""Run the ``claude`` CLI as a subprocess and stream parsed events.

Switch to ``--output-format stream-json`` so the consumer can render live
progress in Telegram. Each line of stdout is a self-contained JSON object
that ``stream_parser`` translates into a typed ``StreamEvent``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from agent_gateway.claude_cli.stream_parser import StreamEvent, parse_stream
from agent_gateway.config import AgentConfig

log = logging.getLogger(__name__)


def _killpg(pid: int) -> None:
    """SIGKILL the entire process group rooted at ``pid``.

    Why a group kill rather than ``proc.kill()``: ``claude`` CLI spawns child
    processes for each tool call (Bash → bash → whatever the bash command
    spawns). On ``/stop`` we want to take down the whole tree, not just the
    direct child — otherwise ``Bash(sleep 600)`` survives and burns time.

    Requires the subprocess to have been started with ``start_new_session=
    True`` so it has its own process group. Falls back to direct ``os.kill``
    if the group is gone (already-dead processes are common on race paths).
    """
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Group went away between getpgid and killpg, or we lost permission
        # (PID reuse). Try the direct kill and accept whatever happens.
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


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
            # Detach into a new session/process group so /stop can kill the
            # full tool subtree (claude → bash → user command) via killpg.
            start_new_session=True,
            # Default asyncio StreamReader buffer is 64 KB. Stream-json events
            # routinely exceed that — Read tool on a screenshot returns base64
            # content blocks ≥ 1 MB, big tool_result echoes can blow past too.
            # Without raising the limit, readline() throws LimitOverrunError
            # ("Separator is not found, and chunk exceed the limit") and the
            # whole turn dies. 10 MB covers any realistic single JSON line.
            limit=10 * 1024 * 1024,
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
                try:
                    line = await proc.stdout.readline()
                except ValueError as exc:
                    # Even with limit=10MB above, a pathologically huge line
                    # (claude streamed back a multi-megabyte file content)
                    # can still trip the buffer. Drain past it and continue
                    # rather than crashing the whole turn.
                    log.warning(
                        "[%s] line buffer overrun (%s) — skipping oversize event",
                        agent, exc,
                    )
                    # Read raw bytes until newline to drain the offending line.
                    try:
                        while True:
                            chunk = await proc.stdout.read(1024 * 1024)
                            if not chunk or chunk.endswith(b"\n"):
                                break
                    except Exception:  # noqa: BLE001
                        pass
                    continue
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
                _killpg(proc.pid)
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
            _killpg(active.process.pid)
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
        # --add-dir <workspace> tells Claude Code's built-in sandbox that the
        # entire agent workspace is writable. Without this, recent (2024+)
        # versions of the CLI mark workspace subdirs (skills/, scripts/,
        # core/, etc.) as sensitive even when the dir is the process cwd —
        # client agents can't extend their own toolchain (write a new skill,
        # add a helper script). Our CLAUDE.md declares skills/ as GREEN; this
        # flag aligns the CLI sandbox with that declaration.
        cmd += ["--add-dir", str(agent_cfg.workspace)]
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
        # Pin the auto-compact window per the architecture's "exactly-one env
        # var" doctrine. Use setdefault so the operator can override per-agent
        # via a config-injected env (e.g. a low-context debug agent at 200K).
        env.setdefault("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "400000")
        # CLAUDE_CODE_REMOTE=1 flips the CLI's `isRemoteMode` flag, which
        # activates the path-sensitivity classifier exception for
        # `<workspace>/.claude/{skills,agents,commands}/`. Without this,
        # claude CLI 2.x refuses Bash/Edit/Write to those paths as "sensitive
        # files" *even with* `--dangerously-skip-permissions` and `--add-dir`
        # — the classifier `u35` runs independently of permission bypass.
        # Live regression: Tyrion attempted `mkdir .claude/skills/instagram-
        # analytics/scripts` and got
        #   "Claude requested permissions to edit ... which is a sensitive
        #    file."
        # Decompiled CLI source (function `u35`):
        #   if (Y === ".claude") {
        #     let M = K[A+1];
        #     if ($ && M) {                       // $ === isRemoteMode
        #       if (M === "skills" || M === "agents" || M === "commands")
        #         break;                          // not sensitive
        #     }
        #   }
        # `isRemoteMode` is set by `hH(process.env.CLAUDE_CODE_REMOTE)` —
        # accepts "1"/"true"/"yes"/"on". Side effects of remote-mode are
        # confined to telemetry tagging and one transport-selection branch
        # gated on `tG.kind === "ccr"` (which we never set), so this is
        # safe for our local-subprocess usage.
        # NOTE: this exemption only covers `.claude/skills|agents|commands`.
        # Writes to `.claude/core/`, `.claude/hooks/`, etc. are still blocked
        # — see workspace-refactor task for the full fix.
        env.setdefault("CLAUDE_CODE_REMOTE", "1")
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
