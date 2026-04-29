"""Aiogram dispatcher and producer — long-poll → asyncio.Queue per agent.

OOB commands (``/stop``, ``/cancel``, ``/status``, ``/reset``, ``/new``) are
intercepted here BEFORE queueing so they take effect immediately while a
long-running ``claude`` subprocess is in flight.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from agent_gateway.consumer import AgentConsumer, IncomingMessage
from agent_gateway.tg.group import is_addressed_to_agent
from agent_gateway.tg.voice import VoiceTranscriber

# Telegram caps bot file downloads at 20 MB. Documents larger than this
# come through with `getFile` returning HTTP 413 — we surface a polite
# "too big" message rather than crashing.
TELEGRAM_BOT_DOWNLOAD_LIMIT = 20 * 1024 * 1024

# Document MIME types we accept by default. Images, plain text, code, JSON,
# CSV, PDF. We deliberately don't accept binary blobs (zip, exe, video) —
# Claude can't do anything useful with them and they fill disk fast.
ACCEPTED_DOC_MIME = {
    "application/pdf",
    "text/plain", "text/markdown", "text/csv", "text/html", "text/x-python",
    "application/json", "application/yaml", "application/x-yaml",
    "application/javascript", "application/typescript",
    "image/png", "image/jpeg", "image/webp", "image/gif",
}

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

    @router.message(F.voice | F.audio | F.video_note)
    async def _audio_handler(message: Message) -> None:
        """Handle voice notes, music/audio uploads, and round video messages.

        All three are run through Groq Whisper. ``video_note`` is the round
        Telegram circle — Whisper accepts the underlying MP4 and pulls audio.
        """
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        if transcriber is None:
            log.info("[%s] audio received but no transcriber configured", consumer.name)
            return

        # Pick whichever attachment is set, in priority order.
        attachment = message.voice or message.audio or message.video_note
        if attachment is None:
            return
        kind = (
            "tg-voice" if message.voice
            else "tg-audio" if message.audio
            else "tg-video-note"
        )

        text = await transcriber.transcribe_voice(consumer.bot, attachment.file_id)
        if not text:
            log.warning("[%s] %s transcription failed", consumer.name, kind)
            return
        # Echo back what we heard so the operator can /stop on misheard input.
        await _echo_voice_transcript(consumer.bot, message, text)
        await consumer.queue.put(_make_msg(message, text, source=kind))

    @router.message(F.sticker)
    async def _sticker_handler(message: Message) -> None:
        """Stickers can't be reasoned over directly. Treat as a soft ack:
        emit one-line text describing the sticker (emoji + set) so the
        operator's intent comes through if the next message references it."""
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        sticker = message.sticker
        if sticker is None:
            return
        emoji = sticker.emoji or "🖼"
        set_name = sticker.set_name or "(no set)"
        text = f"[Sticker received: {emoji} (set: {set_name})]"
        await consumer.queue.put(_make_msg(message, text, source="tg-sticker"))

    @router.message(F.video | F.animation)
    async def _video_handler(message: Message) -> None:
        """Plain video / GIF — too big for Whisper, can't be Read'd as image.
        Surface a polite ack instead of silent drop."""
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        kind = "video" if message.video else "animation"
        await consumer.bot.send_message(
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
            text=(
                f"<i>I received a {kind} but can't process it yet. "
                f"Send a screenshot or describe what's in it as text instead.</i>"
            ),
            parse_mode="HTML",
        )

    @router.message(F.location | F.contact | F.poll | F.dice)
    async def _structured_handler(message: Message) -> None:
        """Structured Telegram payloads — surface as text so they're not lost."""
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        if message.location:
            text = (
                f"[Location shared: lat={message.location.latitude}, "
                f"lon={message.location.longitude}]"
            )
            source = "tg-location"
        elif message.contact:
            text = (
                f"[Contact shared: {message.contact.first_name or ''} "
                f"{message.contact.last_name or ''} "
                f"({message.contact.phone_number or 'no phone'})]"
            )
            source = "tg-contact"
        elif message.poll:
            opts = ", ".join(o.text for o in message.poll.options[:5])
            text = f"[Poll: {message.poll.question} — options: {opts}]"
            source = "tg-poll"
        elif message.dice:
            text = f"[Dice rolled: {message.dice.emoji} = {message.dice.value}]"
            source = "tg-dice"
        else:
            return
        await consumer.queue.put(_make_msg(message, text, source=source))

    @router.message(F.text)
    async def _text_handler(message: Message) -> None:
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        # consumer.cfg.bot_user_id is set once at startup via cache_getme().
        self_bot_id = getattr(consumer.cfg, "bot_user_id", None)
        enriched, source = _build_text_with_context(message, self_bot_id=self_bot_id)
        await consumer.queue.put(_make_msg(message, enriched, source=source))

    @router.message(F.photo)
    async def _photo_handler(message: Message) -> None:
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        try:
            saved = await _save_telegram_attachment(
                bot=consumer.bot,
                message=message,
                workspace=Path(consumer.cfg.workspace),
                kind="photo",
            )
        except Exception:  # noqa: BLE001
            log.exception("[%s] photo download failed", consumer.name)
            return
        if saved is None:
            return
        self_bot_id = getattr(consumer.cfg, "bot_user_id", None)
        enriched = _build_photo_prompt(message, saved, self_bot_id=self_bot_id)
        await consumer.queue.put(_make_msg(message, enriched, source="tg-photo"))

    @router.message(F.document)
    async def _document_handler(message: Message) -> None:
        if not _accept(message, allowed_user_ids, allowed_group_ids, consumer, bot_username):
            return
        doc = message.document
        # Reject binaries we can't usefully reason about.
        mime = (doc.mime_type or "").lower()
        if mime and mime not in ACCEPTED_DOC_MIME:
            await consumer.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=message.message_thread_id,
                text=f"<i>Skipped {doc.file_name or 'file'}: unsupported type ({mime})</i>",
                parse_mode="HTML",
            )
            return
        if doc.file_size and doc.file_size > TELEGRAM_BOT_DOWNLOAD_LIMIT:
            await consumer.bot.send_message(
                chat_id=message.chat.id,
                message_thread_id=message.message_thread_id,
                text=(
                    f"<i>Skipped {doc.file_name or 'file'}: "
                    f"{doc.file_size // (1024 * 1024)} MB exceeds 20 MB Telegram bot download cap</i>"
                ),
                parse_mode="HTML",
            )
            return
        try:
            saved = await _save_telegram_attachment(
                bot=consumer.bot,
                message=message,
                workspace=Path(consumer.cfg.workspace),
                kind="doc",
            )
        except Exception:  # noqa: BLE001
            log.exception("[%s] document download failed", consumer.name)
            return
        if saved is None:
            return
        self_bot_id = getattr(consumer.cfg, "bot_user_id", None)
        enriched = _build_document_prompt(message, saved, self_bot_id=self_bot_id)
        await consumer.queue.put(_make_msg(message, enriched, source="tg-document"))

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
    if not raw_text:
        return
    # Telegram clients automatically suffix `@<bot_username>` to slash-commands
    # in groups when the bot is one of several — i.e. `/reset@tirionaibot`
    # instead of bare `/reset`. Strip the suffix before matching against the
    # canonical OOB list. Author's original gateway.py:3036 does the same.
    head = raw_text.split()[0].lower()
    if "@" in head:
        head = head.split("@", 1)[0]
    if head not in OOB_COMMANDS:
        return
    cmd = head
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


