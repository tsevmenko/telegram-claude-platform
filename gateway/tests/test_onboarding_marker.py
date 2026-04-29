"""Onboarding marker pipeline — locks in the four changes that prevent
fresh agents wandering aimlessly:

1. protect-files.sh blocks writes into ~/.claude/projects/ (where Tyrion
   went hunting for memory location and our path-traversal guard
   refused to ship his outputs).
2. session-bootstrap.sh checks for core/.needs-onboarding and prepends
   a "DO ONBOARDING FIRST" block to session context.
3. onboarding skill removes the marker after USER.md is written.
4. Vesna's add_agent skill plants the marker on every new agent and
   tells operator to run /onboarding before anything else.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTECT_FILES = REPO_ROOT / "workspace-template" / "hooks" / "protect-files.sh"
SESSION_BOOTSTRAP = REPO_ROOT / "workspace-template" / "hooks" / "session-bootstrap.sh"
ONBOARDING_SKILL = REPO_ROOT / "workspace-template" / "skills" / "onboarding" / "SKILL.md"
VESNA_INSTALLER = REPO_ROOT / "installer" / "lib" / "50-vesna.sh"


# ---------------------------------------------------------------------------
# (1) protect-files.sh — Claude Code metadata dirs blocked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected_blocked",
    [
        # Within Claude Code's own metadata — must be blocked.
        ("/home/agent/.claude/projects/-home-agent--claude-lab-tyrion--claude/memory/x.md", True),
        ("/root/.claude/projects/some-project/file.md",                                   True),
        ("/home/agent/.claude/statsig/cache.json",                                         True),
        ("/home/agent/.claude/todos/list.json",                                            True),
        ("/home/agent/.claude/shell-snapshots/snap.txt",                                   True),
        ("/home/agent/.claude/ide/state.json",                                             True),
        # Workspace memory — MUST be allowed (those are the legitimate paths).
        # v0.4.0: workspace no longer has /.claude/ subdirectory.
        ("/home/agent/.claude-lab/leto/core/MEMORY.md",                                    False),
        ("/home/agent/.claude-lab/tyrion/core/LEARNINGS.md",                               False),
        ("/root/.claude-lab/vesna/core/warm/decisions.md",                                 False),
        # Sanity: even though the new layout drops /.claude/, agents migrating
        # from old VPS state may still have files at the old path until B-phase
        # mv is done. Those legacy paths must STILL be allowed (they're not
        # claude CLI metadata, just our old layout). protect-files only
        # blocks `.claude/projects|statsig|todos|shell-snapshots|ide` —
        # `.claude-lab/.../.claude/core` and friends are fine.
        ("/home/agent/.claude-lab/leto/.claude/core/MEMORY.md",                            False),
        # Existing protected paths — sanity check we didn't break them.
        ("/home/agent/secrets/leto-bot-token",                                             True),
        ("/etc/passwd",                                                                    True),
    ],
)
def test_protect_files_classification(path: str, expected_blocked: bool) -> None:
    payload = json.dumps({"tool_input": {"file_path": path}})
    proc = subprocess.run(
        ["bash", str(PROTECT_FILES)],
        input=payload,
        capture_output=True, text=True, timeout=5,
    )
    if expected_blocked:
        assert proc.returncode == 2, (
            f"{path}: should be BLOCKED (rc=2), got rc={proc.returncode}"
        )
        assert "BLOCKED" in proc.stderr
    else:
        assert proc.returncode == 0, (
            f"{path}: should be ALLOWED (rc=0), got rc={proc.returncode}, "
            f"stderr={proc.stderr!r}"
        )


# ---------------------------------------------------------------------------
# (2) session-bootstrap.sh — emits onboarding warning when marker present
# ---------------------------------------------------------------------------


def _build_fake_workspace(tmp_path: Path) -> Path:
    """Tree shaped like what session-bootstrap.sh expects.

    v0.4.0+: workspace lives directly at ``tmp_path/ws`` (no ``.claude/``
    subdir, since claude CLI 2.x's path-sensitivity classifier blocks
    writes to anything under a ``.claude/`` path component).
    """
    wsp = tmp_path / "ws"
    (wsp / "core").mkdir(parents=True)
    (wsp / "scripts").mkdir(parents=True)
    return wsp


def test_session_bootstrap_emits_warning_when_marker_present(tmp_path: Path) -> None:
    wsp = _build_fake_workspace(tmp_path)
    (wsp / "core" / ".needs-onboarding").touch()

    proc = subprocess.run(
        ["bash", str(SESSION_BOOTSTRAP)],
        env={**os.environ, "AGENT_WORKSPACE": str(wsp)},
        capture_output=True, text=True, timeout=5,
    )
    assert proc.returncode == 0
    assert "Onboarding required" in proc.stdout
    assert "DO THIS FIRST" in proc.stdout
    assert ".needs-onboarding" in proc.stdout  # tells how to clear


def test_session_bootstrap_silent_when_marker_absent(tmp_path: Path) -> None:
    wsp = _build_fake_workspace(tmp_path)
    # No .needs-onboarding file.

    proc = subprocess.run(
        ["bash", str(SESSION_BOOTSTRAP)],
        env={**os.environ, "AGENT_WORKSPACE": str(wsp)},
        capture_output=True, text=True, timeout=5,
    )
    assert proc.returncode == 0
    assert "Onboarding required" not in proc.stdout


def test_session_bootstrap_warning_includes_voice_first_pitch(tmp_path: Path) -> None:
    """The session-bootstrap warning should pitch the voice-memo + links
    flow that the onboarding skill expects, not just say 'do onboarding'."""
    wsp = _build_fake_workspace(tmp_path)
    (wsp / "core" / ".needs-onboarding").touch()
    proc = subprocess.run(
        ["bash", str(SESSION_BOOTSTRAP)],
        env={**os.environ, "AGENT_WORKSPACE": str(wsp)},
        capture_output=True, text=True, timeout=5,
    )
    assert "голосовое" in proc.stdout or "voice" in proc.stdout.lower()
    assert "USER.md" in proc.stdout


# ---------------------------------------------------------------------------
# (3) Onboarding skill removes the marker after writing USER.md
# ---------------------------------------------------------------------------


def test_onboarding_skill_documents_marker_removal() -> None:
    text = ONBOARDING_SKILL.read_text(encoding="utf-8")
    # Two beats: where to find the marker, how to remove it.
    assert ".needs-onboarding" in text
    assert "rm" in text
    # Also tell the agent why it matters (so it doesn't get tempted to skip).
    assert "session-bootstrap" in text or "future sessions" in text.lower()


# ---------------------------------------------------------------------------
# (4) Vesna's admin-tools skill — add_agent must plant marker + tell operator
# ---------------------------------------------------------------------------


def _admin_skill_text() -> str:
    """Extract the heredoc'd admin-tools SKILL.md from 50-vesna.sh."""
    src = VESNA_INSTALLER.read_text(encoding="utf-8")
    start = src.find("<<'SKILL'")
    end = src.find("\nSKILL\n", start)
    assert start != -1 and end != -1, "admin-tools heredoc not found in 50-vesna.sh"
    return src[start:end]


