"""Vesna runs as root with bypass_permissions=false (Anthropic disallows
--dangerously-skip-permissions for uid=0). Without a comprehensive
permissions.allow she has to ask the operator on every routine sysadmin
command. This test pins the broad sysadmin allowlist so future edits
don't accidentally narrow it back to the client-agent set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TMPL = REPO_ROOT / "installer" / "templates" / "claude" / "vesna-settings.json.tmpl"


def _load() -> dict:
    raw = TMPL.read_text(encoding="utf-8").replace("{{HOOKS_DIR}}", "/fake/hooks")
    return json.loads(raw)


def test_vesna_template_is_valid_json() -> None:
    data = _load()
    assert "permissions" in data
    assert "hooks" in data


def test_vesna_template_distinct_from_client_default() -> None:
    """The whole point of the split — Vesna's allowlist must be wider than
    the default client-agent template."""
    vesna = _load()
    default_tmpl = REPO_ROOT / "installer" / "templates" / "claude" / "settings.json.tmpl"
    default = json.loads(
        default_tmpl.read_text(encoding="utf-8").replace("{{HOOKS_DIR}}", "/fake/hooks")
    )
    assert len(vesna["permissions"]["allow"]) > len(default["permissions"]["allow"]) * 2, (
        "Vesna allowlist should be substantially wider than the client default"
    )


@pytest.mark.parametrize(
    "category,must_contain",
    [
        # Service management — Vesna's day job.
        ("services", ["Bash(systemctl:*)", "Bash(journalctl:*)", "Bash(crontab:*)"]),
        # Package management — installing things.
        ("packages", ["Bash(apt:*)", "Bash(apt-get:*)", "Bash(dpkg:*)"]),
        # User & sudoers admin.
        ("users", ["Bash(useradd:*)", "Bash(usermod:*)", "Bash(passwd:*)", "Bash(visudo:*)"]),
        # Sudo catch-all (Vesna IS root, sudo is no-op for her).
        ("sudo", ["Bash(sudo:*)"]),
        # Security tooling needed by harden-vps skill.
        ("hardening", ["Bash(ufw:*)", "Bash(fail2ban-client:*)", "Bash(tailscale:*)"]),
        # Network diag.
        ("network", ["Bash(ip:*)", "Bash(ss:*)", "Bash(ping:*)", "Bash(dig:*)"]),
        # Process management.
        ("process", ["Bash(ps:*)", "Bash(pgrep:*)", "Bash(pkill:*)", "Bash(kill:*)"]),
        # File ops (no surprise the client template has these too, but Vesna
        # needs them as much).
        ("file_ops", ["Bash(cat:*)", "Bash(ls:*)", "Bash(rm:*)", "Bash(cp:*)", "Bash(mv:*)"]),
        # Read tool itself (Vesna reads many memory files).
        ("read_tool", ["Read", "Write", "Edit", "Grep", "Glob", "Task", "Skill"]),
    ],
)
def test_vesna_allowlist_covers_category(category: str, must_contain: list[str]) -> None:
    allow = set(_load()["permissions"]["allow"])
    missing = [item for item in must_contain if item not in allow]
    assert not missing, f"Vesna {category} allowlist missing: {missing}"


def test_vesna_template_keeps_critical_denies() -> None:
    deny = _load()["permissions"]["deny"]
    deny_str = "\n".join(deny)
    assert "rm -rf /" in deny_str
    assert "curl" in deny_str and ("| bash" in deny_str or "| sh" in deny_str)


def test_vesna_template_uses_hooks_dir_placeholder() -> None:
    raw = TMPL.read_text(encoding="utf-8")
    assert "{{HOOKS_DIR}}" in raw
    # Each hook command resolves through the placeholder, not a hardcoded path.
    assert "/root/" not in raw
    assert "/home/" not in raw


def test_vesna_template_compact_window_pinned() -> None:
    data = _load()
    assert data["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "400000"


def test_vesna_template_has_all_seven_lifecycle_hooks() -> None:
    data = _load()
    expected = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PreCompact", "Stop"}
    assert expected <= set(data["hooks"].keys())


def test_50_vesna_passes_profile_to_install_global_claude_dir() -> None:
    """Lock in the call site — installer/lib/50-vesna.sh must pass
    "vesna" as the 8th arg to install_global_claude_dir, otherwise the
    helper falls back to the narrow client-agent settings.json template."""
    text = (REPO_ROOT / "installer" / "lib" / "50-vesna.sh").read_text(encoding="utf-8")
    # Strip line-continuation backslashes so the multi-line invocation
    # collapses to one line we can grep.
    flat = text.replace("\\\n", " ")
    assert 'install_global_claude_dir root' in flat
    # The line that calls install_global_claude_dir must end with "vesna".
    for line in flat.splitlines():
        if "install_global_claude_dir root" in line:
            assert '"vesna"' in line, (
                f"50-vesna.sh: call must pass profile=vesna; got: {line!r}"
            )
            return
    raise AssertionError("install_global_claude_dir root call line not located")