async def _save_telegram_attachment(
    bot: Bot,
    message: Message,
    workspace: Path,
    kind: str,
) -> Path | None:
    """Download the photo (highest resolution) or document to the workspace.

    Returns the absolute path Claude can Read. Files land at::

        <workspace>/incoming/<msg_id>-<file_unique_id>.<ext>

    The directory is auto-created. Old files (>7 days) are pruned by the
    daily memory-rotate.sh cron. ``kind`` is "photo" or "doc" — drives the
    file extension and which TG attachment field is consumed.
    """
    inbox = workspace / "incoming"
    inbox.mkdir(parents=True, exist_ok=True)

    if kind == "photo":
        # Photos arrive as a list of PhotoSize sorted small→large.
        # Take the largest — Claude needs the high-res one for OCR / detail.
        if not message.photo:
            return None
        photo = message.photo[-1]
        file_id = photo.file_id
        unique = photo.file_unique_id
        ext = ".jpg"
    elif kind == "doc":
        doc = message.document
        if doc is None:
            return None
        file_id = doc.file_id
        unique = doc.file_unique_id
        # Preserve original extension if reasonable, else fall back by MIME.
        original = (doc.file_name or "")
        if "." in original and len(original.rsplit(".", 1)[-1]) <= 8:
            ext = "." + original.rsplit(".", 1)[-1].lower()
        elif (doc.mime_type or "").startswith("image/"):
            ext = "." + doc.mime_type.split("/", 1)[1]
        else:
            ext = ""
    else:
        raise ValueError(f"unknown attachment kind: {kind}")

    target = inbox / f"{message.message_id}-{unique}{ext}"
    if target.exists():
        # Idempotent: same file_unique_id → same path → reuse cached download.
        return target.resolve()

    await bot.download(file_id, destination=target)
    return target.resolve()


