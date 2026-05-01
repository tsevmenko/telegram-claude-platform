"""Tests for v0.4.3 — Playwright MCP, Anthropic skill-creator skill,
web-fetch-discipline rules.

Live regression that motivated this release: Tyrion (2026-05-01) used the
built-in WebFetch on a SPA (course.u10.studio) and got 794 bytes of empty
<div id="root"> shell. He concluded "we need Playwright" — but the
markdown-extract skill (already in his workspace) wraps Jina Reader which
DOES handle SPA via server-side headless browser. Operator confirmed Jina
returns full 12 KB markdown on the same URL.

This release does three things:
1. Bundles Anthropic's skill-creator (Apache 2.0) for skill validation/evals.
2. Installs Playwright + @playwright/mcp system-wide on the VPS, registered
   in both /root/.claude/mcp.json and /home/agent/.claude/mcp.json so all
   four agents get mcp__playwright__* tools.
3. Bakes a permanent web-fetch-tool-selection rule into CLAUDE.md.tmpl
   and rules.md.tmpl, plus a `web-fetch-discipline` skill that documents
   the decision tree (Jina default → Playwright fallback → WebFetch only
   for static HTML).

These tests pin all three layers so a future refactor doesn't quietly
revert them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WSP_TEMPLATE = REPO_ROOT / "workspace-template"


# ---------------------------------------------------------------------------
# (1) Anthropic skill-creator vendored
# ---------------------------------------------------------------------------


def test_skill_creator_bundled() -> None:
    sc = WSP_TEMPLATE / "skills" / "skill-creator"
    assert (sc / "SKILL.md").is_file()
    text = (sc / "SKILL.md").read_text()
    assert "name: skill-creator" in text
    assert "Anthropic" in text or "anthropic" in text.lower() or "Apache" in text \
        or (sc / "LICENSE.txt").is_file()


def test_skill_creator_license_preserved() -> None:
    """Apache 2.0 requires LICENSE preservation."""
    sc = WSP_TEMPLATE / "skills" / "skill-creator"
    license_file = sc / "LICENSE.txt"
    assert license_file.is_file(), "LICENSE.txt must be preserved (Apache 2.0)"
    text = license_file.read_text()
    assert "Apache License" in text
    assert "Version 2.0" in text


def test_skill_creator_has_validators() -> None:
    """skill-creator brings runnable scripts (quick_validate, run_eval, etc.)
    — the whole point of using the official one over a hand-rolled validator."""
    scripts = WSP_TEMPLATE / "skills" / "skill-creator" / "scripts"
    assert (scripts / "quick_validate.py").is_file(), \
        "quick_validate.py must be present — agents need it for SKILL.md linting"
    assert (scripts / "run_eval.py").is_file(), \
        "run_eval.py must be present — eval-runner is the value-add over hand-rolled"


# ---------------------------------------------------------------------------
# (2) web-fetch-discipline skill
# ---------------------------------------------------------------------------


def test_web_fetch_discipline_skill_present() -> None:
    sd = WSP_TEMPLATE / "skills" / "web-fetch-discipline"
    assert (sd / "SKILL.md").is_file()
    text = (sd / "SKILL.md").read_text()
    assert text.startswith("---\n")
    assert "name: web-fetch-discipline" in text
    assert "user-invocable: true" in text


def test_web_fetch_discipline_documents_three_tiers() -> None:
    text = (WSP_TEMPLATE / "skills" / "web-fetch-discipline" / "SKILL.md").read_text()
    # Must explain all three fetch paths so the agent picks deterministically.
    assert "markdown-extract" in text
    assert "playwright" in text.lower() or "Playwright" in text
    assert "WebFetch" in text
    # The "tried first" line must be unambiguous: Jina is default.
    assert "default" in text.lower()
    assert "Jina" in text or "r.jina.ai" in text


def test_web_fetch_discipline_explains_spa_failure_mode() -> None:
    """Future agents need to understand WHY this rule exists, not just what
    to do. Live regression must be in the file."""
    text = (WSP_TEMPLATE / "skills" / "web-fetch-discipline" / "SKILL.md").read_text()
    assert "SPA" in text or "JavaScript" in text or "JS" in text
    assert "shell" in text.lower() or "empty" in text.lower()


# ---------------------------------------------------------------------------
# (3) CLAUDE.md.tmpl + rules.md.tmpl encode the rules
# ---------------------------------------------------------------------------


def test_workspace_claude_md_has_web_fetching_section() -> None:
    text = (WSP_TEMPLATE / "CLAUDE.md.tmpl").read_text()
    assert "## Web fetching" in text or "Web Fetching" in text
    assert "markdown-extract" in text
    assert "WebFetch" in text
    assert "playwright" in text.lower()


def test_workspace_claude_md_has_skill_creation_section() -> None:
    text = (WSP_TEMPLATE / "CLAUDE.md.tmpl").read_text()
    assert "## Skill creation" in text or "skill-creator" in text


def test_rules_md_has_web_fetch_rule() -> None:
    text = (WSP_TEMPLATE / "core" / "rules.md.tmpl").read_text()
    assert "Web fetching" in text or "web fetching" in text.lower()
    assert "markdown-extract" in text


def test_rules_md_has_skill_creation_rule() -> None:
    text = (WSP_TEMPLATE / "core" / "rules.md.tmpl").read_text()
    assert "skill-creator" in text or "Skill creation" in text


# ---------------------------------------------------------------------------
# (4) Installer step 72-playwright + register helper
# ---------------------------------------------------------------------------


def test_installer_step_72_playwright_exists() -> None:
    p = REPO_ROOT / "installer" / "lib" / "72-playwright.sh"
    assert p.is_file()
    text = p.read_text()
    assert "step_main()" in text
    assert "@playwright/mcp" in text
    # Step must drive `playwright install chromium` somewhere — the exact
    # invocation can be either `npx playwright install chromium` or
    # `<path>/playwright" install chromium`, so we just check the install
    # action is invoked.
    assert "install chromium" in text
    assert "register_playwright_mcp_for" in text
    # Must register MCP for both root and agent users.
    assert "register_playwright_mcp_for root" in text
    assert "register_playwright_mcp_for agent" in text


def test_install_sh_registers_step_72() -> None:
    text = (REPO_ROOT / "install.sh").read_text()
    assert "72-playwright" in text
    # Order matters: must come AFTER 70-openviking (so MCP merging is sane)
    # and BEFORE 99-self-check.
    seventy_idx = text.find("70-openviking")
    seventy_two_idx = text.find("72-playwright")
    self_check_idx = text.find("99-self-check")
    assert 0 < seventy_idx < seventy_two_idx < self_check_idx


def test_installer_step_72_uses_shared_browsers_path() -> None:
    """Sharing the Chromium binary between root + agent users (instead of
    each having its own ~600 MB cache) requires PLAYWRIGHT_BROWSERS_PATH
    pointing at /opt/playwright/browsers. Test pins this."""
    text = (REPO_ROOT / "installer" / "lib" / "72-playwright.sh").read_text()
    assert "PLAYWRIGHT_BROWSERS_PATH" in text
    assert "/opt/playwright/browsers" in text


# ---------------------------------------------------------------------------
# (5) Sanity — skill-creator reaches every workspace via deploy_skills mech
# (workspace-template/skills/* gets rsync'd by installer's plant_workspace
# AND by Vesna's add_agent — both already work; we just verify presence.)
# ---------------------------------------------------------------------------


def test_skill_creator_in_workspace_template() -> None:
    """Vesna's add_agent rsync's workspace-template into new agents'
    workspace. Make sure skill-creator is there to be carried."""
    p = WSP_TEMPLATE / "skills" / "skill-creator" / "SKILL.md"
    assert p.is_file()


def test_web_fetch_discipline_in_workspace_template() -> None:
    p = WSP_TEMPLATE / "skills" / "web-fetch-discipline" / "SKILL.md"
    assert p.is_file()
