"""Tests for Phase 7 (Superpowers + Instagram-analytics) and Phase 8 (3rd OAuth doc)."""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGINS_INSTALLER = REPO_ROOT / "installer" / "lib" / "55-plugins.sh"
PINS = REPO_ROOT / "installer" / "PINS"
PINS_REPOS = REPO_ROOT / "installer" / "PINS.repos"
SKILLS_DIR = REPO_ROOT / "workspace-template" / "skills"
ADD_NEW_AGENT_DOC = REPO_ROOT / "docs" / "ADD-NEW-AGENT.md"


# ---------------------------------------------------------------------------
# P7.6 — 55-plugins.sh executable + sha-pinned + sane PINS entry
# ---------------------------------------------------------------------------


def test_plugins_installer_is_executable() -> None:
    """An installer step that isn't +x silently no-ops on most systems."""
    mode = PLUGINS_INSTALLER.stat().st_mode
    assert mode & 0o100, f"{PLUGINS_INSTALLER.name}: not chmod +x"


def test_plugins_installer_pins_a_specific_sha() -> None:
    text = PLUGINS_INSTALLER.read_text(encoding="utf-8")
    m = re.search(r"SUPERPOWERS_SHA=\"?([0-9a-f]{40})\"?", text)
    assert m, "55-plugins.sh must hard-code a 40-char SUPERPOWERS_SHA"


def test_plugins_sha_matches_pins_file() -> None:
    """The SHA in 55-plugins.sh must equal SUPERPOWERS_SHA in PINS so a bump
    in one place is visible to verify_pins. Drift here is silent and dangerous."""
    plugin_text = PLUGINS_INSTALLER.read_text(encoding="utf-8")
    pins_text = PINS.read_text(encoding="utf-8")

    plugin_match = re.search(r"SUPERPOWERS_SHA=\"?([0-9a-f]{40})\"?", plugin_text)
    pins_match = re.search(
        r"^\s*SUPERPOWERS_SHA=([0-9a-f]{40})", pins_text, flags=re.MULTILINE,
    )
    assert plugin_match, "55-plugins.sh: missing SUPERPOWERS_SHA"
    assert pins_match, "PINS: missing SUPERPOWERS_SHA entry"
    assert plugin_match.group(1) == pins_match.group(1), (
        f"SHA drift: 55-plugins.sh has {plugin_match.group(1)} but PINS has "
        f"{pins_match.group(1)}"
    )


def test_pins_repos_maps_superpowers_sha() -> None:
    repos_text = PINS_REPOS.read_text(encoding="utf-8")
    assert re.search(
        r"^SUPERPOWERS_SHA=pcvelz/superpowers\b",
        repos_text, flags=re.MULTILINE,
    ), "PINS.repos: SUPERPOWERS_SHA must map to pcvelz/superpowers"


def test_plugins_installer_calls_fix_owner_with_correct_signature() -> None:
    """fix_owner takes USER:GROUP first, PATH second. Reverse order silently
    no-ops on the actual chown."""
    text = PLUGINS_INSTALLER.read_text(encoding="utf-8")
    # Match `fix_owner "<user>:<group>" "<path>"` shape.
    assert re.search(r"fix_owner\s+\"\$\{user\}:\$\{user\}\"", text), (
        "55-plugins.sh must call fix_owner with USER:GROUP as first arg"
    )


# ---------------------------------------------------------------------------
# P7-Instagram — stub skill present and well-formed
# ---------------------------------------------------------------------------


def test_instagram_analytics_skill_stub_exists() -> None:
    skill_md = SKILLS_DIR / "instagram-analytics" / "SKILL.md"
    assert skill_md.is_file(), (
        "agent-skills sync should produce workspace-template/skills/instagram-analytics/SKILL.md"
    )


def test_instagram_skill_marked_as_stub() -> None:
    skill_md = SKILLS_DIR / "instagram-analytics" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "status: stub" in text, (
        "Stub skills must self-identify so installers / scanners can filter them"
    )


def test_instagram_skill_does_not_claim_hashtag_support() -> None:
    """ScrapeCreators doesn't have IG hashtag endpoints; the SKILL.md must
    surface that limitation so an over-eager Claude doesn't promise it."""
    skill_md = SKILLS_DIR / "instagram-analytics" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8").lower()
    assert "hashtag" in text and ("doesn't" in text or "don't" in text or "not" in text), (
        "Instagram skill must explicitly disclaim hashtag support"
    )


# ---------------------------------------------------------------------------
# P8 — ADD-NEW-AGENT doc covers 3rd OAuth slot
# ---------------------------------------------------------------------------


def test_add_new_agent_doc_documents_third_oauth_slot() -> None:
    text = ADD_NEW_AGENT_DOC.read_text(encoding="utf-8")
    assert "3rd OAuth slot" in text or "third OAuth" in text.lower()


def test_third_oauth_doc_mentions_anthropic_max_3_token_rule() -> None:
    """The 3-token rule is the architectural fact that justifies the slot."""
    text = ADD_NEW_AGENT_DOC.read_text(encoding="utf-8")
    assert re.search(r"3\s*concurrent\s*OAuth\s*tokens?", text, re.IGNORECASE), (
        "Doc must explain Anthropic Max permits exactly 3 concurrent OAuth tokens"
    )


def test_third_oauth_doc_lists_use_cases() -> None:
    """Concrete examples — readers can pattern-match their need."""
    text = ADD_NEW_AGENT_DOC.read_text(encoding="utf-8").lower()
    has_background = "background" in text or "nightly" in text or "cron" in text
    has_recovery = "recovery" in text or "spare" in text or "wedged" in text
    assert has_background, "Doc must mention background/cron use case"
    assert has_recovery, "Doc must mention recovery/spare use case"


def test_third_oauth_doc_provides_setup_commands() -> None:
    text = ADD_NEW_AGENT_DOC.read_text(encoding="utf-8")
    assert "useradd" in text and "claude login" in text, (
        "Doc must show concrete setup commands (useradd + claude login)"
    )
