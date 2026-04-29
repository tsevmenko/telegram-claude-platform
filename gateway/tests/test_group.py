"""Group-routing tests."""

from __future__ import annotations

from types import SimpleNamespace

from agent_gateway.config import AgentConfig
from agent_gateway.tg.group import is_addressed_to_agent


def _msg(chat_type, text, thread_id=None, chat_id=-100, is_forum=False):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type, is_forum=is_forum),
        message_thread_id=thread_id,
        text=text,
        caption=None,
    )


def _cfg(agent_names=None, topic_routing=None):
    return AgentConfig(
        workspace="/tmp/ws",
        agent_names=agent_names or [],
        topic_routing=topic_routing or {},
    )


def test_private_chat_always_addressed():
    cfg = _cfg()
    msg = _msg("private", "hi")
    assert is_addressed_to_agent("leto", cfg, msg, None) is True


def test_topic_routing_hits():
    cfg = _cfg(topic_routing={"-100": ["42"]})
    msg = _msg("supergroup", "hello", thread_id=42, chat_id=-100)
    assert is_addressed_to_agent("leto", cfg, msg, None) is True


def test_topic_routing_misses():
    cfg = _cfg(topic_routing={"-100": ["42"]})
    msg = _msg("supergroup", "hello", thread_id=99, chat_id=-100)
    assert is_addressed_to_agent("leto", cfg, msg, None) is False


def test_general_topic_routes_when_general_listed():
    """In a forum supergroup, default General topic has thread_id=None.
    Operators register it as the literal string "general"."""
    cfg = _cfg(topic_routing={"-100": ["general"]})
    msg = _msg("supergroup", "hello", thread_id=None, chat_id=-100, is_forum=True)
    assert is_addressed_to_agent("leto", cfg, msg, None) is True


def test_general_topic_silent_when_not_listed():
    cfg = _cfg(topic_routing={"-100": ["42"]})
    msg = _msg("supergroup", "hello", thread_id=None, chat_id=-100, is_forum=True)
    # No @mention, no agent_names match, General not in routing → silence.
    assert is_addressed_to_agent("leto", cfg, msg, None) is False


def test_non_forum_supergroup_still_no_general_routing():
    """For regular (non-forum) supergroups, `is_forum` is False and
    thread_id is always None — but those should NOT be routed via the
    "general" key (that key is forum-specific)."""
    cfg = _cfg(topic_routing={"-100": ["general"]})
    msg = _msg("supergroup", "hi", thread_id=None, chat_id=-100, is_forum=False)
    assert is_addressed_to_agent("leto", cfg, msg, None) is False


def test_mention_by_bot_username():
    cfg = _cfg()
    msg = _msg("supergroup", "hey @leto_bot what's up", chat_id=-100)
    assert is_addressed_to_agent("leto", cfg, msg, "leto_bot") is True


def test_mention_by_agent_name_word_boundary():
    cfg = _cfg(agent_names=["leto"])
    msg = _msg("supergroup", "leto, please respond", chat_id=-100)
    assert is_addressed_to_agent("leto", cfg, msg, None) is True


def test_no_match_in_unrelated_word():
    cfg = _cfg(agent_names=["leto"])
    # "letonia" should NOT trigger leto.
    msg = _msg("supergroup", "I went to letonia last summer", chat_id=-100)
    assert is_addressed_to_agent("leto", cfg, msg, None) is False


def test_empty_text_in_group_not_addressed():
    cfg = _cfg(agent_names=["leto"])
    msg = _msg("supergroup", "", chat_id=-100)
    assert is_addressed_to_agent("leto", cfg, msg, None) is False


def test_strict_routing_ignores_name_mention_in_foreign_topic():
    """Live-VPS regression: in a multi-agent forum group, operators casually
    say "Vesna and Leto" while planning. Without strict routing, Leto would
    barge into Vesna's Technical topic on every such mention.

    With strict routing: when topic_routing is configured for a chat, we
    respond ONLY in registered topics. @mentions / agent_names matches in
    other topics are ignored.
    """
    cfg = _cfg(
        agent_names=["leto"],
        topic_routing={"-100": ["general"]},  # Leto registered for General only
    )
    # Operator in Tech topic (thread_id=168) writes message that mentions Leto.
    msg = _msg(
        "supergroup",
        "у нас есть Vesna, Leto, Tyrion — координируем планы",
        thread_id=168,
        chat_id=-100,
        is_forum=True,
    )
    assert is_addressed_to_agent("leto", cfg, msg, "letoaibot") is False, (
        "Leto must NOT respond in Tech (thread 168) even when message mentions 'leto' — "
        "strict topic routing should beat name-mention fallback"
    )


def test_strict_routing_accepts_in_registered_topic():
    cfg = _cfg(topic_routing={"-100": ["general"]})
    msg = _msg(
        "supergroup", "hello", thread_id=None, chat_id=-100, is_forum=True
    )
    assert is_addressed_to_agent("leto", cfg, msg, None) is True


def test_legacy_mention_still_works_when_no_topic_routing():
    """Backward compat: operators who haven't configured topic_routing yet
    rely on @mention detection. Don't break that."""
    cfg = _cfg(agent_names=["leto"], topic_routing={})
    msg = _msg(
        "supergroup", "hey leto, what's up?", chat_id=-100, is_forum=True
    )
    assert is_addressed_to_agent("leto", cfg, msg, None) is True


def test_strict_routing_rejects_foreign_username_mention():
    """Even @vesna_admin_bot pinged in a topic Leto isn't routed to should
    NOT wake Leto — strict routing means foreign topic = silent."""
    cfg = _cfg(
        agent_names=["leto"],
        topic_routing={"-100": ["general"]},
    )
    msg = _msg(
        "supergroup",
        "@vesna_admin_bot please run a status check",
        thread_id=168,
        chat_id=-100,
        is_forum=True,
    )
    assert is_addressed_to_agent("leto", cfg, msg, "letoaibot") is False
