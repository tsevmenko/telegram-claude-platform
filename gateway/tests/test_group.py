"""Group-routing tests."""

from __future__ import annotations

from types import SimpleNamespace

from agent_gateway.config import AgentConfig
from agent_gateway.tg.group import is_addressed_to_agent


def _msg(chat_type, text, thread_id=None, chat_id=-100):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type),
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
