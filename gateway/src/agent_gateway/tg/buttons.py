"""Inline button rendering and callback dispatch.

The agent embeds button markers in its reply text. Example:

    Should I commit these changes?
    [BUTTONS: [Yes|commit:yes] [No|commit:no] [Show diff|show:diff]]

The renderer detects the marker, strips it from the text, and attaches an
``InlineKeyboardMarkup`` to the outgoing message. Each button's
``callback_data`` is the part after the ``|``.

Callbacks are routed by **prefix**. Skills/agents register handlers via
``register_callback_handler("commit:", fn)`` — any callback starting with
``commit:`` is delivered to ``fn``. The default fallback echoes the action
back to the chat as a confirmation.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

log = logging.getLogger(__name__)

CallbackHandler = Callable[[Bot, CallbackQuery, str], Awaitable[None]]


@dataclass
class ButtonSpec:
    label: str
    callback_data: str


# Pattern: [BUTTONS: [label|cb] [label|cb] ...]
# Inner pattern: [Yes|commit:yes]
_OUTER_RE = re.compile(r"\[BUTTONS:\s*((?:\[[^\]\|]+\|[^\]]+\]\s*)+)\]")
_INNER_RE = re.compile(r"\[([^\]\|]+)\|([^\]]+)\]")

# Telegram callback_data is limited to 64 bytes.
CALLBACK_DATA_MAX = 64


def extract_buttons(text: str) -> tuple[str, list[list[ButtonSpec]]]:
    """Strip the [BUTTONS: …] marker from text. Return (cleaned_text, rows)."""
    rows: list[list[ButtonSpec]] = []
    cleaned_parts: list[str] = []
    last = 0
    for m in _OUTER_RE.finditer(text):
        cleaned_parts.append(text[last:m.start()])
        spec_blob = m.group(1)
        row: list[ButtonSpec] = []
        for inner in _INNER_RE.finditer(spec_blob):
            label = inner.group(1).strip()
            cb = inner.group(2).strip()
            if not label or not cb:
                continue
            if len(cb.encode("utf-8")) > CALLBACK_DATA_MAX:
                cb = cb.encode("utf-8")[:CALLBACK_DATA_MAX].decode("utf-8", errors="ignore")
            row.append(ButtonSpec(label=label, callback_data=cb))
        if row:
            rows.append(row)
        last = m.end()
    cleaned_parts.append(text[last:])
    return "".join(cleaned_parts).strip(), rows


def build_keyboard(rows: list[list[ButtonSpec]]) -> InlineKeyboardMarkup | None:
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b.label, callback_data=b.callback_data) for b in row]
        for row in rows
    ])


class CallbackDispatcher:
    """Prefix-based router for inline button callbacks."""

    def __init__(self) -> None:
        self._handlers: dict[str, CallbackHandler] = {}

    def register(self, prefix: str, handler: CallbackHandler) -> None:
        self._handlers[prefix] = handler

    async def dispatch(self, bot: Bot, query: CallbackQuery) -> None:
        data = query.data or ""
        for prefix, handler in self._handlers.items():
            if data.startswith(prefix):
                await handler(bot, query, data[len(prefix):])
                return
        await default_handler(bot, query, data)


async def default_handler(bot: Bot, query: CallbackQuery, _payload: str) -> None:
    """Fallback: ack the callback and echo the action label."""
    label = query.data or "?"
    try:
        await query.answer(text=f"action: {label}", show_alert=False)
    except Exception:  # noqa: BLE001
        pass
    msg: Message | None = query.message  # type: ignore[assignment]
    if msg is None:
        return
    try:
        await bot.send_message(
            chat_id=msg.chat.id,
            message_thread_id=msg.message_thread_id,
            text=f"<i>(action recorded: {label})</i>",
            parse_mode="HTML",
        )
    except Exception:  # noqa: BLE001
        pass
