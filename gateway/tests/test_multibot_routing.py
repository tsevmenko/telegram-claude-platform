"""Multi-bot dispatch isolation — each agent's router only sees updates
polled by its own bot.

Live-VPS regression: when Tyrion was added to user-gateway alongside Leto,
Tyrion's text messages were silently swallowed by Leto's router. aiogram's
``Dispatcher.start_polling(*bots)`` walks routers in include order; the
first router whose handler matches wins, even if the handler returns None.
Without a per-bot filter, Leto's ``@router.message(F.text)`` matched
EVERY text update — including Tyrion's — and rejected them all (because
Leto's _accept returns False on thread=318).

Fix in ``attach_to_dispatcher``: ``router.message.filter(F.bot.id == bot.id)``.
Each router now ignores updates from other bots, dispatch flow continues
to the next router which is the correct owner.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCER_PY = REPO_ROOT / "gateway" / "src" / "agent_gateway" / "tg" / "producer.py"


def test_attach_to_dispatcher_applies_per_bot_filter() -> None:
    """Static check on the source: every event-type filter is set up so
    routers don't trample each other across bots."""
    src = PRODUCER_PY.read_text(encoding="utf-8")
    # Function in question.
    assert "def attach_to_dispatcher(" in src
    # Must filter at least messages and callback queries by bot.id.
    assert "router.message.filter(F.bot.id == bot.id)" in src
    assert "router.callback_query.filter(F.bot.id == bot.id)" in src


def test_attach_to_dispatcher_filter_runs_before_include_router() -> None:
    """Filters must be applied BEFORE include_router — once the router is
    attached its filters are frozen for that dispatcher's matching pass.
    Setting filters post-attach is a no-op."""
    src = PRODUCER_PY.read_text(encoding="utf-8")
    # Find the function body and look at line ordering.
    func_start = src.find("def attach_to_dispatcher(")
    assert func_start != -1
    func_text = src[func_start:src.find("\n\n\n", func_start)]
    filter_pos = func_text.find("router.message.filter")
    include_pos = func_text.find("dp.include_router")
    assert filter_pos != -1 and include_pos != -1
    assert filter_pos < include_pos, (
        "router.message.filter must be set BEFORE dp.include_router "
        "(filters set after attach are ignored on the matching pass)"
    )


def test_attach_to_dispatcher_filter_signature_uses_F_dot_bot() -> None:
    """The filter expression must use aiogram's magic-filter syntax, not
    a Python lambda — only the ``F`` object survives serialization into
    aiogram's filter chain."""
    from agent_gateway.tg.producer import attach_to_dispatcher

    src = inspect.getsource(attach_to_dispatcher)
    # Must use F.bot.id form, not lambda message: message.bot.id.
    assert "F.bot.id" in src
    assert "lambda" not in src.lower(), (
        "Use F.bot.id == bot.id — lambdas won't survive aiogram's filter "
        "serialization"
    )


def test_diagnostic_log_lines_removed() -> None:
    """The TEMP DIAGNOSTIC log lines we added during the bug hunt should
    be gone — they clutter steady-state logs and were only there to
    surface the multi-bot issue."""
    src = PRODUCER_PY.read_text(encoding="utf-8")
    assert "TEMP DIAGNOSTIC" not in src
    assert "REJECTED by _accept" not in src


@pytest.mark.parametrize("event_type", ["message", "callback_query", "edited_message"])
def test_filter_covers_all_event_types_we_use(event_type: str) -> None:
    """If we ever wire a handler on a new event type (like ``inline_query``
    or ``poll_answer``), it must also be filtered to its bot."""
    src = PRODUCER_PY.read_text(encoding="utf-8")
    assert f"router.{event_type}.filter(F.bot.id == bot.id)" in src, (
        f"router.{event_type}.filter missing — multi-bot dispatch will leak"
    )
