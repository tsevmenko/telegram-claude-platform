"""T17-equivalent: shape tests for `installer/templates/claude/settings.json.tmpl`.

The settings template wires hooks, permissions, and the auto-compact window.
Drift here is silent and breaks production after a fresh install. These tests
fail loudly when a key field disappears.

The tmpl uses ``{{HOOKS_DIR}}`` placeholder so we substitute a fake one before
parsing as JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_TMPL = REPO_ROOT / "installer" / "templates" / "claude" / "settings.json.tmpl"


def _load() -> dict:
    raw = SETTINGS_TMPL.read_text(encoding="utf-8")
    # Substitute the only placeholder so the file becomes valid JSON.
    raw = raw.replace("{{HOOKS_DIR}}", "/fake/hooks")
    return json.loads(raw)


def test_template_is_valid_json() -> None:
    data = _load()
    assert isinstance(data, dict)


def test_compact_window_pinned_to_400000() -> None:
    """`CLAUDE_CODE_AUTO_COMPACT_WINDOW=400000` is the single env var the
    author calls out — at 400K Opus 4.7 stops auto-compacting and uses the
    full 1M context. Don't drop or change without measuring impact."""
    data = _load()
    env = data.get("env", {})
    assert env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW") == "400000"


def test_permissions_allow_essentials() -> None:
    data = _load()
    allow = set(data["permissions"]["allow"])
    # Bash subset essential for any real workspace (git, read, edit).
    must_have = {"Bash(git:*)", "Read", "Write", "Edit", "Grep", "Glob"}
    missing = must_have - allow
    assert not missing, f"settings.json.tmpl missing allow entries: {missing}"


def test_permissions_deny_critical_patterns() -> None:
    data = _load()
    deny = data["permissions"]["deny"]
    # `rm -rf /` and curl|bash must be blocked at the permissions layer.
    deny_str = "\n".join(deny)
    assert "rm -rf /" in deny_str
    assert "curl" in deny_str and ("| bash" in deny_str or "| sh" in deny_str)


def test_hooks_block_covers_seven_lifecycle_points() -> None:
    """SessionStart, UserPromptSubmit, PreToolUse(Bash), PreToolUse(Edit|Write),
    PostToolUse, PreCompact, Stop — seven distinct registrations."""
    data = _load()
    hooks = data["hooks"]
    expected_keys = {"SessionStart", "UserPromptSubmit", "PreToolUse",
                     "PostToolUse", "PreCompact", "Stop"}
    assert expected_keys <= set(hooks.keys())

    # PreToolUse needs two matchers: Bash + Edit|Write.
    pre_matchers = {entry.get("matcher", "") for entry in hooks["PreToolUse"]}
    assert "Bash" in pre_matchers
    assert any("Edit" in m for m in pre_matchers)


def test_every_hook_uses_hooks_dir_placeholder() -> None:
    """All hook commands must reference {{HOOKS_DIR}} so the installer can
    re-target them per agent. A hard-coded path here breaks multi-agent."""
    raw = SETTINGS_TMPL.read_text(encoding="utf-8")
    # Each "command" line should contain the placeholder OR a non-relative
    # absolute path that points outside the workspace (we don't have any of
    # those today). If the placeholder is missing somewhere, fail fast.
    data = _load()
    for event_name, entries in data["hooks"].items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                assert "/fake/hooks/" in cmd, (
                    f"hook in {event_name} doesn't use {{{{HOOKS_DIR}}}}: {cmd}"
                )


def test_every_hook_has_reasonable_timeout() -> None:
    """3-10s. Any hook longer than 30s blocks the prompt unacceptably."""
    data = _load()
    for event, entries in data["hooks"].items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                t = hook.get("timeout")
                assert isinstance(t, int) and 1 <= t <= 30, (
                    f"hook in {event} has invalid timeout: {t}"
                )


def test_local_recall_registered_in_user_prompt_submit() -> None:
    """P2 added local-recall.sh — must remain registered after auto-recall.sh."""
    data = _load()
    user_prompt = data["hooks"]["UserPromptSubmit"]
    cmds = []
    for entry in user_prompt:
        for hook in entry.get("hooks", []):
            cmds.append(hook["command"])
    cmd_str = "\n".join(cmds)
    assert "auto-recall.sh" in cmd_str
    assert "local-recall.sh" in cmd_str
    assert "correction-detector.sh" in cmd_str


def test_no_root_or_sudo_in_allow() -> None:
    """Defence-in-depth: allow-list must not whitelist `sudo` or root-equivalent
    catch-alls. Vesna and Leto rely on narrow sudoers separately, not on this
    file. Author was burned by an over-permissive allow once."""
    data = _load()
    allow = " ".join(data["permissions"]["allow"]).lower()
    assert "sudo" not in allow
    # `Bash(*)` would defeat the deny list — make sure no wildcard.
    assert "bash(*)" not in allow
    assert "bash(*:*)" not in allow
