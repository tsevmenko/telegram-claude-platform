"""Tests for the v0.4.2 self-scheduling / proactivity stack.

Two binaries (cron-add, fire-webhook) plus the self-schedule skill let
agents fire webhook injections at future times — recurring (cron) or
one-shot (at). Live regression that motivated this: Tyrion (2026-05-01)
hit "Session-only, auto-expires after 7 days" when he tried to use the
CLI's built-in scheduled-tasks; we needed durable OS-level scheduling.

These tests pin:
- bin scripts pass syntax check + accept expected args
- cron-add validation rejects bad agent names, bad cron expressions,
  bad base64
- self-schedule skill present in workspace-template
- CLAUDE.md.tmpl mentions Proactivity (so agents know they have it)
- sudoers template grants agent narrow access to cron-add only
- installer step 95-personal-cron.sh exists and is registered
- system-deps installs `at`
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_DIR = REPO_ROOT / "installer" / "templates" / "bin"
FIRE_WEBHOOK = BIN_DIR / "fire-webhook"
CRON_ADD = BIN_DIR / "cron-add"
SKILL_DIR = REPO_ROOT / "workspace-template" / "skills" / "self-schedule"


# ---------------------------------------------------------------------------
# bin scripts: bash syntax + executable bit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("script", [FIRE_WEBHOOK, CRON_ADD,
                                    SKILL_DIR / "scripts" / "schedule.sh",
                                    SKILL_DIR / "scripts" / "list.sh",
                                    SKILL_DIR / "scripts" / "remove.sh"])
def test_script_passes_bash_syntax_check(script: Path) -> None:
    assert script.is_file(), f"{script} is missing"
    proc = subprocess.run(["bash", "-n", str(script)],
                          capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, (
        f"{script.name} failed bash -n: {proc.stderr!r}"
    )


@pytest.mark.parametrize("script", [FIRE_WEBHOOK, CRON_ADD,
                                    SKILL_DIR / "scripts" / "schedule.sh",
                                    SKILL_DIR / "scripts" / "list.sh",
                                    SKILL_DIR / "scripts" / "remove.sh"])
def test_script_is_executable(script: Path) -> None:
    """Operator's git checkout might lose +x on Windows. Catch that here."""
    assert os.access(script, os.X_OK), f"{script} not executable (chmod +x)"


# ---------------------------------------------------------------------------
# fire-webhook usage / arg validation
# ---------------------------------------------------------------------------


def test_fire_webhook_no_args_prints_usage() -> None:
    proc = subprocess.run(["bash", str(FIRE_WEBHOOK)],
                          capture_output=True, text=True, timeout=5)
    assert proc.returncode == 1
    assert "usage:" in proc.stderr.lower()


def test_fire_webhook_one_arg_prints_usage() -> None:
    proc = subprocess.run(["bash", str(FIRE_WEBHOOK), "tyrion"],
                          capture_output=True, text=True, timeout=5)
    assert proc.returncode == 1


def test_fire_webhook_missing_config_returns_2(tmp_path: Path) -> None:
    """If GATEWAY_CONFIG points to a nonexistent file, exit 2 (not crash)."""
    env = {**os.environ,
           "GATEWAY_CONFIG": str(tmp_path / "nope.json"),
           "WEBHOOK_TOKEN_FILE": str(tmp_path / "token.txt")}
    b64 = base64.b64encode(b"hello").decode()
    proc = subprocess.run(["bash", str(FIRE_WEBHOOK), "tyrion", b64],
                          env=env, capture_output=True, text=True, timeout=5)
    assert proc.returncode == 2
    assert "config not found" in proc.stderr


# ---------------------------------------------------------------------------
# cron-add validation: agent name, cron expr, base64
# ---------------------------------------------------------------------------


