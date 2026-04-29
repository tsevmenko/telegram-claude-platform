"""Tests for Phase 3b: reply-context injection, forward-tag, HOT source-tag."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_gateway.consumer import IncomingMessage
from agent_gateway.memory.hot import append_turn
from agent_gateway.tg.producer import (
    _build_text_with_context,
    _forward_origin_name,
    _make_msg,
)


# ---------------------------------------------------------------------------
# IncomingMessage.source field
# ---------------------------------------------------------------------------


def test_incoming_message_source_defaults_to_tg_text() -> None:
    m = IncomingMessage(chat_id=1, user_id=2, message_id=3, thread_id=None, text="x")
    assert m.source == "tg-text"


def test_make_msg_passes_source() -> None:
    fake_msg = SimpleNamespace(
        chat=SimpleNamespace(id=10),
        from_user=SimpleNamespace(id=20),
        message_id=30,
        message_thread_id=None,
        forward_origin=None,
        reply_to_message=None,
        text="hi",
    )
    msg = _make_msg(fake_msg, "hi", source="tg-voice")
    assert msg.source == "tg-voice"


# ---------------------------------------------------------------------------
# _build_text_with_context
# ---------------------------------------------------------------------------


def _msg(
    text: str,
    *,
    forward_origin: object | None = None,
    reply: object | None = None,
    quote: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        caption=None,
        forward_origin=forward_origin,
        reply_to_message=reply,
        quote=quote,
    )


def test_plain_text_no_enrichment() -> None:
    enriched, source = _build_text_with_context(_msg("hello"))
    assert enriched == "hello"
    assert source == "tg-text"


def test_forward_from_user_tags_origin() -> None:
    fwd = SimpleNamespace(
        sender_user=SimpleNamespace(full_name="Alice Smith", first_name="Alice"),
    )
    enriched, source = _build_text_with_context(_msg("see this", forward_origin=fwd))
    assert "[Forwarded from: Alice Smith]" in enriched
    assert "see this" in enriched
    assert source == "forwarded"


def test_forward_from_hidden_user() -> None:
    """MessageOriginHiddenUser exposes only sender_user_name (privacy mode)."""
    fwd = SimpleNamespace(sender_user=None, sender_user_name="hidden_user_42")
    enriched, _ = _build_text_with_context(_msg("body", forward_origin=fwd))
    assert "[Forwarded from: hidden_user_42]" in enriched


def test_forward_from_channel() -> None:
    fwd = SimpleNamespace(
        sender_user=None,
        sender_user_name=None,
        chat=SimpleNamespace(title="My News Channel", username="news"),
    )
    enriched, _ = _build_text_with_context(_msg("body", forward_origin=fwd))
    assert "[Forwarded from: My News Channel]" in enriched


def test_reply_to_non_bot_injects_untrusted_block() -> None:
    reply = SimpleNamespace(
        from_user=SimpleNamespace(is_bot=False, full_name="Bob"),
        text="please repackage as HTML",
        caption=None,
    )
    enriched, source = _build_text_with_context(
        _msg("do it now", reply=reply)
    )
    assert "Replied to an earlier message" in enriched
    assert "untrusted metadata" in enriched
    assert "please repackage as HTML" in enriched
    assert "---" in enriched
    assert "do it now" in enriched
    assert source == "replied"


def test_reply_to_self_bot_now_injects_with_self_label() -> None:
    """Reply to our own bot's prior message ALSO injects.

    Earlier behaviour skipped this on the assumption that the prior bot
    output was always in session history. Live regression caught by Tyrion
    (2026-04-30): post-compact and over-window replies invisibilised the
    operator's focus. Now we always inject, but label it 'your prior
    message' so the model knows the body is its own past output, not new
    operator content.
    """
    reply = SimpleNamespace(
        from_user=SimpleNamespace(id=4242, is_bot=True, full_name="MyBot"),
        text="here is option D from my list",
        caption=None,
    )
    enriched, source = _build_text_with_context(
        _msg("D it is", reply=reply), self_bot_id=4242
    )
    assert "Replied to your prior message" in enriched
    assert "here is option D from my list" in enriched
    assert source == "replied"


def test_reply_quote_field_takes_priority_over_full_body() -> None:
    """Bot API 7+ TextQuote: when the operator highlights a snippet, it's the
    high-signal focus and we should use it instead of the whole replied body."""
    reply = SimpleNamespace(
        from_user=SimpleNamespace(is_bot=False),
        text="A) apples B) bananas C) cherries D) durian E) elderberry",
        caption=None,
    )
    quote = SimpleNamespace(text="D) durian", position=30, is_manual=True)
    enriched, source = _build_text_with_context(
        _msg("explain this option", reply=reply, quote=quote)
    )
    assert "D) durian" in enriched
    # The non-highlighted parts of the replied body are NOT in the snippet.
    assert "A) apples" not in enriched.split("explain this option")[0]
    assert "(quoted snippet" in enriched
    assert source == "replied"


def test_reply_quote_to_self_uses_self_label_with_quote_kind() -> None:
    """Combine: reply-to-self bot + quote field. Both labels apply."""
    reply = SimpleNamespace(
        from_user=SimpleNamespace(id=99, is_bot=True),
        text="A B C D E F G",
        caption=None,
    )
    quote = SimpleNamespace(text="D", position=6, is_manual=True)
    enriched, _ = _build_text_with_context(
        _msg("hook", reply=reply, quote=quote), self_bot_id=99
    )
    assert "Replied to your prior message (quoted snippet" in enriched
    assert "\nD\n" in enriched


def test_reply_with_empty_body_and_no_quote_is_noop() -> None:
    reply = SimpleNamespace(
        from_user=SimpleNamespace(is_bot=False),
        text="",
        caption=None,
    )
    enriched, source = _build_text_with_context(_msg("hi", reply=reply))
    assert enriched == "hi"
    assert source == "tg-text"


def test_forward_and_reply_combined() -> None:
    fwd = SimpleNamespace(sender_user=SimpleNamespace(full_name="Channel Bot"))
    reply = SimpleNamespace(
        from_user=SimpleNamespace(is_bot=False),
        text="earlier message",
        caption=None,
    )
    enriched, source = _build_text_with_context(
        _msg("act on this", forward_origin=fwd, reply=reply)
    )
    # Forward wins for source tag; both blocks present in body.
    assert "[Forwarded from: Channel Bot]" in enriched
    assert "Replied to an earlier message" in enriched
    assert source == "forwarded"


def test_reply_body_truncated_at_500_chars() -> None:
    long_body = "x" * 1000
    reply = SimpleNamespace(
        from_user=SimpleNamespace(is_bot=False),
        text=long_body,
        caption=None,
    )
    enriched, _ = _build_text_with_context(_msg("ack", reply=reply))
    # 500 chars of x → followed by "---" separator
    assert "x" * 500 in enriched
    assert "x" * 501 not in enriched


# ---------------------------------------------------------------------------
# Telegram message-link detection
# ---------------------------------------------------------------------------


def test_tme_private_link_with_topic_emits_hint() -> None:
    """Live regression: operator pasted a t.me link to a specific message
    expecting the bot to fetch it. Bot API has no getMessage-by-id, so we
    surface a hint nudging operator to Reply instead."""
    enriched, source = _build_text_with_context(
        _msg("analyze https://t.me/c/3619435150/318/427 please")
    )
    assert "Telegram message link(s) mentioned" in enriched
    assert "ask the operator to *reply*" in enriched
    assert "https://t.me/c/3619435150/318/427" in enriched
    assert source == "link-mention"


def test_tme_private_link_root_thread_recognised() -> None:
    enriched, _ = _build_text_with_context(
        _msg("https://t.me/c/3619435150/427")
    )
    assert "Telegram message link(s)" in enriched


def test_tme_public_link_with_username_recognised() -> None:
    enriched, _ = _build_text_with_context(
        _msg("see https://t.me/somechannel/12345")
    )
    assert "Telegram message link(s)" in enriched
    assert "https://t.me/somechannel/12345" in enriched


def test_tme_link_dedup_keeps_one_block() -> None:
    """Same link mentioned twice → hint shown once, not duplicated."""
    enriched, _ = _build_text_with_context(
        _msg(
            "https://t.me/c/100/5 first ref, also https://t.me/c/100/5 again"
        )
    )
    # Only one occurrence of the URL in the bullet block (the original text
    # below the --- still has both occurrences — that's the operator's words).
    hint_block = enriched.split("---")[0]
    assert hint_block.count("https://t.me/c/100/5") == 1


def test_tme_link_cap_at_five_links() -> None:
    """Link spam cap: first 5 links surfaced, rest dropped from the hint."""
    urls = " ".join(f"https://t.me/c/100/{i}" for i in range(1, 11))
    enriched, _ = _build_text_with_context(_msg(f"check {urls}"))
    hint_block = enriched.split("---")[0]
    # 5 bullet rows, not 10
    assert hint_block.count("- https://t.me/c/100/") == 5


def test_non_tme_links_dont_trigger_hint() -> None:
    """A regular https URL must not be misclassified as a t.me link."""
    enriched, source = _build_text_with_context(
        _msg("see https://example.com/article and https://github.com/x/y")
    )
    assert "Telegram message link" not in enriched
    assert source == "tg-text"


def test_tme_link_combines_with_reply() -> None:
    """Operator replies AND mentions a link — both blocks appear, source='replied'
    (replied is more specific signal than link-mention)."""
    reply = SimpleNamespace(
        from_user=SimpleNamespace(is_bot=False),
        text="prior",
        caption=None,
    )
    enriched, source = _build_text_with_context(
        _msg("look at https://t.me/c/100/5", reply=reply)
    )
    assert "Replied to an earlier message" in enriched
    assert "Telegram message link(s)" in enriched
    assert source == "replied"


# ---------------------------------------------------------------------------
# _forward_origin_name fallbacks
# ---------------------------------------------------------------------------


def test_forward_origin_name_unknown_when_empty() -> None:
    assert _forward_origin_name(SimpleNamespace()) == "unknown"


def test_forward_origin_name_falls_back_first_name() -> None:
    origin = SimpleNamespace(
        sender_user=SimpleNamespace(full_name=None, first_name="Charlie")
    )
    assert _forward_origin_name(origin) == "Charlie"


# ---------------------------------------------------------------------------
# hot.append_turn — source tag is preserved in the journal entry
# ---------------------------------------------------------------------------


def test_hot_append_writes_source_tag(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "core" / "hot").mkdir(parents=True)
    (workspace / "core" / "hot" / "recent.md").write_text("# HOT\n")

    append_turn(workspace, "test", "user said", "agent replied", source_tag="replied")
    text = (workspace / "core" / "hot" / "recent.md").read_text()
    assert "[replied]" in text
    assert "user said" in text
    assert "agent replied" in text


def test_hot_append_supports_all_source_kinds(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "core" / "hot").mkdir(parents=True)
    (workspace / "core" / "hot" / "recent.md").write_text("# HOT\n")

    for kind in ("tg-text", "tg-voice", "forwarded", "replied", "webhook"):
        append_turn(workspace, "test", f"u-{kind}", f"a-{kind}", source_tag=kind)

    text = (workspace / "core" / "hot" / "recent.md").read_text()
    for kind in ("tg-text", "tg-voice", "forwarded", "replied", "webhook"):
        assert f"[{kind}]" in text, f"missing source tag {kind} in HOT memory"
