"""Verify --add-dir <workspace> is included in the claude CLI invocation."""
from types import SimpleNamespace
from agent_gateway.claude_cli.runner import ClaudeRunner


def test_build_cmd_includes_add_dir_workspace() -> None:
    runner = ClaudeRunner(claude_binary="claude")
    cfg = SimpleNamespace(
        workspace="/home/agent/.claude-lab/tyrion",
        model="opus",
        bypass_permissions=True,
        system_reminder="...",
    )
    cmd = runner._build_cmd(cfg, sid="abc", new_session=True)
    assert "--add-dir" in cmd
    idx = cmd.index("--add-dir")
    assert cmd[idx + 1] == "/home/agent/.claude-lab/tyrion"


def test_build_cmd_add_dir_for_each_workspace() -> None:
    runner = ClaudeRunner(claude_binary="claude")
    for ws in ("/root/.claude-lab/vesna",
               "/home/agent/.claude-lab/leto",
               "/home/agent/.claude-lab/tyrion"):
        cfg = SimpleNamespace(
            workspace=ws, model="sonnet",
            bypass_permissions=False, system_reminder=None,
        )
        cmd = runner._build_cmd(cfg, sid="x", new_session=True)
        assert ws in cmd

