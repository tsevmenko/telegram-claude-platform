"""Regression tests for the v0.4.0 workspace layout.

The old layout placed agent files under ``~/.claude-lab/<agent>/.claude/``,
which triggered claude CLI 2.x's path-sensitivity classifier (function
``u35`` in the decompiled CLI binary): any path component named
``.claude`` is treated as sensitive metadata and Edit/Write/Bash tool calls
to it are refused — *even with* ``--dangerously-skip-permissions`` and
``--add-dir``.

Live regression: Tyrion (2026-04-29) tried to ``mkdir`` inside his own
``.claude/skills/instagram-analytics/`` and was blocked. The
``CLAUDE_CODE_REMOTE=1`` env workaround (v0.3.9) carved out
``.claude/skills``, ``.claude/agents`` and ``.claude/commands`` only.
``.claude/core/`` (memory: USER.md, MEMORY.md, .needs-onboarding) stayed
blocked, breaking onboarding completion.

v0.4.0 fix: drop the ``.claude/`` subdir entirely. Workspace path is now
``~/.claude-lab/<agent>/``. CLAUDE.md is auto-discovered from cwd. The
classifier no longer triggers on workspace writes.

These tests pin the layout invariant so future installer/refactor work
doesn't reintroduce the trailing ``/.claude``.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from agent_gateway.claude_cli.runner import ClaudeRunner

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Workspace path invariant
# ---------------------------------------------------------------------------


def test_workspace_path_does_not_end_in_dot_claude() -> None:
    """Any agent's workspace path must NOT end in ``.claude``. The whole
    point of the v0.4.0 refactor is that the workspace root is the
    parent of any potential ``.claude/`` directory, never inside one."""
    runner = ClaudeRunner(claude_binary="claude")
    for ws in (
        "/home/agent/.claude-lab/leto",
        "/home/agent/.claude-lab/tyrion",
        "/root/.claude-lab/vesna",
    ):
        cfg = SimpleNamespace(
            workspace=ws, model="sonnet",
            bypass_permissions=True, system_reminder=None,
        )
        cmd = runner._build_cmd(cfg, sid="x", new_session=True)
        idx = cmd.index("--add-dir")
        passed = cmd[idx + 1]
        assert not passed.endswith("/.claude"), (
            f"--add-dir got legacy path {passed!r} — must not include /.claude"
        )
        assert ".claude/" not in passed + "/", (
            f"path {passed!r} contains .claude/ component which would trigger "
            f"CLI sensitivity classifier u35"
        )


def test_runner_sets_agent_workspace_env() -> None:
    """Hooks and cron-rotation scripts read ``$AGENT_WORKSPACE``. Runner must
    set it to the canonical workspace path so the brittle realpath-based
    fallback in those scripts never has to fire."""
    runner = ClaudeRunner(claude_binary="claude")
    cfg = SimpleNamespace(
        workspace="/home/agent/.claude-lab/leto", model="opus",
        bypass_permissions=True, system_reminder=None,
    )
    env = runner._build_env(cfg)
    assert env["AGENT_WORKSPACE"] == "/home/agent/.claude-lab/leto"


def test_runner_home_resolution_works_for_v04_layout(monkeypatch) -> None:
    """HOME env should resolve to the user's home, regardless of the
    workspace layout. Earlier code did ``ws.parent.parent`` which assumed
    two levels (``~/.claude-lab/<agent>/.claude/``). v0.4.0 uses one level
    less (``~/.claude-lab/<agent>/``) — the new logic walks up to the
    ``.claude-lab`` ancestor and returns its parent.

    We clear the parent-process HOME so ``setdefault`` falls through to
    the computed value; in production claude is spawned by systemd which
    sets HOME=/home/agent or HOME=/root for the unit's user, and our
    setdefault leaves that in place.
    """
    import os
    monkeypatch.delenv("HOME", raising=False)
    runner = ClaudeRunner(claude_binary="claude")
    for ws, expected_home in (
        ("/home/agent/.claude-lab/leto", "/home/agent"),
        ("/home/agent/.claude-lab/tyrion", "/home/agent"),
        ("/root/.claude-lab/vesna", "/root"),
    ):
        cfg = SimpleNamespace(
            workspace=ws, model="opus",
            bypass_permissions=True, system_reminder=None,
        )
        env = runner._build_env(cfg)
        assert env["HOME"] == expected_home, (
            f"workspace={ws!r} → HOME={env['HOME']!r}, expected {expected_home!r}"
        )


def test_runner_home_setdefault_respects_parent_env(monkeypatch) -> None:
    """If the parent process (systemd) already set HOME, runner must NOT
    overwrite it — that's why we use setdefault, not direct assignment.
    Production systemd unit pins HOME=/home/agent for the agent user."""
    import os
    monkeypatch.setenv("HOME", "/home/agent")
    runner = ClaudeRunner(claude_binary="claude")
    cfg = SimpleNamespace(
        workspace="/home/agent/.claude-lab/leto", model="opus",
        bypass_permissions=True, system_reminder=None,
    )
    env = runner._build_env(cfg)
    # Parent-set HOME wins (matches expected; both happen to be /home/agent).
    assert env["HOME"] == "/home/agent"


# ---------------------------------------------------------------------------
# Installer scripts must plant the new layout
# ---------------------------------------------------------------------------


def test_installer_50_vesna_uses_new_layout() -> None:
    src = (REPO_ROOT / "installer" / "lib" / "50-vesna.sh").read_text()
    # Old: VESNA_WORKSPACE="/root/.claude-lab/vesna/.claude"
    # New: VESNA_WORKSPACE="/root/.claude-lab/vesna"
    m = re.search(r'^readonly VESNA_WORKSPACE="([^"]+)"', src, re.MULTILINE)
    assert m is not None, "VESNA_WORKSPACE constant missing"
    path = m.group(1)
    assert not path.endswith("/.claude"), (
        f"50-vesna.sh has legacy VESNA_WORKSPACE={path!r} — drop /.claude suffix"
    )
    assert path == "/root/.claude-lab/vesna"


def test_installer_60_user_gateway_uses_new_layout() -> None:
    src = (REPO_ROOT / "installer" / "lib" / "60-user-gateway.sh").read_text()
    m = re.search(r'^readonly LETO_WORKSPACE="([^"]+)"', src, re.MULTILINE)
    assert m is not None, "LETO_WORKSPACE constant missing"
    path = m.group(1)
    assert not path.endswith("/.claude"), (
        f"60-user-gateway.sh has legacy LETO_WORKSPACE={path!r} — drop /.claude suffix"
    )
    assert path == "/home/agent/.claude-lab/leto"


def test_installer_85_cron_passes_new_layout_paths() -> None:
    src = (REPO_ROOT / "installer" / "lib" / "85-cron.sh").read_text()
    # cron registration must call install_cron_for_agent with the new path
    # (no /.claude suffix)
    assert "install_cron_for_agent root  /root/.claude-lab/vesna  vesna" in src \
        or "install_cron_for_agent root /root/.claude-lab/vesna vesna" in src
    assert "install_cron_for_agent agent /home/agent/.claude-lab/leto leto" in src
    # Belt-and-braces: no /.claude suffix anywhere in the cron-registration block.
    assert "/.claude  vesna" not in src
    assert "/.claude leto" not in src


# ---------------------------------------------------------------------------
# Vesna's add_agent admin skill heredoc plants the new layout
# ---------------------------------------------------------------------------


def test_admin_skill_rsync_target_has_no_dot_claude() -> None:
    """``rsync ... workspace-template/ /home/agent/.claude-lab/<name>/`` —
    NOT ``.../<name>/.claude/``. Otherwise Vesna creates new agents with the
    legacy broken layout."""
    src = (REPO_ROOT / "installer" / "lib" / "50-vesna.sh").read_text()
    # Pull just the admin-tools heredoc so we don't false-positive on
    # surrounding bash code.
    start = src.find("<<'SKILL'")
    end = src.find("\nSKILL\n", start)
    assert start != -1 and end != -1
    heredoc = src[start:end]
    # The rsync line must reference the new layout.
    assert "/home/agent/.claude-lab/<name>/`" in heredoc \
        or "/home/agent/.claude-lab/<name>/." in heredoc, (
            "admin-tools heredoc should rsync into <name>/, not <name>/.claude/"
        )
    assert "/home/agent/.claude-lab/<name>/.claude/" not in heredoc, (
        "admin-tools heredoc still rsyncs into legacy /.claude/ subdir"
    )


def test_admin_skill_marker_path_uses_new_layout() -> None:
    src = (REPO_ROOT / "installer" / "lib" / "50-vesna.sh").read_text()
    start = src.find("<<'SKILL'")
    end = src.find("\nSKILL\n", start)
    heredoc = src[start:end]
    # touch /home/agent/.claude-lab/<name>/core/.needs-onboarding (NEW)
    # NOT /home/agent/.claude-lab/<name>/.claude/core/.needs-onboarding (OLD)
    assert "touch /home/agent/.claude-lab/<name>/core/.needs-onboarding" in heredoc, (
        "marker-touch path missing or still in legacy form"
    )
    assert "/home/agent/.claude-lab/<name>/.claude/core/.needs-onboarding" not in heredoc, (
        "admin-tools heredoc still uses legacy marker path under /.claude/"
    )
