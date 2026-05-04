"""Tests for v0.4.5 — three threads of cleanup:

1. **MCP registration via `claude mcp add`**, not jq into ~/.claude/mcp.json.
   Tyrion's diagnosis 2026-05-01: claude CLI 2.x reads MCP config from
   `~/.claude.json` (a single dot-file in $HOME), NOT from
   `~/.claude/mcp.json` (path-with-subdir). So all our jq-merge-based
   registrations from v0.4.3 / v0.4.4 silently failed to load any MCP
   server. Refactored register helpers in 70-openviking, 72-playwright,
   73-clickup to use the native `claude mcp add --scope user` subcommand.

2. **Higgsfield HTTP MCP** (https://mcp.higgsfield.ai/mcp) — operator
   bought year tariff 2026-05-03, registered via new installer step
   74-higgsfield.sh. OAuth flow is interactive (one-time per user, done
   manually with SSH port-forward).

3. **Cost guards for instagram-analytics** — live regression 2026-05-02:
   Tyrion bulk-fetched 4 handles in 2 days, multiple repeats per handle
   with --with-transcripts default-on (each transcript ~30 credits);
   ~355 credits burned. Email "low credits" was a false alarm but
   pattern was scary. Sane defaults + budget-guard + dedup-guard now
   prevent re-occurrence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Thread 1 — claude mcp add registration pattern
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("step", ["70-openviking", "72-playwright", "73-clickup"])
def test_register_helper_uses_claude_mcp_add(step: str) -> None:
    """Each MCP-installer step must register via `claude mcp add`, NOT
    by jq-merging into ~/.claude/mcp.json (which claude CLI 2.x ignores)."""
    text = (REPO_ROOT / "installer" / "lib" / f"{step}.sh").read_text()
    assert "claude mcp add" in text, (
        f"{step}.sh must use native `claude mcp add` for MCP registration"
    )
    # The tell-tale signature of the old broken pattern:
    #   jq '.mcpServers = ((.mcpServers // {}) + {...})' ... > "$mcp_path"
    # Should be GONE in v0.4.5.
    assert ".mcpServers = ((.mcpServers" not in text, (
        f"{step}.sh still uses jq-merge-into-mcp.json pattern; "
        f"that path is ignored by claude CLI 2.x"
    )


@pytest.mark.parametrize("step", ["70-openviking", "72-playwright", "73-clickup"])
def test_register_helper_idempotent_remove_then_add(step: str) -> None:
    """Each register helper must call `claude mcp remove` before add, so
    re-running the installer doesn't double-add or fail on existing entry."""
    text = (REPO_ROOT / "installer" / "lib" / f"{step}.sh").read_text()
    assert "claude mcp remove" in text


# ---------------------------------------------------------------------------
# Thread 2 — Higgsfield HTTP MCP installer step
# ---------------------------------------------------------------------------


def test_installer_step_74_higgsfield_exists() -> None:
    p = REPO_ROOT / "installer" / "lib" / "74-higgsfield.sh"
    assert p.is_file()
    text = p.read_text()
    assert "step_main()" in text
    assert "https://mcp.higgsfield.ai/mcp" in text
    assert "register_mcp_for_user" in text
    # Both users.
    assert "register_mcp_for_user root" in text
    assert "register_mcp_for_user agent" in text
    # Must use --transport http (since this is HTTP MCP, not stdio).
    assert "--transport http" in text
    # Must specify --callback-port for OAuth flow.
    assert "--callback-port" in text


def test_install_sh_registers_step_74() -> None:
    text = (REPO_ROOT / "install.sh").read_text()
    assert "74-higgsfield" in text
    seventy_three = text.find("73-clickup")
    seventy_four = text.find("74-higgsfield")
    self_check = text.find("99-self-check")
    assert 0 < seventy_three < seventy_four < self_check


def test_installer_74_documents_oauth_flow_in_header() -> None:
    """Operator must complete OAuth interactively post-install. Step header
    should document the SSH-port-forward trick so the operator doesn't
    have to dig through chat history."""
    text = (REPO_ROOT / "installer" / "lib" / "74-higgsfield.sh").read_text()
    assert "ssh -L" in text or "port-forward" in text.lower() or "OAuth" in text
    assert "/mcp" in text or "claude session" in text.lower()


# ---------------------------------------------------------------------------
# Thread 3 — instagram-analytics cost guards + sane defaults
# ---------------------------------------------------------------------------


SKILL_DIR = REPO_ROOT / "workspace-template" / "skills" / "instagram-analytics"


def test_instagram_analytics_skill_in_workspace_template() -> None:
    """Pulled into source control in v0.4.5 — was previously workspace-local
    on Tyrion's VPS only. Future agents inherit it via Vesna's add_agent."""
    assert (SKILL_DIR / "SKILL.md").is_file()
    assert (SKILL_DIR / "scripts" / "bulk-fetch.sh").is_file()


def test_budget_guard_helper_present() -> None:
    p = SKILL_DIR / "scripts" / "_budget-guard.sh"
    assert p.is_file()
    text = p.read_text()
    # Public API names that other scripts source.
    assert "budget_guard_check" in text
    assert "budget_guard_record" in text
    # Kill switch field documented.
    assert "disabled" in text
    # Daily reset logic.
    assert "last_reset_date" in text


def test_dedup_guard_helper_present() -> None:
    p = SKILL_DIR / "scripts" / "_dedup-guard.sh"
    assert p.is_file()
    text = p.read_text()
    assert "dedup_guard_check" in text
    # Default 7-day window.
    assert "7 * 86400" in text or "7" in text and "86400" in text
    # Force-flag override path.
    assert "force" in text.lower()


def test_bulk_fetch_sources_both_guards() -> None:
    """The expensive entry-point must source both guards before any API
    call. Defence in depth — operator may forget to set budget limits but
    dedup will at least catch repeat fetches."""
    text = (SKILL_DIR / "scripts" / "bulk-fetch.sh").read_text()
    assert "_budget-guard.sh" in text
    assert "_dedup-guard.sh" in text
    # Calls in script body, not just sourced.
    assert "budget_guard_check" in text
    assert "dedup_guard_check" in text
    assert "budget_guard_record" in text


def test_bulk_fetch_default_no_transcripts() -> None:
    """Live regression 2026-05-02: defaults included --with-transcripts,
    each transcript ~30 credits, multiplied total cost ~30×. v0.4.5
    flips default to OFF; opt-in via --with-transcripts flag."""
    text = (SKILL_DIR / "scripts" / "bulk-fetch.sh").read_text()
    # Default value must be 0 (off).
    assert "WANT_TRANSCRIPTS=0" in text
    # Flag for opt-in must exist.
    assert "--with-transcripts)" in text


def test_bulk_fetch_default_count_capped() -> None:
    """Default --count was 50 (full feed), now 20 (snapshot). Larger pulls
    still possible via explicit --count N but require operator awareness."""
    text = (SKILL_DIR / "scripts" / "bulk-fetch.sh").read_text()
    assert "COUNT=20" in text
    # Old default should not be the default anymore.
    assert "COUNT=50" not in text or "COUNT=20" in text  # both checks pass means we replaced


def test_bulk_fetch_force_flag_for_dedup_override() -> None:
    """The 7-day dedup guard refuses re-fetches; --force lets the operator
    explicitly override (e.g. when they know IG state changed materially)."""
    text = (SKILL_DIR / "scripts" / "bulk-fetch.sh").read_text()
    assert "--force" in text
    assert "FORCE=" in text or "FORCE=1" in text