def test_admin_skill_describes_marker_planting() -> None:
    text = _admin_skill_text()
    assert "needs-onboarding" in text
    # Mandatory step in numbered list, not optional aside.
    assert "Plant onboarding marker" in text or "plant the marker" in text.lower()
    # Mandatory step uses touch with the right path pattern.
    assert "touch /home/agent/.claude-lab" in text
    assert "core/.needs-onboarding" in text


def test_admin_skill_tells_operator_to_run_onboarding() -> None:
    text = _admin_skill_text()
    # The final operator message must mention /onboarding.
    assert "/onboarding" in text
    # Explicit warning that without it the new agent refuses work.
    assert "refuse" in text.lower() or "не возьмётся" in text or "просить" in text.lower()


def test_admin_skill_lists_steps_in_correct_order() -> None:
    """Numbered steps 1–8 must include token validation, workspace creation,
    marker planting, restart, and final operator instruction."""
    text = _admin_skill_text()
    for keyword in [
        "getMe",                # step 2
        "rsync",                # step 4
        "core/.needs-onboarding",  # step 5
        "config.json",          # step 6
        "systemctl restart",    # step 7
        "/onboarding",          # step 8
    ]:
        assert keyword in text, f"add_agent steps missing keyword: {keyword}"


def test_admin_skill_says_non_negotiable() -> None:
    """The non-negotiability of marker + operator instruction needs to be
    obvious so a future maintainer doesn't 'simplify' the steps away."""
    text = _admin_skill_text()
    assert "non-negotiable" in text.lower() or "mandatory" in text.lower()
