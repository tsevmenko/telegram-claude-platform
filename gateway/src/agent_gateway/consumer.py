"""Per-agent message consumer — pulls from queue, runs claude, replies live."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

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


@dataclass
class IncomingMessage:
    chat_id: int
    user_id: int
    message_id: int
    thread_id: int | None
    text: str
    is_oob: bool = False
    oob_command: str = ""


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
        # Persist HOT journal turn — never blocks reply (already sent above).
        await asyncio.to_thread(
            hot_append_turn,
            Path(self.cfg.workspace),
            self.name,
            msg.text,
            final_text,
            "tg-text",
        )

        # Fire-and-forget L4 push (bounded executor — never blocks).
        if self.l4 is not None:
            self.l4.push(self.name, msg.chat_id, msg.text, final_text, "tg-text")

    async def _handle_oob(self, msg: IncomingMessage) -> None:
        cmd = msg.oob_command
        if cmd in ("/stop", "/cancel"):
            killed = await self.runner.kill(self.name, msg.chat_id)
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text="stopped." if killed else "nothing to stop.",
            )
        elif cmd == "/status":
            active = (self.name, msg.chat_id) in self.runner.active
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text="working" if active else "idle",
            )
        elif cmd == "/reset":
            await self.runner.kill(self.name, msg.chat_id)
            self.sessions.reset(self.name, msg.chat_id)
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text="session reset. next message starts fresh.",
            )
        elif cmd == "/new":
            self.sessions.reset(self.name, msg.chat_id)
            await self.bot.send_message(
                chat_id=msg.chat_id,
                message_thread_id=msg.thread_id,
                text="new session started.",
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
        except TelegramBadRequest:
            # "message is not modified" or rate-limit — both safe to swallow.
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
        except TelegramBadRequest:
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

    async def _replace_with_error(self, status_msg, detail: str) -> None:
        text = f"<i>error: {escape_html(detail[:300])}</i>"
        try:
            await self.bot.edit_message_text(
                chat_id=status_msg.chat.id,
                message_id=status_msg.message_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except TelegramBadRequest:
            pass
