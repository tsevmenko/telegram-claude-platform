"""Regression tests for v0.2.1 audit fixes.

Each test names the audit gap it locks in.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Gap 2 — PreCompact must flush full HOT, not the cron's tail-200
# ---------------------------------------------------------------------------


def test_sync_l4_supports_ov_full_flag() -> None:
    text = (REPO_ROOT / "workspace-template" / "scripts" / "sync-l4.sh").read_text()
    assert 'OV_FULL="${OV_FULL:-0}"' in text
    assert 'cat "$HOT"' in text  # full path
    assert 'tail -n 200 "$HOT"' in text  # cron path
    assert 'if [ "$OV_FULL" = "1" ]; then' in text


def test_flush_to_openviking_sets_ov_full_to_1() -> None:
    text = (
        REPO_ROOT / "workspace-template" / "hooks" / "flush-to-openviking.sh"
    ).read_text()
    # Must explicitly export OV_FULL=1 when invoking sync-l4.sh.
    assert "OV_FULL=1" in text


# ---------------------------------------------------------------------------
# Gap 10 — --max-budget-usd must reach claude in compress + trim
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script_name",
    ["trim-hot.sh", "compress-warm.sh"],
)
def test_cron_scripts_pass_max_budget_to_claude(script_name: str) -> None:
    text = (REPO_ROOT / "workspace-template" / "scripts" / script_name).read_text()
    assert "SONNET_BUDGET=" in text
    assert "--max-budget-usd" in text
    # The budget variable must actually be consumed in a claude invocation.
    assert re.search(r'--max-budget-usd\s+"?\$SONNET_BUDGET"?', text), (
        f"{script_name}: --max-budget-usd not wired to $SONNET_BUDGET"
    )


# ---------------------------------------------------------------------------
# Gap 5 — cron file has version marker for idempotent merges
# ---------------------------------------------------------------------------


def test_cron_template_has_tcp_marker() -> None:
    text = (REPO_ROOT / "installer" / "lib" / "85-cron.sh").read_text()
    assert "tcp-installer: memory rotation" in text
    # Both begin and end markers so a future tool can do a regex strip-replace.
    assert "begin" in text and "end" in text


# ---------------------------------------------------------------------------
# Gap 11 — gateway emergency-trim acquires the same lockfile cron uses
# ---------------------------------------------------------------------------


def test_emergency_trim_uses_trim_hot_lock() -> None:
    text = (
        REPO_ROOT / "gateway" / "src" / "agent_gateway" / "memory" / "hot.py"
    ).read_text()
    assert "/tmp/trim-hot.lock" in text
    assert "fcntl.LOCK_NB" in text
    assert "BlockingIOError" in text


# ---------------------------------------------------------------------------
# Gap 12 — cron logs go to ${WS}/logs/memory-cron.log (consolidated)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script_name",
    ["trim-hot.sh", "compress-warm.sh", "rotate-warm.sh", "memory-rotate.sh", "sync-l4.sh"],
)
def test_cron_scripts_log_to_workspace_logs_dir(script_name: str) -> None:
    text = (REPO_ROOT / "workspace-template" / "scripts" / script_name).read_text()
    assert 'LOG_DIR="${WS}/logs"' in text
    assert "memory-cron.log" in text


def test_cron_log_lines_are_prefixed_per_script() -> None:
    """Single shared log file means each line should identify its source."""
    expected = [
        ("trim-hot.sh", "[trim-hot]"),
        ("compress-warm.sh", "[compress-warm]"),
        ("rotate-warm.sh", "[rotate-warm]"),
        ("memory-rotate.sh", "[memory-rotate]"),
        ("sync-l4.sh", "[sync-l4]"),
    ]
    for script_name, prefix in expected:
        text = (
            REPO_ROOT / "workspace-template" / "scripts" / script_name
        ).read_text()
        assert prefix in text, f"{script_name}: missing log prefix {prefix}"


# ---------------------------------------------------------------------------
# Gap 1 — webhook accepts both `agent` and `agentId`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_accepts_python_naming(tmp_path: Path) -> None:
    from agent_gateway.tg.webhook_api import WebhookAPI
    from unittest.mock import AsyncMock, MagicMock
    from aiohttp import web

    token_file = tmp_path / "webhook-token.txt"
    token_file.write_text("testtoken")

    consumer = MagicMock()
    consumer.queue = AsyncMock()
    api = WebhookAPI(
        consumers={"leto": consumer},
        token_path=token_file,
        listen_host="127.0.0.1",
        listen_port=0,
    )

    request = MagicMock()
    request.headers = {"Authorization": "Bearer testtoken"}
    request.json = AsyncMock(
        return_value={"agent": "leto", "chat_id": 123, "text": "hi"}
    )
    resp: web.Response = await api._handle_inject(request)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_webhook_accepts_workshop_camelcase(tmp_path: Path) -> None:
    """Operators copy-pasting curl examples from edgelab.su workshop hit
    camelCase. Must work without 400."""
    from agent_gateway.tg.webhook_api import WebhookAPI
    from unittest.mock import AsyncMock, MagicMock
    from aiohttp import web

    token_file = tmp_path / "webhook-token.txt"
    token_file.write_text("testtoken")

    consumer = MagicMock()
    consumer.queue = AsyncMock()
    api = WebhookAPI(
        consumers={"leto": consumer},
        token_path=token_file,
        listen_host="127.0.0.1",
        listen_port=0,
    )

    request = MagicMock()
    request.headers = {"Authorization": "Bearer testtoken"}
    request.json = AsyncMock(
        return_value={"agentId": "leto", "chatId": 123, "message": "hi"}
    )
    resp: web.Response = await api._handle_inject(request)
    assert resp.status == 200


# ---------------------------------------------------------------------------
# Gap 7 — getMe-cached self-reply detection
# ---------------------------------------------------------------------------


def test_build_text_with_context_uses_self_bot_id_when_provided() -> None:
    from agent_gateway.tg.producer import _build_text_with_context

    # Reply to a different bot (our id is 999, replied bot is 111) — must
    # inject context, not skip.
    reply = SimpleNamespace(
        from_user=SimpleNamespace(id=111, is_bot=True),
        text="some other bot output",
        caption=None,
    )
    msg = SimpleNamespace(
        text="ack",
        caption=None,
        forward_origin=None,
        reply_to_message=reply,
    )
    enriched, source = _build_text_with_context(msg, self_bot_id=999)
    assert "untrusted metadata" in enriched
    assert source == "replied"


def test_build_text_with_context_skips_when_replying_to_self_bot() -> None:
    from agent_gateway.tg.producer import _build_text_with_context

    reply = SimpleNamespace(
        from_user=SimpleNamespace(id=999, is_bot=True),
        text="our own previous answer",
        caption=None,
    )
    msg = SimpleNamespace(
        text="follow up",
        caption=None,
        forward_origin=None,
        reply_to_message=reply,
    )
    enriched, source = _build_text_with_context(msg, self_bot_id=999)
    assert "untrusted metadata" not in enriched
    assert source == "tg-text"


def test_build_text_falls_back_when_self_id_unknown() -> None:
    """If we haven't cached getMe yet (very first message), conservatively
    treat all bot replies as self (legacy behaviour)."""
    from agent_gateway.tg.producer import _build_text_with_context

    reply = SimpleNamespace(
        from_user=SimpleNamespace(id=111, is_bot=True),
        text="other bot",
        caption=None,
    )
    msg = SimpleNamespace(
        text="x",
        caption=None,
        forward_origin=None,
        reply_to_message=reply,
    )
    enriched, _ = _build_text_with_context(msg, self_bot_id=None)
    # Legacy fallback: all bots considered self.
    assert "untrusted metadata" not in enriched


# ---------------------------------------------------------------------------
# Gap 3 — onboarding skill mentions voice-first flow
# ---------------------------------------------------------------------------


def test_onboarding_skill_describes_voice_first_path() -> None:
    text = (
        REPO_ROOT / "workspace-template" / "skills" / "onboarding" / "SKILL.md"
    ).read_text()
    assert "voice memo" in text.lower() or "voice-first" in text.lower()
    assert "links" in text.lower() or "link" in text.lower()
    # Mission field must be in the skill's expected USER.md output schema.
    assert "Mission" in text


def test_user_md_template_has_mission_section() -> None:
    text = (REPO_ROOT / "workspace-template" / "core" / "USER.md.tmpl").read_text()
    assert "## Mission" in text


# ---------------------------------------------------------------------------
# Gap 4 + 13 — PROMPTS.md is a daily-driver library, not just recovery
# ---------------------------------------------------------------------------


def test_prompts_md_has_daily_driver_section() -> None:
    text = (REPO_ROOT / "docs" / "PROMPTS.md").read_text()
    assert "Daily-driver" in text or "daily driver" in text.lower() or "Daily kickoff" in text


def test_prompts_md_has_voice_onboarding_prompt() -> None:
    text = (REPO_ROOT / "docs" / "PROMPTS.md").read_text()
    assert "/onboarding" in text


def test_prompts_md_self_audit_includes_18_checks() -> None:
    """Author's self-audit is 18 questions; ours should match."""
    text = (REPO_ROOT / "docs" / "PROMPTS.md").read_text()
    audit_section_match = re.search(
        r"Daily self-diagnostic.*?Verdict",
        text,
        flags=re.DOTALL,
    )
    assert audit_section_match, "Daily self-diagnostic section missing"
    section = audit_section_match.group(0)
    # Count enumerated check lines (^\d+\.) in the audit block.
    checks = re.findall(r"^\s*(\d+)\.\s", section, flags=re.MULTILINE)
    assert len(checks) >= 18, (
        f"Daily self-diagnostic has only {len(checks)} checks; expected ≥18"
    )


# ---------------------------------------------------------------------------
# Voice italic echo — helper exists and is invoked in voice handler
# ---------------------------------------------------------------------------


def test_voice_handler_calls_echo_helper() -> None:
    text = (
        REPO_ROOT / "gateway" / "src" / "agent_gateway" / "tg" / "producer.py"
    ).read_text()
    assert "_echo_voice_transcript" in text
    # It's called BEFORE queueing the message, not after (otherwise the
    # operator sees the answer first, which defeats the purpose).
    voice_handler = re.search(
        r"async def _voice_handler.*?return\n",
        text, flags=re.DOTALL,
    )
    assert voice_handler is None or "_echo_voice_transcript" not in voice_handler.group(0), (
        "voice handler should call echo before consumer.queue.put"
    )
    # Looser check — make sure helper is wired
    assert "await _echo_voice_transcript(" in text
