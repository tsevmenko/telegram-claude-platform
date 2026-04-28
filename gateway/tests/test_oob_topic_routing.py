"""Regression test for the bug where OOB commands (/status, /stop, /reset,
/compact, /cancel, /new) bypassed topic_routing.

Symptom on live VPS: Leto (configured for General topic only) answered
``/status`` in the Technical topic that's owned by Vesna. Both bots in the
same group received the OOB and both answered.

Root cause: ``producer._oob_handler`` was the only handler that didn't call
``_accept`` / ``is_addressed_to_agent``. We added ``_accept_for_oob`` which
keeps the user-allowlist bypass (panic-button semantics) but enforces
group + topic routing.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_gateway.tg.producer import _accept_for_oob


def _msg(*, chat_id: int, chat_type: str, thread_id: int | None,
         is_forum: bool = False, text: str = "/status") -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type, is_forum=is_forum),
        message_thread_id=thread_id,
        text=text,
        caption=None,
    )


def _consumer(agent_name: str, topic_routing: dict, agent_names=None):
    cfg = SimpleNamespace(
        agent_names=agent_names or [agent_name],
        topic_routing=topic_routing,
    )
    return SimpleNamespace(name=agent_name, cfg=cfg)


# Realistic scenario: forum group -100…150, Leto routes "general", Vesna
# routes topic_id "168". Operator types /status in topic 168 (Vesna's).
# Only Vesna should accept; Leto must reject.


def test_leto_rejects_oob_in_vesnas_topic() -> None:
    leto = _consumer("leto", {"-1003619435150": ["general"]})
    msg = _msg(chat_id=-1003619435150, chat_type="supergroup",
               thread_id=168, is_forum=True)
    assert _accept_for_oob(msg, {-1003619435150}, leto, "letoaibot") is False


def test_vesna_accepts_oob_in_her_topic() -> None:
    vesna = _consumer("vesna", {"-1003619435150": ["168"]})
    msg = _msg(chat_id=-1003619435150, chat_type="supergroup",
               thread_id=168, is_forum=True)
    assert _accept_for_oob(msg, {-1003619435150}, vesna, "vesna_admin_bot") is True


def test_leto_accepts_oob_in_general() -> None:
    leto = _consumer("leto", {"-1003619435150": ["general"]})
    # General topic: thread_id is None and chat is_forum=True
    msg = _msg(chat_id=-1003619435150, chat_type="supergroup",
               thread_id=None, is_forum=True)
    assert _accept_for_oob(msg, {-1003619435150}, leto, "letoaibot") is True


def test_vesna_rejects_oob_in_general() -> None:
    vesna = _consumer("vesna", {"-1003619435150": ["168"]})
    msg = _msg(chat_id=-1003619435150, chat_type="supergroup",
               thread_id=None, is_forum=True)
    assert _accept_for_oob(msg, {-1003619435150}, vesna, "vesna_admin_bot") is False


def test_oob_in_unallowlisted_group_rejected() -> None:
    leto = _consumer("leto", {"-1003619435150": ["general"]})
    # Different group id — must reject even though the topic field would match.
    msg = _msg(chat_id=-1009999999999, chat_type="supergroup",
               thread_id=None, is_forum=True)
    assert _accept_for_oob(msg, {-1003619435150}, leto, "letoaibot") is False


def test_oob_in_private_chat_always_accepted() -> None:
    """Operator's private DM with the bot still hits OOB. Allowlist-skip
    means anyone DMing the bot can /stop too — that's by design (panic
    button > deny rule)."""
    leto = _consumer("leto", {})
    msg = _msg(chat_id=12345, chat_type="private", thread_id=None)
    assert _accept_for_oob(msg, {-1003619435150}, leto, "letoaibot") is True


def test_oob_user_allowlist_intentionally_skipped() -> None:
    """The whole point of _accept_for_oob: a stranger in an allowlisted
    group can /stop the agent. We DON'T accept their /text — but /stop
    we honour even from non-allowlisted users to keep it a real panic
    button."""
    leto = _consumer("leto", {"-1003619435150": ["general"]})
    msg = _msg(chat_id=-1003619435150, chat_type="supergroup",
               thread_id=None, is_forum=True)
    # No user allowlist parameter here at all — function shouldn't take one.
    assert _accept_for_oob(msg, {-1003619435150}, leto, "letoaibot") is True
