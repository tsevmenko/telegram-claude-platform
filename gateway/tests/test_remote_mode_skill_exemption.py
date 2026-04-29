"""Regression test for the bug where Claude CLI 2.x refused agents'
Bash/Edit/Write tool calls inside `<workspace>/.claude/skills/` with the
literal error:

    Claude requested permissions to edit
    /home/agent/.claude-lab/tyrion/.claude/skills/instagram-analytics/scripts
    which is a sensitive file.

This blocked Tyrion from creating the instagram-analytics skill and broke
the central design pattern of "agents extend their own toolchain by
writing skills".

Root cause (verified against decompiled claude CLI 2.1.121, function
``u35`` and its caller ``w9$``): the path-sensitivity classifier checks
each path component against a hardcoded list. When it hits ``.claude``,
it allows the next component to be ``skills``, ``agents``, or
``commands`` — but ONLY if its second arg ``$`` is truthy. That arg is
threaded down from ``isRemoteMode``, which the CLI sets via
``hH(process.env.CLAUDE_CODE_REMOTE) || E6()``.

Our gateway runs claude as a local subprocess. ``E6()`` is false (it's
the workspace-capability check for daemon-mode CLI). So unless we set
``CLAUDE_CODE_REMOTE=1`` explicitly, the exception never fires and our
agents are locked out of their own skills directory.

This test pins down the env contract so a future refactor of
``_build_env`` doesn't silently regress this fix.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from agent_gateway.claude_cli.runner import ClaudeRunner


def _cfg(workspace: str = "/home/agent/.claude-lab/tyrion/.claude") -> SimpleNamespace:
    return SimpleNamespace(
        workspace=workspace, model="opus",
        bypass_permissions=True, system_reminder=None,
    )


def test_env_includes_claude_code_remote() -> None:
    runner = ClaudeRunner(claude_binary="claude")
    env = runner._build_env(_cfg())
    assert env.get("CLAUDE_CODE_REMOTE") == "1", (
        "CLAUDE_CODE_REMOTE=1 must be set so the CLI's isRemoteMode flag "
        "activates the .claude/skills exemption in the sensitivity classifier."
    )


def test_env_remote_mode_is_setdefault_not_assignment() -> None:
    """Operator can override per-agent (e.g. force isRemoteMode off for a
    debugging session) by injecting CLAUDE_CODE_REMOTE in the parent env.
    setdefault preserves that; direct assignment would not."""
    runner = ClaudeRunner(claude_binary="claude")
    saved = os.environ.get("CLAUDE_CODE_REMOTE")
    os.environ["CLAUDE_CODE_REMOTE"] = "0"
    try:
        env = runner._build_env(_cfg())
        assert env["CLAUDE_CODE_REMOTE"] == "0", (
            "operator override via parent env must win over our default"
        )
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_CODE_REMOTE", None)
        else:
            os.environ["CLAUDE_CODE_REMOTE"] = saved


def test_env_does_not_clobber_compact_window() -> None:
    """The other env-var fix (auto-compact window) must keep working."""
    runner = ClaudeRunner(claude_binary="claude")
    env = runner._build_env(_cfg())
    assert env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW") == "400000"


def test_env_remote_mode_set_for_every_workspace_layout() -> None:
    """Both Vesna (root) and user-agents must get the env var."""
    runner = ClaudeRunner(claude_binary="claude")
    for ws in ("/root/.claude-lab/vesna/.claude",
               "/home/agent/.claude-lab/leto/.claude",
               "/home/agent/.claude-lab/tyrion/.claude"):
        env = runner._build_env(_cfg(workspace=ws))
        assert env["CLAUDE_CODE_REMOTE"] == "1", (
            f"{ws}: env var missing — agent will hit sensitive-file refusal"
        )
