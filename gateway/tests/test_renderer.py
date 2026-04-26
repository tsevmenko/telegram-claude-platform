"""Markdown→HTML + truncation + rate-limit tests."""

from __future__ import annotations

from agent_gateway.tg.renderer import (
    EditRateLimiter,
    escape_html,
    markdown_to_telegram_html,
    truncate_for_telegram,
)


def test_escape_html_basic():
    assert escape_html("a & b") == "a &amp; b"
    assert escape_html("<script>") == "&lt;script&gt;"


def test_fenced_code_block_with_language():
    out = markdown_to_telegram_html("```python\nprint('hi')\n```")
    assert "<pre><code" in out
    assert "language-python" in out


def test_fenced_code_block_without_language():
    out = markdown_to_telegram_html("```\nplain text\n```")
    assert "<pre>" in out
    assert "plain text" in out


def test_inline_code_does_not_double_escape_inside_pre():
    src = "before ```\ndo not `escape` here\n``` after `inline` x"
    out = markdown_to_telegram_html(src)
    # Inside <pre>, `inline` should NOT be wrapped in <code>
    pre_part, _, after = out.partition("</pre>")
    assert "<code>" not in pre_part.split("<pre>", 1)[1]
    assert "<code>inline</code>" in after


def test_bold_and_italic():
    assert "<b>bold</b>" in markdown_to_telegram_html("**bold**")
    assert "<b>bold</b>" in markdown_to_telegram_html("__bold__")
    out_italic = markdown_to_telegram_html("here is *italic* text")
    assert "<i>italic</i>" in out_italic


def test_link_conversion():
    out = markdown_to_telegram_html("see [docs](https://example.com)")
    assert '<a href="https://example.com">docs</a>' in out


def test_table_wrapped_in_pre():
    src = "| a | b |\n|---|---|\n| 1 | 2 |"
    out = markdown_to_telegram_html(src)
    assert "<pre>" in out
    assert "| a | b |" in out


def test_heading_becomes_bold():
    out = markdown_to_telegram_html("# Title\nbody")
    assert "<b>Title</b>" in out


def test_truncate_short_message_unchanged():
    assert truncate_for_telegram("hi") == ["hi"]


def test_truncate_at_line_boundary():
    body = "line1\n" * 1500  # ~9000 chars
    chunks = truncate_for_telegram(body, max_len=4000)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 4000


def test_rate_limiter_first_call_passes():
    rl = EditRateLimiter(interval_sec=10)
    assert rl.should_edit(1, 100) is True


def test_rate_limiter_blocks_inside_interval():
    rl = EditRateLimiter(interval_sec=10)
    rl.should_edit(1, 100)
    assert rl.should_edit(1, 100) is False


def test_rate_limiter_per_message():
    rl = EditRateLimiter(interval_sec=10)
    assert rl.should_edit(1, 100) is True
    assert rl.should_edit(1, 200) is True   # different message_id
    assert rl.should_edit(2, 100) is True   # different chat
