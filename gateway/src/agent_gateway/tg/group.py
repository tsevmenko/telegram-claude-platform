"""Group-chat routing helpers.

Per-topic routing: in a Telegram forum group, each topic has a numeric
``message_thread_id``. Each agent's config maps ``{chat_id: [topic_id, ...]}``
— if an incoming message lands in a topic registered for this agent, the
agent handles it; otherwise the message is ignored.

The other group-chat heuristic is ``@bot_username`` mention detection — the
agent only replies when explicitly addressed. This is the legacy path used
when the operator hasn't set up forum topics yet.
"""

from __future__ import annotations

from aiogram.types import Message

from agent_gateway.config import AgentConfig


def is_addressed_to_agent(
    agent_name: str,
    cfg: AgentConfig,
    message: Message,
    bot_username: str | None,
) -> bool:
    """Return True if this message is meant for ``agent_name``."""
    chat_type = message.chat.type
    if chat_type in ("private",):
        # Direct messages are always addressed to the bot they reach.
        return True

    # Forum/topic routing — preferred path.
    # Telegram does NOT include `message_thread_id` for messages in the
    # default General topic of a forum supergroup. We map that case to
    # the routing key "general" so operators can register General the
    # same way as named topics:
    #     "topic_routing": {"-100123...": ["general", "42"]}
    chat_topics = cfg.topic_routing.get(str(message.chat.id), [])
    thread_key: str | None
    if message.message_thread_id is not None:
        thread_key = str(message.message_thread_id)
    elif getattr(message.chat, "is_forum", False):
        thread_key = "general"
    else:
        thread_key = None

    # STRICT topic routing: if the operator configured topics for this chat,
    # we ONLY respond in those topics. We do NOT fall back to @mention /
    # agent_names matching in other topics, because in a multi-agent forum
    # the literal word "leto" or "vesna" appears in the operators' planning
    # discussions all the time — agents would barge into each others'
    # topics every time a name was uttered. Strict routing keeps each
    # agent in its lane.
    if chat_topics:
        return bool(thread_key and thread_key in chat_topics)

    # No topic_routing configured for this chat → legacy path: respond on
    # @mention or agent_names hit. This preserves the v1 single-bot DM-style
    # behaviour for operators who haven't (yet) split their group into topics.
    text = (message.text or message.caption or "").lower()
    if not text:
        return False

    # @username mention.
    if bot_username:
        if f"@{bot_username.lower()}" in text:
            return True

    # Bare-name mention from agent_names list.
    for name in cfg.agent_names:
        token = name.lower()
        # Word-boundary check: avoid matching "leto" inside "letonia".
        if _word_in(text, token):
            return True

    return False


def _word_in(text: str, word: str) -> bool:
    word = word.lower()
    if word not in text:
        return False
    # Quick word-boundary check — works for ASCII names; Cyrillic names rely
    # on the substring match (which is fine for short, distinctive bot names).
    idx = text.find(word)
    if idx == -1:
        return False
    before = text[idx - 1] if idx > 0 else " "
    after = text[idx + len(word)] if idx + len(word) < len(text) else " "
    return not (before.isalnum() or after.isalnum())
