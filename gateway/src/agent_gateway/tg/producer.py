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

OOB_COMMANDS = frozenset({"/stop", "/cancel", "/status", "/reset", "/new", "/compact"})


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
    # Crucially: OOB still has to respect group_id + topic_routing checks,
    # otherwise every bot in the same group answers /status in every topic.
    # User allowlist is intentionally bypassed (operator must always be able
    # to /stop a runaway turn even from a chat we'd otherwise reject).
    for cmd in OOB_COMMANDS:
        bare = cmd.lstrip("/")

        @router.message(Command(bare), flags={"oob": True, "cmd": cmd})
        async def _oob_handler(message: Message, **_: Any) -> None:
            if not _accept_for_oob(
                message, allowed_group_ids, consumer, bot_username
            ):
                return
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
        # Echo the transcript back as italic so the operator sees what we
        # actually heard before the long answer arrives. If Whisper mishears,
        # they can /stop and re-record instead of waiting for a wrong reply.
        await _echo_voice_transcript(consumer.bot, message, text)
        await consumer.queue.put(_make_msg(message, text, source="tg-voice"))

    @router.message(F.text)
    async def _text_handler(message: Message) -> None:
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        # consumer.cfg.bot_user_id is set once at startup via cache_getme().
        self_bot_id = getattr(consumer.cfg, "bot_user_id", None)
        enriched, source = _build_text_with_context(message, self_bot_id=self_bot_id)
        await consumer.queue.put(_make_msg(message, enriched, source=source))

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


def _accept_for_oob(
    message: Message,
    allowed_group_ids: set[int],
    consumer: AgentConsumer,
    bot_username: str | None,
) -> bool:
    """Same as ``_accept`` but skips the user allowlist.

    Rationale: ``/stop`` and ``/cancel`` are panic buttons that must always
    fire regardless of which user typed them in an allowlisted group. Topic
    routing is still enforced — otherwise every bot in the same group
    answers ``/status`` in every topic.
    """
    chat_type = message.chat.type
    if chat_type in ("group", "supergroup", "channel"):
        if allowed_group_ids and message.chat.id not in allowed_group_ids:
            return False
        return is_addressed_to_agent(consumer.name, consumer.cfg, message, bot_username)
    return True


def _make_msg(
    message: Message,
    text: str,
    *,
    oob: bool = False,
    cmd: str = "",
    source: str = "tg-text",
) -> IncomingMessage:
    return IncomingMessage(
        chat_id=message.chat.id,
        user_id=message.from_user.id if message.from_user else 0,
        message_id=message.message_id,
        thread_id=message.message_thread_id,
        text=text,
        is_oob=oob,
        oob_command=cmd,
        source=source,
    )


def _build_text_with_context(
    message: Message, self_bot_id: int | None = None
) -> tuple[str, str]:
    """Build the text the agent sees, prefixed with reply/forward context.

    Returns ``(enriched_text, source_tag)``.

    Reply context: when the operator replies to a non-bot message, the body of
    the replied-to message is injected as ``[Replied message (untrusted
    metadata, for context only):]``. The "untrusted metadata" framing is a
    defence against prompt injection — Claude is trained to treat such tagged
    content as data, not instructions.

    Forward context: when the message is forwarded, the origin is tagged with
    ``[Forwarded from: <name>]`` so the agent treats the body as third-party
    text rather than direct operator input.

    Both can apply at once (forward of a reply). Forward takes priority for
    the source tag because the message body is wholly third-party in that
    case.

    ``self_bot_id``: pass our own ``getMe().id`` so we only skip injection for
    replies to OUR bot (whose output is already in the session history).
    Replies to a different bot in the same group should still inject context.
    Falls back to the broader "any-bot" check if id is None.
    """
    text = message.text or message.caption or ""
    parts: list[str] = []
    source = "tg-text"

    # Forward context. forward_origin is Bot API 7.0+ — use getattr so older
    # aiogram versions / mocks don't crash.
    fwd = getattr(message, "forward_origin", None)
    if fwd is not None:
        origin_name = _forward_origin_name(fwd)
        parts.append(f"[Forwarded from: {origin_name}]")
        source = "forwarded"

    # Reply context. Only inject if the replied-to message is not from our own
    # bot (those are already in the session history) and has non-empty body.
    reply = getattr(message, "reply_to_message", None)
    if reply is not None:
        reply_user = getattr(reply, "from_user", None)
        if self_bot_id is not None and reply_user is not None:
            is_self_reply = getattr(reply_user, "id", None) == self_bot_id
        else:
            # Fallback when getMe id isn't cached yet (very early startup).
            is_self_reply = bool(reply_user and getattr(reply_user, "is_bot", False))
        body = ((reply.text if reply.text is not None else None)
                or getattr(reply, "caption", None)
                or "")
        if not is_self_reply and body.strip():
            # Cap to 500 chars to keep the prompt budget bounded.
            snippet = body.strip()[:500]
            parts.append("[Replied message (untrusted metadata, for context only):]")
            parts.append(snippet)
            parts.append("---")
            if source == "tg-text":
                source = "replied"

    parts.append(text)
    return "\n".join(parts), source


def _forward_origin_name(origin: object) -> str:
    """Best-effort extraction of a human-readable origin name.

    Handles the four MessageOrigin variants from Bot API 7+:
    - MessageOriginUser: real user → ``sender_user.full_name`` or first_name
    - MessageOriginHiddenUser: privacy-mode user → ``sender_user_name``
    - MessageOriginChannel: channel post → ``chat.title``
    - MessageOriginChat: anonymous group admin → ``sender_chat.title``
    """
    sender_user = getattr(origin, "sender_user", None)
    if sender_user is not None:
        return (
            getattr(sender_user, "full_name", None)
            or getattr(sender_user, "first_name", None)
            or "user"
        )
    hidden = getattr(origin, "sender_user_name", None)
    if hidden:
        return hidden
    chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    if chat is not None:
        return getattr(chat, "title", None) or getattr(chat, "username", None) or "channel"
    return "unknown"


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


async def _echo_voice_transcript(bot: Bot, message: Message, text: str) -> None:
    """Send the transcribed voice back to the same chat/thread as italic.

    Trims to 500 chars to avoid creating a wall of text on long monologues.
    Best-effort — failure is logged but doesn't block the agent turn.
    """
    from html import escape as html_escape
    snippet = text.strip()
    if not snippet:
        return
    if len(snippet) > 500:
        snippet = snippet[:497] + "…"
    body = f"<i>🎙 {html_escape(snippet)}</i>"
    try:
        await bot.send_message(
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
            text=body,
            parse_mode="HTML",
            reply_to_message_id=message.message_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("voice transcript echo failed: %s", exc)


def attach_to_dispatcher(dp: Dispatcher, bot: Bot, router: Router) -> None:
    """Bind a per-agent Bot instance + Router to the shared Dispatcher."""
    dp.include_router(router)
    # aiogram v3 supports multi-bot polling via Dispatcher.start_polling(*bots).
    # We track the bots list outside; the actual call lives in __main__.py.
    if not hasattr(dp, "_bots"):
        dp._bots: list[Bot] = []  # type: ignore[attr-defined]
    dp._bots.append(bot)  # type: ignore[attr-defined]