def _fake_gateway_config(tmp_path: Path, agents: dict[str, dict] | None = None) -> Path:
    """Write a minimal gateway config with the given agent names."""
    import json
    cfg = {
        "allowed_group_ids": [-1003619435150],
        "agents": agents or {
            "tyrion": {"topic_routing": {"-1003619435150": ["318"]}},
            "leto":   {"topic_routing": {"-1003619435150": ["general"]}},
        },
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return p


def _run_cron_add(*args: str, tmp_path: Path,
                  config: Path | None = None) -> subprocess.CompletedProcess:
    """Run cron-add with CRON_DIR + GATEWAY_CONFIG pointed at temp paths so we
    don't touch the real /etc/cron.d/."""
    cron_dir = tmp_path / "cron.d"
    cron_dir.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "CRON_DIR": str(cron_dir),
        "GATEWAY_CONFIG": str(config or _fake_gateway_config(tmp_path)),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    return subprocess.run(["bash", str(CRON_ADD), *args],
                          env=env, capture_output=True, text=True, timeout=5)


def test_cron_add_no_args_prints_usage(tmp_path: Path) -> None:
    proc = _run_cron_add(tmp_path=tmp_path)
    assert proc.returncode == 1
    assert "Usage" in proc.stderr


def test_cron_add_rejects_unknown_agent(tmp_path: Path) -> None:
    b64 = base64.b64encode(b"hi").decode()
    proc = _run_cron_add("add", "ghostly", "0 18 * * 0", b64,
                         tmp_path=tmp_path)
    assert proc.returncode == 1
    assert "not found" in proc.stderr


def test_cron_add_rejects_invalid_agent_name(tmp_path: Path) -> None:
    """Names with spaces, semicolons, slashes, etc. — would let arg-injection
    through into the cron file. Strict regex rejects them."""
    b64 = base64.b64encode(b"hi").decode()
    for bad in ["ty rion", "tyrion;ls", "tyrion/../etc", "TyRion",
                "9tyrion", "x" * 40]:
        proc = _run_cron_add("add", bad, "0 18 * * 0", b64,
                             tmp_path=tmp_path)
        assert proc.returncode == 1, (
            f"agent name {bad!r} should have been rejected"
        )


@pytest.mark.parametrize("expr", [
    "0 18 * * 0",        # weekly Sunday 18:00
    "*/15 * * * *",      # every 15 min
    "30 4 1-15 * 1-5",   # range + step combinations
    "0 9,12,18 * * *",   # list
])
def test_cron_add_accepts_valid_cron_exprs(tmp_path: Path, expr: str) -> None:
    b64 = base64.b64encode(b"hi").decode()
    proc = _run_cron_add("add", "tyrion", expr, b64, "test",
                         tmp_path=tmp_path)
    # Subprocess might exit 0 or fail on systemctl reload (which is fine in
    # tests — we don't have systemd in CI). Accept exit 0 OR check we got
    # past validation by seeing the file written.
    cron_file = tmp_path / "cron.d" / "agent-personal-tyrion"
    assert cron_file.is_file(), (
        f"valid cron expr {expr!r} should have written cron file. "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


@pytest.mark.parametrize("bad_expr", [
    "every minute",         # English aliases not supported
    "@daily",               # @ aliases rejected (timing too coarse)
    "0 18 * *",             # 4 fields instead of 5
    "0 18 * * 0 /bin/sh",   # extra field (would be command injection target)
    "; rm -rf /",           # blatant
    "*/15;ls",              # semicolon
    "0 18 * * SUN",         # day name (we want numeric only — strict)
])
def test_cron_add_rejects_invalid_cron_exprs(tmp_path: Path, bad_expr: str) -> None:
    b64 = base64.b64encode(b"hi").decode()
    proc = _run_cron_add("add", "tyrion", bad_expr, b64, "test",
                         tmp_path=tmp_path)
    assert proc.returncode == 1, (
        f"bad cron expr {bad_expr!r} should have been rejected"
    )
    assert "invalid cron expression" in proc.stderr.lower()


def test_cron_add_rejects_invalid_base64(tmp_path: Path) -> None:
    """BSD base64 (macOS) accepts garbage permissively, GNU (Linux) is
    strict. Test passes input that is invalid under BOTH: characters
    outside base64 alphabet that survive even lenient decoders to produce
    empty/garbage output, and validate via exit code only — the specific
    error message differs per platform."""
    # Long string of non-base64 chars — fails strictly on Linux, decodes
    # to "non-empty garbage" on macOS lenient mode but the *empty* check
    # catches the empty-after-strip case if any.
    bad_inputs = [
        "###################",        # all invalid characters
        "this-is-clearly!@#$%",       # mixed garbage
    ]
    for bad in bad_inputs:
        proc = _run_cron_add("add", "tyrion", "0 18 * * 0", bad, "test",
                             tmp_path=tmp_path)
        # Exit code is what matters — both Linux strict-base64 and macOS
        # decoded-empty paths return 1.
        assert proc.returncode != 0, (
            f"input {bad!r} should be rejected (got exit {proc.returncode})"
        )


def test_cron_add_rejects_empty_decoded_prompt(tmp_path: Path) -> None:
    """Valid base64 of empty string should be rejected — prevents schedules
    that fire empty webhook prompts."""
    empty_b64 = base64.b64encode(b"").decode() or ""
    proc = _run_cron_add("add", "tyrion", "0 18 * * 0", empty_b64, "test",
                         tmp_path=tmp_path)
    assert proc.returncode == 1


def test_cron_add_rejects_invalid_tag(tmp_path: Path) -> None:
    """Tags must be plain identifiers — no spaces, no shell metas (would
    leak into the cron comment line)."""
    b64 = base64.b64encode(b"hi").decode()
    for bad_tag in ["my tag", "tag;ls", "weekly digest", "tag\nmore"]:
        proc = _run_cron_add("add", "tyrion", "0 18 * * 0", b64, bad_tag,
                             tmp_path=tmp_path)
        assert proc.returncode == 1, (
            f"bad tag {bad_tag!r} should have been rejected"
        )


def test_cron_add_writes_correct_line_format(tmp_path: Path) -> None:
    """The line written to the cron file must match a fixed shape:
    <expr> <user> <fire-webhook-path> <agent> <base64>. No room for
    arbitrary command insertion."""
    b64 = base64.b64encode(b"weekly digest").decode()
    proc = _run_cron_add("add", "tyrion", "0 18 * * 0", b64, "weekly-digest",
                         tmp_path=tmp_path)
    cron_file = tmp_path / "cron.d" / "agent-personal-tyrion"
    assert cron_file.is_file()
    content = cron_file.read_text()
    # Header lines + comment + actual line.
    assert "SHELL=/bin/bash" in content
    assert "CRON_TZ=UTC" in content
    assert "[tag=weekly-digest]" in content
    # Schedule line: 5 fields, then agent user, then fire-webhook path, then args.
    assert "0 18 * * 0 agent /opt/agent-installer/bin/fire-webhook tyrion" in content
    assert b64 in content


def test_cron_add_vesna_runs_as_root(tmp_path: Path) -> None:
    """Personal cron for vesna runs as root (she lives in agent-vesna.service
    which is User=root); user-agents run as `agent`."""
    cfg = _fake_gateway_config(tmp_path, agents={
        "vesna": {"topic_routing": {"-1003619435150": ["558"]}},
    })
    b64 = base64.b64encode(b"check disk").decode()
    proc = _run_cron_add("add", "vesna", "0 6 * * *", b64, "morning-check",
                         tmp_path=tmp_path, config=cfg)
    cron_file = tmp_path / "cron.d" / "agent-personal-vesna"
    assert cron_file.is_file()
    content = cron_file.read_text()
    assert "0 6 * * * root /opt/agent-installer/bin/fire-webhook vesna" in content
    assert "HOME=/root" in content


def test_cron_add_list_returns_empty_when_no_file(tmp_path: Path) -> None:
    proc = _run_cron_add("list", "tyrion", tmp_path=tmp_path)
    assert proc.returncode == 0
    assert ("no entries" in proc.stdout.lower()
            or "does not exist" in proc.stdout.lower())


def test_cron_add_remove_handles_missing_file(tmp_path: Path) -> None:
    proc = _run_cron_add("remove", "tyrion", "5", tmp_path=tmp_path)
    assert proc.returncode == 1
    assert "not found" in proc.stderr.lower()


# ---------------------------------------------------------------------------
# Skill metadata + content
# ---------------------------------------------------------------------------


def test_self_schedule_skill_md_has_required_frontmatter() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text()
    assert text.startswith("---\n")
    assert "name: self-schedule" in text
    assert "user-invocable: true" in text
    # Description must include trigger phrases for both natural-language
    # invocation and explicit /skill calls.
    assert "remind me" in text.lower() or "напомни" in text
    assert "recurring" in text.lower() or "еженедельно" in text


def test_self_schedule_skill_warns_against_built_in_scheduler() -> None:
    """The skill explicitly tells agents NOT to use claude CLI's
    mcp__scheduled-tasks__create_scheduled_task — that's session-bound."""
    text = (SKILL_DIR / "SKILL.md").read_text()
    assert "scheduled-tasks" in text or "scheduled_tasks" in text or "scheduled tasks" in text.lower()
    assert "session-bound" in text.lower() or "auto-expires" in text.lower() \
        or "7 days" in text


def test_self_schedule_skill_documents_audit_log() -> None:
    """Skill must point at core/scheduled.md as the durable audit trail."""
    text = (SKILL_DIR / "SKILL.md").read_text()
    assert "scheduled.md" in text


# ---------------------------------------------------------------------------
# CLAUDE.md.tmpl: agents must learn about Proactivity
# ---------------------------------------------------------------------------


def test_workspace_claude_md_has_proactivity_section() -> None:
    text = (REPO_ROOT / "workspace-template" / "CLAUDE.md.tmpl").read_text()
    assert "Proactivity" in text or "proactivity" in text.lower()
    assert "self-schedule" in text


def test_workspace_claude_md_warns_about_session_bound_scheduler() -> None:
    text = (REPO_ROOT / "workspace-template" / "CLAUDE.md.tmpl").read_text()
    # The whole point of self-schedule existing is that the built-in is
    # session-bound. CLAUDE.md must transmit that context to agents.
    assert "session-bound" in text.lower() or "auto-expires" in text.lower() \
        or "7 days" in text


# ---------------------------------------------------------------------------
# Sudoers grant + installer wiring
# ---------------------------------------------------------------------------


def test_sudoers_grants_only_cron_add_for_proactivity() -> None:
    """The agent user gets passwordless sudo ONLY for cron-add (with
    add/list/remove subcommands) — not for arbitrary scripts under
    /opt/agent-installer/bin/. That keeps the escalation path narrow."""
    text = (REPO_ROOT / "installer" / "lib" / "30-users.sh").read_text()
    assert "AGENT_PROACTIVITY" in text
    assert "/opt/agent-installer/bin/cron-add" in text
    # Must not grant blanket access to fire-webhook or any other binary
    # in /opt/agent-installer/bin/.
    bad_grant = "AGENT_PROACTIVITY = \\\n    /opt/agent-installer/bin/*"
    assert bad_grant not in text, (
        "sudoers must not grant blanket access to /opt/agent-installer/bin/*"
    )
    # cron-add must be referenced with subcommand suffix (add/list/remove),
    # not a bare invocation that could be tricked.
    assert "cron-add add *" in text
    assert "cron-add list *" in text
    assert "cron-add remove *" in text


def test_installer_step_95_registered_in_install_sh() -> None:
    text = (REPO_ROOT / "install.sh").read_text()
    assert "95-personal-cron" in text


def test_installer_step_95_file_exists_and_has_step_main() -> None:
    p = REPO_ROOT / "installer" / "lib" / "95-personal-cron.sh"
    assert p.is_file()
    text = p.read_text()
    assert "step_main()" in text
    assert "fire-webhook" in text and "cron-add" in text


def test_system_deps_installs_at() -> None:
    """`at` daemon required by `self-schedule once`. Must be in 10-system-deps."""
    text = (REPO_ROOT / "installer" / "lib" / "10-system-deps.sh").read_text()
    assert " at " in text or " at\\\n" in text  # apt install line includes 'at'
    assert "atd" in text  # systemctl enable --now atd
