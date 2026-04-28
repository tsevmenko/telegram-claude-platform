"""Shape tests for `workspace-template/` and `installer/templates/claude/` files.

These tests are doc-as-config: they assert that templates contain (or don't
contain) specific structural elements that downstream code and Claude rely on.

Catches regressions where someone deletes a critical section (e.g. the four
``@include`` directives, Terse Mode block, neutral operator-address examples).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WSP_CLAUDE_MD = REPO_ROOT / "workspace-template" / "CLAUDE.md.tmpl"
WSP_USER_MD = REPO_ROOT / "workspace-template" / "core" / "USER.md.tmpl"
WSP_RULES_MD = REPO_ROOT / "workspace-template" / "core" / "rules.md.tmpl"
GLOBAL_CLAUDE_MD = (
    REPO_ROOT / "installer" / "templates" / "claude" / "global-CLAUDE.md.tmpl"
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing template: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# workspace-template/CLAUDE.md.tmpl
# ---------------------------------------------------------------------------


def test_workspace_claude_md_has_exactly_4_includes() -> None:
    """Token budget at session start depends on this — strict 4-include rule.

    Author measured ~11-13K tokens at session start with exactly these four.
    Adding a fifth (e.g. `core/AGENTS.md`) inflates by ~5K tokens for every
    session — material at scale.
    """
    text = _read(WSP_CLAUDE_MD)
    includes = re.findall(r"^@core/[^\s]+", text, flags=re.MULTILINE)
    assert includes == [
        "@core/USER.md",
        "@core/rules.md",
        "@core/warm/decisions.md",
        "@core/hot/handoff.md",
    ], f"wrong includes: {includes}"


def test_workspace_claude_md_has_reliability_pyramid() -> None:
    text = _read(WSP_CLAUDE_MD)
    assert "Reliability pyramid" in text
    # Five levels mentioned somewhere — be lax on exact wording.
    for fragment in ("Session memory", "episodes.jsonl", "TOOLS", "rules.md", "Hooks"):
        assert fragment in text, f"reliability pyramid missing '{fragment}'"


def test_workspace_claude_md_has_file_access_zones() -> None:
    """RED/YELLOW/GREEN file zones — distinct from autonomy zones."""
    text = _read(WSP_CLAUDE_MD)
    assert "File access zones" in text
    # Find the access-zones section and check each colour appears within it.
    section = text.split("File access zones", 1)[1].split("##", 1)[0]
    assert "RED" in section
    assert "YELLOW" in section
    assert "GREEN" in section


def test_workspace_claude_md_has_subagent_tactics() -> None:
    text = _read(WSP_CLAUDE_MD)
    assert "Subagent tactics" in text
    section = text.split("Subagent tactics", 1)[1].split("##", 1)[0]
    # 4-row decision table by task type
    for fragment in ("Trivia", "subagent", "parallel", "cross-review"):
        assert fragment.lower() in section.lower(), f"subagent tactics missing '{fragment}'"


def test_workspace_claude_md_has_memory_map_with_in_context_column() -> None:
    text = _read(WSP_CLAUDE_MD)
    assert "Memory map" in text
    section = text.split("Memory map", 1)[1].split("##", 1)[0]
    assert "In context?" in section, "memory map must call out which layers preload into context"
    for layer in ("IDENTITY", "WARM", "HOT", "COLD", "L4"):
        assert layer in section, f"memory map missing layer {layer}"


def test_workspace_claude_md_has_anti_pattern_footer() -> None:
    text = _read(WSP_CLAUDE_MD)
    assert "What does NOT belong" in text


def test_workspace_claude_md_has_dont_initiate_rule() -> None:
    """Anti-spam-the-operator rule: agent responds to triggers, not unprompted."""
    text = _read(WSP_CLAUDE_MD)
    # Match either phrasing — give some flexibility for future rewording.
    assert any(
        s in text
        for s in (
            "do not ping the operator unprompted",
            "I do not initiate",
            "not initiate",
        )
    ), "missing 'I don't initiate' rule under Communication"


def test_workspace_claude_md_under_target_length() -> None:
    """Workspace CLAUDE.md should stay under 200 lines (target ~150).

    Author's measured target is 60-80 lines on his own machine; we ship a
    richer template (Reliability pyramid, zones, tactics, anti-pattern) so
    the budget is higher but still bounded.
    """
    text = _read(WSP_CLAUDE_MD)
    line_count = len(text.splitlines())
    assert line_count < 200, f"CLAUDE.md.tmpl is {line_count} lines — target < 200"


# ---------------------------------------------------------------------------
# workspace-template/core/rules.md.tmpl
# ---------------------------------------------------------------------------


def test_rules_md_has_terse_mode() -> None:
    """Terse Mode is the single biggest output-token saving in the system.

    Author claims ~75% reduction; our text says output costs 5x input on Opus.
    """
    text = _read(WSP_RULES_MD)
    assert "Terse Mode" in text
    section = text.split("Terse Mode", 1)[1]
    # Section must mention articles and filler — the two biggest savings.
    assert "articles" in section.lower()
    for filler in ("Sure!", "happy to", "filler"):
        assert filler in section, f"terse-mode section missing example '{filler}'"


def test_rules_md_has_escalation_three_strike() -> None:
    text = _read(WSP_RULES_MD)
    assert "Escalation" in text
    section = text.split("Escalation", 1)[1].split("##", 1)[0]
    # Three explicit attempt steps
    assert "First try" in section
    assert "Second try" in section
    assert "Third try" in section
    assert "STOP" in section


def test_rules_md_has_confidence_levels() -> None:
    text = _read(WSP_RULES_MD)
    assert "Confidence levels" in text
    section = text.split("Confidence levels", 1)[1].split("##", 1)[0]
    for level in ("Fact", "Assumption", "Don't know"):
        assert level in section, f"confidence-levels section missing '{level}'"


# ---------------------------------------------------------------------------
# workspace-template/core/USER.md.tmpl
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "шеф",
        "босс",
        "chief Edgelab",  # belt-and-braces — author's brand should never appear in our templates
    ],
)
def test_user_md_no_ru_or_brand_examples(phrase: str) -> None:
    """Per anti-RU policy and clean-rebrand: USER.md placeholders must be neutral.

    The original `edgelab-claude-md` template uses literal Russian honorifics
    («шеф», «босс») as example operator-address values. We strip those.
    """
    text = _read(WSP_USER_MD)
    assert phrase not in text, f"USER.md.tmpl contains forbidden '{phrase}'"


def test_user_md_has_operator_address_placeholder() -> None:
    text = _read(WSP_USER_MD)
    assert "{{OPERATOR_ADDRESS}}" in text or "Address as" in text


# ---------------------------------------------------------------------------
# installer/templates/claude/global-CLAUDE.md.tmpl
# ---------------------------------------------------------------------------


def test_global_claude_md_has_rule_priority_chain() -> None:
    text = _read(GLOBAL_CLAUDE_MD)
    assert "Rule Priority" in text
    section = text.split("Rule Priority", 1)[1].split("##", 1)[0]
    # Five priorities, top = Security
    assert "Security" in section
    assert "Operator" in section
    assert "Fact-checking" in section


def test_global_claude_md_has_9_principles_with_rationales() -> None:
    """Each principle has a one-line rationale (— prevents Y / catches Z / ...)."""
    text = _read(GLOBAL_CLAUDE_MD)
    assert "9 Working Principles" in text
    section = text.split("9 Working Principles", 1)[1].split("##", 1)[0]
    # Pull numbered principles
    matches = re.findall(r"^\d+\.\s+\*\*[^*]+\*\*\s+—", section, flags=re.MULTILINE)
    assert len(matches) == 9, (
        f"expected 9 principles each with `— rationale`, got {len(matches)}"
    )


def test_global_claude_md_has_anti_pattern_footer() -> None:
    text = _read(GLOBAL_CLAUDE_MD)
    assert "What does NOT belong" in text
