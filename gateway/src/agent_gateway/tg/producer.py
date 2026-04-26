"""Aiogram dispatcher and producer — long-poll → asyncio.Queue per agent.

OOB commands (``/stop``, ``/cancel``, ``/status``, ``/reset``, ``/new``) are
intercepted here BEFORE queueing so they take effect immediately while a
long-running ``claude`` subprocess is in flight.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from agent_gateway.consumer import AgentConsumer, IncomingMessage
from agent_gateway.tg.group import is_addressed_to_agent
from agent_gateway.tg.voice import VoiceTranscriber

log = logging.getLogger(__name__)

OOB_COMMANDS = frozenset({"/stop", "/cancel", "/status", "/reset", "/new"})


def build_router(
    consumer: AgentConsumer,
    allowed_user_ids: set[int],
    transcriber: VoiceTranscriber | None = None,
    allowed_group_ids: set[int] | None = None,
) -> Router:
    """Build a router for one agent with all message handlers wired up."""
    allowed_group_ids = allowed_group_ids or set()
    router = Router(name=f"router-{consumer.name}")
    bot_username = consumer.cfg.bot_username

    # OOB handlers — registered BEFORE the catch-all so they win the match.
    for cmd in OOB_COMMANDS:
        bare = cmd.lstrip("/")

        @router.message(Command(bare), flags={"oob": True, "cmd": cmd})
        async def _oob_handler(message: Message, **_: Any) -> None:
            await _enqueue_oob(message, consumer, message.text or "")

    @router.message(F.voice)
    async def _voice_handler(message: Message) -> None:
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        if transcriber is None:
            log.info("[%s] voice received but no transcriber configured", consumer.name)
            return
        text = await transcriber.transcribe_voice(consumer.bot, message.voice.file_id)
        if not text:
            log.warning("[%s] voice transcription failed", consumer.name)
            return
        await consumer.queue.put(_make_msg(message, text))

    @router.message(F.text)
    async def _text_handler(message: Message) -> None:
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        await consumer.queue.put(_make_msg(message, message.text or ""))

    return router


def _accept(
    message: Message,
    allowed_user_ids: set[int],
    allowed_group_ids: set[int],
    consumer: AgentConsumer,
    bot_username: str | None,
) -> bool:
    if not _allowed(message, allowed_user_ids):
        return False

    chat_type = message.chat.type
    if chat_type in ("group", "supergroup", "channel"):
        if allowed_group_ids and message.chat.id not in allowed_group_ids:
            return False
        return is_addressed_to_agent(consumer.name, consumer.cfg, message, bot_username)
    return True


def _make_msg(message: Message, text: str, *, oob: bool = False, cmd: str = "") -> IncomingMessage:
    return IncomingMessage(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        message_id=message.message_id,
        thread_id=message.message_thread_id,
        text=text,
        is_oob=oob,
        oob_command=cmd,
    )


async def _enqueue_oob(message: Message, consumer: AgentConsumer, raw_text: str) -> None:
    cmd = raw_text.split()[0].lower() if raw_text else ""
    if cmd not in OOB_COMMANDS:
        return
    # OOB messages skip the user allowlist check on purpose: if the queue is
    # backed up with a long task, the operator must always be able to /stop it.
    msg = _make_msg(message, raw_text, oob=True, cmd=cmd)
    # Producer thread short-circuit: handle OOB inline rather than queueing.
    await consumer._handle_oob(msg)  # noqa: SLF001 — intentional fast path


def _allowed(message: Message, allowed_user_ids: set[int]) -> bool:
    if not allowed_user_ids:
        return True
    if not message.from_user:
        return False
    return message.from_user.id in allowed_user_ids


def attach_to_dispatcher(dp: Dispatcher, bot: Bot, router: Router) -> None:
    """Bind a per-agent Bot instance + Router to the shared Dispatcher."""
    dp.include_router(router)
    # aiogram v3 supports multi-bot polling via Dispatcher.start_polling(*bots).
    # We track the bots list outside; the actual call lives in __main__.py.
    if not hasattr(dp, "_bots"):
        dp._bots: list[Bot] = []  # type: ignore[attr-defined]
    dp._bots.append(bot)  # type: ignore[attr-defined]
