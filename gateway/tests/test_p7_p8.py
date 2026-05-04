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


def test_instagram_skill_no_longer_stub() -> None:
    """v0.4.5: stub graduated. Tyrion built a fully working
    ScrapeCreators-backed skill on his VPS (analyze.sh, bulk-fetch.sh,
    posts-fetch.sh, reel-details.sh, fetch-author-week.sh). We pulled
    the working skill into source control. The frontmatter must NOT
    advertise status:stub anymore — it would mislead the agent."""
    skill_md = SKILLS_DIR / "instagram-analytics" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert "status: stub" not in text, (
        "skill is no longer a stub; remove the marker from frontmatter"
    )
    # Real skill must list actual scripts that exist.
    scripts_dir = SKILLS_DIR / "instagram-analytics" / "scripts"
    for must_exist in ("bulk-fetch.sh", "analyze.sh", "reel-details.sh"):
        assert (scripts_dir / must_exist).is_file(), (
            f"{must_exist} missing — skill incomplete"
        )


def test_instagram_skill_documents_scope_limits() -> None:
    """The skill must surface what it CAN'T do so an over-eager Claude
    doesn't promise things ScrapeCreators's IG endpoints can't deliver
    (private profiles, stories, hashtag aggregation, etc.). Pulled from
    Tyrion's hand-written 'What this skill does NOT do' section."""
    skill_md = SKILLS_DIR / "instagram-analytics" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8").lower()
    assert "does not" in text or "cannot" in text or "no login" in text, (
        "skill must declare its capability boundaries"
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
