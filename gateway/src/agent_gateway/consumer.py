"""Per-agent message consumer — pulls from queue, runs claude, replies live."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

from pathlib import Path

from agent_gateway.claude_cli.boundary import BoundaryTracker
from agent_gateway.claude_cli.runner import ClaudeRunner
from agent_gateway.claude_cli.session import SessionStore
from agent_gateway.config import AgentConfig
from agent_gateway.memory.cold import context_bridge_preamble
from agent_gateway.memory.hot import append_turn as hot_append_turn
from agent_gateway.memory.l4_openviking import L4OpenViking
from agent_gateway.tg.buttons import build_keyboard, extract_buttons
from agent_gateway.tg.renderer import (
    EditRateLimiter,
    escape_html,
    markdown_to_telegram_html,
    truncate_for_telegram,
)

log = logging.getLogger(__name__)

INITIAL_STATUS_HTML = "<i>working — 0s</i>"


def _is_parse_error(exc: TelegramBadRequest) -> bool:
    """Detect Telegram's 'can't parse entities' family of errors.

    These come from malformed HTML in our markdown→HTML rendering. The fix is
    always the same: drop ``parse_mode`` and resend as plain text. Other
    `TelegramBadRequest` variants (rate-limit, message-not-modified, no-such-
    chat) should NOT be retried with this strategy.
    """
    msg = (str(exc) or "").lower()
    return (
        "can't parse entities" in msg
        or "can't find end of the entity" in msg
        or "unsupported start tag" in msg
        or "unmatched end tag" in msg
    )


@dataclass
class IncomingMessage:
    chat_id: int
    user_id: int
    message_id: int
    thread_id: int | None
    text: str
    is_oob: bool = False
    oob_command: str = ""
    # Source tag passed through to HOT memory. Producer sets this based on
    # how the message arrived: "tg-text", "tg-voice", "forwarded", "replied",
    # "webhook". Defaults to "tg-text".
    source: str = "tg-text"


class AgentConsumer:
    def __init__(
        self,
        agent_name: str,
        agent_cfg: AgentConfig,
        bot: Bot,
        session_store: SessionStore,
        runner: ClaudeRunner,
        l4: L4OpenViking | None = None,
    ) -> None:
        self.name = agent_name
        self.cfg = agent_cfg
        self.bot = bot
        self.sessions = session_store
        self.runner = runner
        self.l4 = l4
        self.queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
        self.rate_limiter = EditRateLimiter()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._consume_loop(), name=f"consumer-{self.name}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _consume_loop(self) -> None:
        while True:
            msg = await self.queue.get()
            try:
                await self._handle(msg)
            except Exception:
                log.exception("[%s] handler crashed for chat %s", self.name, msg.chat_id)

    async def _handle(self, msg: IncomingMessage) -> None:
        if msg.is_oob:
            await self._handle_oob(msg)
            return

        sid, new_session = self.sessions.get_or_create(self.name, msg.chat_id)
        # Always log thread_id — this is how the operator (or Vesna admin) can
        # discover topic IDs without resorting to Telegram Desktop / web URL.
        log.info(
            "[%s] chat=%s thread=%s sid=%s new=%s",
            self.name, msg.chat_id, msg.thread_id, sid, new_session,
        )

        # On a fresh session, prepend a context bridge from the most recent
        # COLD memory section so /reset doesn't mean total amnesia.
        user_text = msg.text
        if new_session:
            preamble = context_bridge_preamble(Path(self.cfg.workspace))
            if preamble:
                user_text = preamble + user_text

        # 1. React with eyes emoji to ack receipt.
        await self._ack(msg)

        # 2. Send placeholder status message that we'll edit live.
        status_msg = await self.bot.send_message(
            chat_id=msg.chat_id,
            message_thread_id=msg.thread_id,
            text=INITIAL_STATUS_HTML,
            parse_mode=ParseMode.HTML,
        )

        tracker = BoundaryTracker(started_at=time.time())
        last_render = ""

        try:
            async for event in self.runner.stream_turn(
                agent=self.name,
                agent_cfg=self.cfg,
                chat_id=msg.chat_id,
                sid=sid,
                new_session=new_session,
                user_text=user_text,
            ):
                tracker.feed(event)

                if event.kind == "final":
                    break

                # Throttle live edits to one per EDIT_INTERVAL_SEC.
                if not self.rate_limiter.should_edit(msg.chat_id, status_msg.message_id):
                    continue
                rendered = tracker.render_status()
                if rendered == last_render:
                    continue
                last_render = rendered
                await self._edit_status(status_msg, rendered)
        except Exception as exc:
            log.exception("[%s] stream crashed", self.name)
            await self._replace_with_error(status_msg, str(exc))
            return

        final_text = tracker.render_final()
        await self._finalise(status_msg, msg, final_text)
        # Auto-send any files the agent wrote with Write/Edit. Path-traversal
        # guard: only files inside the workspace ship; absolute paths outside
        # (e.g. `/etc/passwd`) are silently skipped to avoid exfiltration.
        await self._send_written_files(msg, tracker.written_files)
        # Persist HOT journal turn — never blocks reply (already sent above).
        await asyncio.to_thread(
            hot_append_turn,
            Path(self.cfg.workspace),
            self.name,
            msg.text,
            final_text,
            msg.source,
        )

        # Fire-and-forget L4 push (bounded executor — never blocks).
        if self.l4 is not None:
            self.l4.push(self.name, msg.chat_id, msg.text, final_text, msg.source)

    async def _handle_oob(self, msg: IncomingMessage) -> None:
        cmd = msg.oob_command
        # Honour /reset force (split on whitespace from raw text) — author's
        # graceful-default pattern: bare /reset writes a handoff first; only
        # `/reset force` matches the v1 instant-kill behaviour.
        is_force = bool(msg.text and "force" in msg.text.split()[1:])

        if cmd in ("/stop", "/cancel"):
            killed = await self.runner.kill(self.name, msg.chat_id)
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text="stopped." if killed else "nothing to stop.",
            )
        elif cmd == "/status":
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text=self._render_status(msg.chat_id),
            )
        elif cmd == "/reset":
            if is_force:
                # Instant kill, no handoff. v1 behaviour preserved.
                await self.runner.kill(self.name, msg.chat_id)
                self.sessions.reset(self.name, msg.chat_id)
                await self.bot.send_message(
                    chat_id=msg.chat_id,
                    message_thread_id=msg.thread_id,
                    text="session force-reset. handoff skipped.",
                )
            else:
                summary = self._save_handoff(msg.chat_id)
                await self.runner.kill(self.name, msg.chat_id)
                self.sessions.reset(self.name, msg.chat_id)
                await self.bot.send_message(
                    chat_id=msg.chat_id,
                    message_thread_id=msg.thread_id,
                    text=f"session reset. {summary}",
                )
        elif cmd == "/new":
            # /new = graceful reset.
            summary = self._save_handoff(msg.chat_id)
            await self.runner.kill(self.name, msg.chat_id)
            self.sessions.reset(self.name, msg.chat_id)
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text=f"new session started. {summary}",
            )
        elif cmd == "/compact":
            reply = await self._run_compact()
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text=reply,
            )

    def _render_status(self, chat_id: int) -> str:
        """Render multi-line status block for /status."""
        wsp = Path(self.cfg.workspace)
        active = (self.name, chat_id) in self.runner.active
        state = "working" if active else "idle"

        # File sizes for the four memory layers.
        sizes: list[str] = []
        for label, rel in (
            ("rules.md", "core/rules.md"),
            ("decisions.md", "core/warm/decisions.md"),
            ("recent.md", "core/hot/recent.md"),
            ("MEMORY.md", "core/MEMORY.md"),
        ):
            p = wsp / rel
            if p.is_file():
                size_kb = p.stat().st_size / 1024
                sizes.append(f"  {label:<14}{size_kb:>6.1f} KB")
            else:
                sizes.append(f"  {label:<14}(missing)")

        # Session age + turn count.
        sid_path = self.sessions.path_for(self.name, chat_id)
        age_line = "  session: (none)"
        if sid_path.is_file():
            import time

            age_sec = max(0.0, time.time() - sid_path.stat().st_mtime)
            hours = int(age_sec // 3600)
            mins = int((age_sec % 3600) // 60)
            sid = sid_path.read_text(encoding="utf-8").strip()[:8]
            age_line = f"  session: {sid}… (age {hours}h {mins}m)"

        recent_path = wsp / "core" / "hot" / "recent.md"
        if recent_path.is_file():
            text = recent_path.read_text(encoding="utf-8", errors="replace")
            turns = sum(1 for ln in text.splitlines() if ln.startswith("### "))
        else:
            turns = 0

        lines = [
            f"status: {state}",
            age_line,
            f"  turns in HOT: {turns}",
            "memory:",
            *sizes,
        ]
        return "\n".join(lines)

    def _save_handoff(self, chat_id: int) -> str:
        """Save a session handoff before /reset destroys the session.

        Strategy:
        - Take the last ~10 entries from recent.md (those are 'this session'
          since last cron rotation), copy into hot/handoff.md (overwriting).
        - Append a date-stamped section to MEMORY.md so the next session can
          discover what happened in the last one.

        Cheap and offline — does not invoke claude. The author's gateway uses
        Sonnet for richer summaries; we get most of the benefit at zero cost
        and zero latency by just preserving the raw entries.

        Returns a short status string for the operator reply.
        """
        wsp = Path(self.cfg.workspace)
        recent = wsp / "core" / "hot" / "recent.md"
        handoff = wsp / "core" / "hot" / "handoff.md"
        memory = wsp / "core" / "MEMORY.md"

        if not recent.is_file():
            return "(no recent.md — handoff skipped)"

        text = recent.read_text(encoding="utf-8", errors="replace")
        # Find the last ~10 entries: split on `### ` headers (which start each
        # turn block), keep the trailing 10.
        blocks: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if line.startswith("### "):
                if current:
                    blocks.append("\n".join(current))
                current = [line]
            elif current:
                current.append(line)
        if current:
            blocks.append("\n".join(current))

        last_10 = blocks[-10:] if blocks else []
        if not last_10:
            return "(empty session — handoff skipped)"

        import time

        ts = time.strftime("%Y-%m-%d %H:%M")
        try:
            handoff.parent.mkdir(parents=True, exist_ok=True)
            handoff.write_text(
                f"# Handoff (saved {ts})\n\n" + "\n\n".join(last_10) + "\n",
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            log.exception("[%s] failed to write handoff.md", self.name)
            return "(handoff write failed — see logs)"

        # Append a one-line breadcrumb to MEMORY.md so the next session has a
        # discoverable trail of when sessions ended.
        try:
            memory.parent.mkdir(parents=True, exist_ok=True)
            with memory.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n## {ts} (session ended)\n"
                    f"- {len(last_10)} entries handed off to handoff.md.\n"
                )
        except Exception:  # noqa: BLE001
            log.exception("[%s] failed to append MEMORY.md", self.name)

        return f"handoff saved ({len(last_10)} entries)."

    async def _run_compact(self) -> str:
        """Trigger trim-hot.sh for this agent's workspace.

        Lives in <wsp_root>/scripts/trim-hot.sh; workspace is <wsp_root>/.claude.
        Returns a short status string for the operator.
        """
        wsp = Path(self.cfg.workspace)
        script = wsp.parent / "scripts" / "trim-hot.sh"
        recent = wsp / "core" / "hot" / "recent.md"

        size_before = recent.stat().st_size if recent.is_file() else 0
        if not script.is_file():
            return f"compact: script not found at {script}"

        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(script),
            env={**__import__("os").environ, "AGENT_WORKSPACE": str(wsp)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()  # collect zombie before we abandon the proc
            except Exception:  # noqa: BLE001
                pass
            return "compact: trim-hot.sh exceeded 120s — killed."

        size_after = recent.stat().st_size if recent.is_file() else 0
        delta_kb = (size_before - size_after) / 1024
        return (
            f"compact done. recent.md: {size_before / 1024:.1f} KB → "
            f"{size_after / 1024:.1f} KB (saved {delta_kb:+.1f} KB)."
        )

    async def _ack(self, msg: IncomingMessage) -> None:
        try:
            from aiogram.types import ReactionTypeEmoji

            await self.bot.set_message_reaction(
                chat_id=msg.chat_id,
                message_id=msg.message_id,
                reaction=[ReactionTypeEmoji(emoji="👀")],
            )
        except Exception:  # noqa: BLE001 — reactions require Bot API 7+; fail soft
            pass

    async def _edit_status(self, status_msg, rendered: str) -> None:
        text = f"<pre>{escape_html(rendered)}</pre>"
        try:
            await self.bot.edit_message_text(
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest as e:
            # On parse-entities errors retry as plain text (drop parse_mode).
            # "message is not modified" / rate-limit / etc. → still swallow.
            if _is_parse_error(e):
                try:
                    await self.bot.edit_message_text(
                        chat_id=status_msg.chat.id,
                        message_id=status_msg.message_id,
                        text=rendered[:4000],
                    )
                except TelegramBadRequest:
                    pass

    async def _finalise(self, status_msg, msg: IncomingMessage, final_text: str) -> None:
        if not final_text:
            await self._edit_status(status_msg, "(no output)")
            return

        # Detect inline button markers, strip them from the visible text.
        cleaned, button_rows = extract_buttons(final_text)
        keyboard = build_keyboard(button_rows)

        html_text = markdown_to_telegram_html(cleaned)
        chunks = truncate_for_telegram(html_text)

        # Replace the live-status message with the first chunk of the answer.
        # Buttons (if any) attach to the LAST chunk so the operator sees them
        # at the bottom of a multi-part reply.
        first_keyboard = keyboard if len(chunks) == 1 else None
        try:
            await self.bot.edit_message_text(
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                text=chunks[0],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=first_keyboard,
            )
        except TelegramBadRequest as e:
            # Two failure modes: (1) status message can't be edited (e.g. too
            # old) — fall back to send_message; (2) HTML parse error — strip
            # parse_mode and retry. Try the parse-error path first since it's
            # cheaper (no extra round-trip).
            if _is_parse_error(e):
                try:
                    await self.bot.edit_message_text(
                        chat_id=status_msg.chat.id,
                        message_id=status_msg.message_id,
                        text=cleaned[:4000],
                        disable_web_page_preview=True,
                        reply_markup=first_keyboard,
                    )
                except TelegramBadRequest:
                    await self.bot.send_message(
                        chat_id=msg.chat_id,
                        message_thread_id=msg.thread_id,
                        text=cleaned[:4000],
                        disable_web_page_preview=True,
                        reply_markup=first_keyboard,
                    )
            else:
                await self.bot.send_message(
                    chat_id=msg.chat_id,
                    message_thread_id=msg.thread_id,
                    text=chunks[0],
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=first_keyboard,
                )

        for i, chunk in enumerate(chunks[1:], start=1):
            is_last = i == len(chunks) - 1
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=keyboard if is_last else None,
            )

    # ------------------------------------------------------------------
    # sendDocument auto-emit
    # ------------------------------------------------------------------

    SEND_DOCUMENT_MAX_BYTES = 50 * 1024 * 1024  # Telegram bot doc limit

    async def _send_written_files(
        self, msg: IncomingMessage, paths: list[str]
    ) -> None:
        """Emit each unique file the agent created via Write/Edit.

        Two safety gates:
        - **Path traversal guard.** Resolved path must be inside the agent's
          workspace. Without this, a malicious or confused turn could
          ``Write /etc/passwd`` and we'd happily ship it.
        - **Size cap.** Telegram rejects bot documents > 50MB. Skip with a log
          warning rather than letting the turn fail.

        Dedup by resolved path so the same file written 3 times in one turn
        ships exactly once.
        """
        if not paths:
            return
        wsp = Path(self.cfg.workspace).resolve()
        sent: set[Path] = set()
        for raw in paths:
            try:
                resolved = Path(raw).resolve()
            except (OSError, ValueError):
                log.warning("[%s] cannot resolve write path: %s", self.name, raw)
                continue
            if resolved in sent:
                continue
            if not resolved.is_file():
                continue
            try:
                if not resolved.is_relative_to(wsp):
                    log.warning(
                        "[%s] refusing to send file outside workspace: %s",
                        self.name, resolved,
                    )
                    continue
            except AttributeError:
                # Python < 3.9 fallback (we require 3.11 but be defensive).
                if not str(resolved).startswith(str(wsp)):
                    continue
            try:
                size = resolved.stat().st_size
            except OSError:
                continue
            if size == 0:
                continue
            if size > self.SEND_DOCUMENT_MAX_BYTES:
                log.warning(
                    "[%s] file %s is %d bytes — too large for Telegram doc",
                    self.name, resolved, size,
                )
                continue
            try:
                await self.bot.send_document(
                    chat_id=msg.chat_id,
                    message_thread_id=msg.thread_id,
                    document=FSInputFile(str(resolved)),
                )
                sent.add(resolved)
            except Exception:  # noqa: BLE001
                log.exception(
                    "[%s] failed to send document %s", self.name, resolved
                )

    async def _replace_with_error(self, status_msg, detail: str) -> None:
        text = f"<i>error: {escape_html(detail[:300])}</i>"
        try:
            await self.bot.edit_message_text(
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest as e:
            if _is_parse_error(e):
                try:
                    await self.bot.edit_message_text(
                        chat_id=status_msg.chat.id,
                        message_id=status_msg.message_id,
                        text=f"error: {detail[:300]}",
                    )
                except TelegramBadRequest:
                    pass
