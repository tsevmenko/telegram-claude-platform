"""Markdown → Telegram HTML conversion + rate-limited message editing.

Telegram HTML supports a small subset of tags: ``<b>``, ``<i>``, ``<u>``,
``<s>``, ``<a>``, ``<code>``, ``<pre>``, ``<blockquote>``. Headings, lists,
and tables are not supported and need to be flattened into ``<pre>`` or plain
text.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass

# Limits per Bot API: 4096 chars per message body.
MAX_MESSAGE_LEN = 4000  # a little headroom for HTML tags
EDIT_INTERVAL_SEC = 1.5


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def markdown_to_telegram_html(text: str) -> str:
    """Convert a subset of markdown to Telegram-compatible HTML.

    Rules:
    - Fenced code blocks (```) → ``<pre><code class="language-...">…</code></pre>``.
    - Inline ``code`` → ``<code>…</code>``.
    - **bold** / __bold__ → ``<b>``; *italic* / _italic_ → ``<i>``.
    - ~~strike~~ → ``<s>``.
    - [text](url) → ``<a href="url">text</a>``.
    - Tables → flattened into ``<pre>`` (Telegram has no native table rendering).
    - Headings ``#``-style → bold first line.
    - Lists kept as-is (Telegram renders ``-`` and ``1.`` reasonably).
    """
    text = _convert_fenced_code(text)
    text = _convert_inline_code(text)
    text = _convert_bold_italic(text)
    text = _convert_strike(text)
    text = _convert_links(text)
    text = _convert_tables(text)
    text = _convert_headings(text)
    return text


def _convert_fenced_code(text: str) -> str:
    pattern = re.compile(r"```(\w+)?\n(.+?)```", re.DOTALL)

    def repl(m: re.Match[str]) -> str:
        lang = m.group(1) or ""
        code = escape_html(m.group(2))
        if lang:
            return f'<pre><code class="language-{lang}">{code}</code></pre>'
        return f"<pre>{code}</pre>"

    return pattern.sub(repl, text)


def _convert_inline_code(text: str) -> str:
    # Avoid touching code already inside <pre>...</pre>.
    parts = re.split(r"(<pre>.*?</pre>)", text, flags=re.DOTALL)
    for i, part in enumerate(parts):
        if part.startswith("<pre>"):
            continue
        parts[i] = re.sub(r"`([^`\n]+)`", lambda m: f"<code>{escape_html(m.group(1))}</code>", part)
    return "".join(parts)


def _convert_bold_italic(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![_\w])_(?!\s)(.+?)(?<!\s)_(?![_\w])", r"<i>\1</i>", text)
    return text


def _convert_strike(text: str) -> str:
    return re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)


def _convert_links(text: str) -> str:
    return re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        text,
    )


def _convert_tables(text: str) -> str:
    """Wrap pipe-tables in <pre> since Telegram has no table rendering."""
    lines = text.splitlines()
    out: list[str] = []
    buf: list[str] = []
    in_table = False

    for line in lines:
        is_row = "|" in line and line.strip().startswith("|")
        if is_row:
            if not in_table:
                in_table = True
                buf = []
            buf.append(line)
        else:
            if in_table:
                out.append("<pre>" + escape_html("\n".join(buf)) + "</pre>")
                buf = []
                in_table = False
            out.append(line)

    if in_table and buf:
        out.append("<pre>" + escape_html("\n".join(buf)) + "</pre>")

    return "\n".join(out)


def _convert_headings(text: str) -> str:
    return re.sub(r"^(#{1,6})\s+(.+)$", r"<b>\2</b>", text, flags=re.MULTILINE)


def truncate_for_telegram(text: str, max_len: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split text into Telegram-sized chunks at line boundaries when possible."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, max_len)
        if cut < max_len // 2:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


@dataclass
class EditRateLimiter:
    """Rate-limit ``editMessageText`` calls per (chat_id, message_id)."""

    interval_sec: float = EDIT_INTERVAL_SEC
    _last_edit: dict[tuple[int, int], float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._last_edit = {}

    def should_edit(self, chat_id: int, message_id: int) -> bool:
        now = time.monotonic()
        last = self._last_edit.get((chat_id, message_id), 0.0)
        if now - last >= self.interval_sec:
            self._last_edit[(chat_id, message_id)] = now
            return True
        return False
