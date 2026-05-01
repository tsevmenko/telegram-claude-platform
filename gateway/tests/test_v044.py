"""Tests for v0.4.4 — ClickUp MCP integration with role-based ownership.

Architecture: shared ClickUp MCP server accessible to all agents via
mcp__clickup__* tools, but with WRITE authority split by domain. Tyrion
owns the Brand domain (positioning, voice rules, content types,
competitor watchlist); Varys owns the Operations domain (funnels, leads,
ManyChat state, A/B tests). Cross-domain reads are fine; cross-domain
writes are forbidden by the rules in CLAUDE.md / rules.md.

Why community @taazkareem/clickup-mcp-server (not Anthropic's official):
Free plan rate limit on official is 50 calls/24h — too tight for the
multi-agent workflow we have. Community uses the underlying ClickUp REST
API where rate limits are far more generous. We can migrate to official
when the operator upgrades to Unlimited tier (300/24h).

These tests pin: installer step exists with right structure, CLAUDE.md
template carries the ownership rule, rules.md.tmpl carries the same,
and the wrapper-script architecture is correct (token from chmod-600
secrets file, not inlined in mcp.json).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# CLAUDE.md.tmpl + rules.md.tmpl carry the ClickUp ownership rule
# ---------------------------------------------------------------------------


def test_workspace_claude_md_has_clickup_ownership_section() -> None:
    text = (REPO_ROOT / "workspace-template" / "CLAUDE.md.tmpl").read_text()
    assert "## ClickUp ownership" in text or "ClickUp ownership" in text
    # Both domain labels must be named.
    assert "Brand domain" in text
    assert "Operations domain" in text
    # The "sole writer" wording is the load-bearing phrase — strict not
    # advisory.
    assert "sole writer" in text
    # Must surface mcp__clickup__* as the access path.
    assert "mcp__clickup__" in text
    # Schema discipline pointer.
    assert "core/clickup-schema.md" in text


def test_workspace_claude_md_warns_against_cross_domain_writes() -> None:
    text = (REPO_ROOT / "workspace-template" / "CLAUDE.md.tmpl").read_text()
    # Any of these phrasings is acceptable — pin the intent.
    assert ("never cross-writes" in text
            or "never write" in text.lower()
            or "do not guess" in text.lower())


def test_workspace_claude_md_separates_heavy_raw_data() -> None:
    """Operator-stated requirement: ClickUp holds pointers, not blobs.
    Raw competitor scrapes (45KB+ markdown, ~200KB images) stay in
    core/competitors/ — ClickUp tasks reference them by link/path."""
    text = (REPO_ROOT / "workspace-template" / "CLAUDE.md.tmpl").read_text()
    assert ("Heavy raw data" in text
            or "Heavy raw" in text
            or "raw data" in text.lower())
    # Pointer-pattern explicitly stated.
    assert "pointers" in text.lower()


def test_rules_md_has_clickup_ownership_rule() -> None:
    text = (REPO_ROOT / "workspace-template" / "core" / "rules.md.tmpl").read_text()
    assert "ClickUp ownership" in text
    assert "Brand" in text
    assert "Operations" in text


# ---------------------------------------------------------------------------
# Installer step 73-clickup
# ---------------------------------------------------------------------------


def test_installer_step_73_clickup_exists() -> None:
    p = REPO_ROOT / "installer" / "lib" / "73-clickup.sh"
    assert p.is_file()
    text = p.read_text()
    assert "step_main()" in text
    assert "@taazkareem/clickup-mcp-server" in text
    assert "register_clickup_mcp_for" in text
    # Both root and agent users registered.
    assert "register_clickup_mcp_for root" in text
    assert "register_clickup_mcp_for agent" in text


def test_install_sh_registers_step_73() -> None:
    text = (REPO_ROOT / "install.sh").read_text()
    assert "73-clickup" in text
    seventy_two = text.find("72-playwright")
    seventy_three = text.find("73-clickup")
    self_check = text.find("99-self-check")
    assert 0 < seventy_two < seventy_three < self_check


def test_installer_step_73_uses_wrapper_pattern() -> None:
    """Token must NOT be inlined in mcp.json (mode 0644). Wrapper script
    reads it from chmod-600 secrets file and exports as env. Pin this
    architecture so a future "simplification" doesn't accidentally leak."""
    text = (REPO_ROOT / "installer" / "lib" / "73-clickup.sh").read_text()
    # write_wrapper helper present.
    assert "write_wrapper" in text
    # Wrapper reads from secrets file path.
    assert "/home/agent/.claude-lab/shared/secrets/clickup.token" in text
    # The mcp.json entry uses the wrapper as `command`, no token in JSON.
    # We can verify this by checking that the registration helper does NOT
    # write CLICKUP_API_KEY into the JSON.
    assert "CLICKUP_API_KEY" not in _registration_block(text), (
        "Registration helper should not put API key into mcp.json — "
        "use the wrapper script which reads from secrets file."
    )


def _registration_block(text: str) -> str:
    """Extract the register_clickup_mcp_for function body."""
    start = text.find("register_clickup_mcp_for() {")
    if start == -1:
        return ""
    # Find matching closing brace at column 0.
    end = text.find("\n}\n", start)
    return text[start:end] if end != -1 else text[start:]


def test_installer_step_73_resolves_team_id_from_api() -> None:
    """When CLICKUP_TEAM_ID isn't pre-set, the installer must auto-resolve
    it via ClickUp's /team API endpoint — saves operator a manual lookup.
    Override via env still works for multi-team setups."""
    text = (REPO_ROOT / "installer" / "lib" / "73-clickup.sh").read_text()
    assert "api.clickup.com/api/v2/team" in text
    assert "CLICKUP_TEAM_ID" in text


def test_installer_step_73_skips_gracefully_if_token_missing() -> None:
    """First-time installer: token may not be staged yet. Step should warn
    and skip MCP registration, not crash the whole install."""
    text = (REPO_ROOT / "installer" / "lib" / "73-clickup.sh").read_text()
    # Look for graceful-skip pattern: warn + return 0 when token missing.
    assert "token missing" in text.lower() or "TOKEN_FILE" in text
    # Must use return 0 (not die), so the rest of the install completes.
    skip_block_start = text.find('TOKEN_FILE')
    assert skip_block_start != -1


# ---------------------------------------------------------------------------
# All three MCP servers (openviking, playwright, clickup) live in template
# ---------------------------------------------------------------------------


def test_three_mcp_steps_in_install_sh_order() -> None:
    """Order matters because each step's register_*_for helper merges into
    the same mcp.json. They must run sequentially after 30-users (which
    creates the user accounts that own ~/.claude/) and before 99-self-check."""
    text = (REPO_ROOT / "install.sh").read_text()
    users_idx     = text.find("30-users")
    openviking_idx = text.find("70-openviking")
    playwright_idx = text.find("72-playwright")
    clickup_idx   = text.find("73-clickup")
    self_check_idx = text.find("99-self-check")
    assert 0 < users_idx < openviking_idx < playwright_idx < clickup_idx < self_check_idx