def _build_photo_prompt(
    message: Message, image_path: Path, self_bot_id: int | None = None
) -> str:
    """Compose the user_text Claude sees for a photo turn.

    We use an explicit prompt rather than relying on Claude Code's @-mention
    auto-attachment, because the @-syntax is parsed in interactive CLI but
    not always in stdin-fed `-p` mode. An explicit "use the Read tool"
    instruction is reliable across CLI versions.
    """
    parts: list[str] = []
    # Reply / forward enrichment first (same logic as text).
    enriched_caption, _src = _build_text_with_context(message, self_bot_id=self_bot_id)
    if enriched_caption.strip():
        parts.append(enriched_caption.strip())
    else:
        parts.append("[image with no caption]")
    parts.append("")
    parts.append(
        f"The operator attached an image. Use the Read tool to view it: "
        f"{image_path}"
    )
    return "\n".join(parts)


def _build_document_prompt(
    message: Message, doc_path: Path, self_bot_id: int | None = None
) -> str:
    parts: list[str] = []
    enriched_caption, _src = _build_text_with_context(message, self_bot_id=self_bot_id)
    if enriched_caption.strip():
        parts.append(enriched_caption.strip())
    else:
        parts.append("[document with no caption]")
    fname = (message.document.file_name if message.document else "") or doc_path.name
    parts.append("")
    parts.append(
        f"The operator attached a file `{fname}`. Use the Read tool to view it: "
        f"{doc_path}"
    )
    return "\n".join(parts)


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
    """Bind a per-agent Bot instance + Router to the shared Dispatcher.

    Multi-bot gotcha: with ``Dispatcher.start_polling(*bots)``, all routers
    live in one Dispatcher and aiogram tries them in include order. The first
    router whose handler matches wins — even if the matched handler returns
    ``None`` (rejecting the update). Without a per-bot filter, agent A's
    router silently swallows updates that were polled by agent B's bot,
    because both have ``@router.message(F.text)``.

    Fix: scope each router to its own bot via ``F.bot.id``. When agent B's
    update arrives, agent A's router doesn't match → aiogram continues
    walking the chain → reaches agent B's router → matches → handles.
    """
    router.message.filter(F.bot.id == bot.id)
    router.callback_query.filter(F.bot.id == bot.id)
    router.edited_message.filter(F.bot.id == bot.id)

    dp.include_router(router)
    # aiogram v3 supports multi-bot polling via Dispatcher.start_polling(*bots).
    # We track the bots list outside; the actual call lives in __main__.py.
    if not hasattr(dp, "_bots"):
        dp._bots: list[Bot] = []  # type: ignore[attr-defined]
    dp._bots.append(bot)  # type: ignore[attr-defined]
