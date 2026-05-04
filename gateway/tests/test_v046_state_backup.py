"""Tests for v0.4.6 — state-backup infrastructure.

Live data on VPS (USER profiles, decisions, scraped competitor archives,
custom skills) had no off-host backup. If the droplet died, all
accumulated agent learning vanished. v0.4.6 adds a private GitHub repo
mirror, rsynced every 4h via cron, with secret-scanner pre-commit guard.

These tests pin: installer step exists with right structure, helper
templates ship with the repo, secret-scanner refuses obvious tokens,
gitignore excludes the right paths.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TPL_DIR = REPO_ROOT / "installer" / "templates" / "state-backup"
STEP = REPO_ROOT / "installer" / "lib" / "98-state-backup.sh"


# ---------------------------------------------------------------------------
# Installer step structure
# ---------------------------------------------------------------------------


def test_installer_step_98_exists() -> None:
    assert STEP.is_file()
    text = STEP.read_text()
    assert "step_main()" in text
    # Must check for STATE_BACKUP_REPO env — if not set, skip gracefully.
    assert "STATE_BACKUP_REPO" in text
    # Cron file generation.
    assert "/etc/cron.d/agent-state-backup" in text
    # Both runner cadences (4-hourly + daily snapshot).
    assert "0 */4 * * * root" in text
    assert "0 3 * * * root" in text


def test_install_sh_registers_step_98() -> None:
    text = (REPO_ROOT / "install.sh").read_text()
    assert "98-state-backup" in text
    # Must run AFTER the workspace-creating steps but BEFORE 99-self-check.
    cron_idx = text.find("85-cron")
    backup_idx = text.find("98-state-backup")
    self_check_idx = text.find("99-self-check")
    assert 0 < cron_idx < backup_idx < self_check_idx


def test_installer_98_skips_if_env_unset() -> None:
    """If STATE_BACKUP_REPO is missing the step must warn and exit 0,
    not abort the whole install. Operators can re-run the step after
    creating the repo + deploy key."""
    text = STEP.read_text()
    assert "Skipping state-backup setup" in text or "return 0" in text


# ---------------------------------------------------------------------------
# Templates ship with the repo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("file", [
    "state-backup-runner.sh",
    "secret-scanner.sh",
    "openviking-snapshot.sh",
    "restore-from-backup.sh",
    ".gitignore",
    "README.md",
])
def test_template_file_present(file: str) -> None:
    assert (TPL_DIR / file).is_file(), (
        f"installer/templates/state-backup/{file} must ship in repo"
    )


@pytest.mark.parametrize("script", [
    "state-backup-runner.sh",
    "secret-scanner.sh",
    "openviking-snapshot.sh",
    "restore-from-backup.sh",
])
def test_template_script_passes_bash_n(script: str) -> None:
    p = TPL_DIR / script
    proc = subprocess.run(
        ["bash", "-n", str(p)],
        capture_output=True, text=True, timeout=5,
    )
    assert proc.returncode == 0, f"{script} bash -n: {proc.stderr!r}"


# ---------------------------------------------------------------------------
# .gitignore: critical exclusions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("must_ignore", [
    # Secrets — any version of these.
    "**/secrets/",
    "*.token",
    "*.key",
    "*.pem",
    "**/*.credentials*",
    ".env",
    # Claude CLI internal cruft.
    "**/.claude/projects/",
    "**/.claude/sessions/",
    "**/.claude/shell-snapshots/",
    "**/.claude/mcp-needs-auth-cache.json",
    # Build artefacts.
    "**/node_modules/",
    "**/.venv/",
    "**/__pycache__/",
    # Logs (may contain pasted secrets).
    "**/logs/activity/",
    "*.log",
    "*.jsonl",
    # Deprecated.
    "*.deprecated.*",
])
def test_gitignore_blocks(must_ignore: str) -> None:
    text = (TPL_DIR / ".gitignore").read_text()
    assert must_ignore in text, (
        f".gitignore must contain pattern: {must_ignore}"
    )


# ---------------------------------------------------------------------------
# Secret scanner — runtime behaviour
# ---------------------------------------------------------------------------


def _run_scanner_in_tmp_repo(tmp_path: Path, file_name: str, content: str) -> subprocess.CompletedProcess:
    """Initialize a tmp git repo, stage one file with given content, run scanner."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / file_name).write_text(content)
    subprocess.run(["git", "add", file_name], cwd=tmp_path, check=True)
    return subprocess.run(
        ["bash", str(TPL_DIR / "secret-scanner.sh")],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )


def test_scanner_clean_file_passes(tmp_path: Path) -> None:
    proc = _run_scanner_in_tmp_repo(tmp_path, "doc.md", "Hello world\nNothing to see.\n")
    assert proc.returncode == 0, f"scanner rejected clean file: {proc.stderr!r}"


@pytest.mark.parametrize("pattern_label,sample", [
    ("anthropic_key", "sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ("openai_key",    "sk-proj-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ("groq_key",      "gsk_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ("github_pat",    "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ("slack_token",   "xoxb-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ("aws_access",    "AKIAABCDEFGHIJKLMNOP"),
    ("scrapecreators","pk_12345678_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
    ("scrapecreators_alt","pXBZAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAcf2"),
    ("private_key",   "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA"),
    ("jwt",           "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3OD.dQw4w9WgXcQ"),
])
def test_scanner_rejects_secret_patterns(tmp_path: Path, pattern_label: str, sample: str) -> None:
    """Each pattern shape must trigger the scanner. Without these guards a
    careless rsync or copy could leak agent's API key history."""
    proc = _run_scanner_in_tmp_repo(
        tmp_path, "leak.md", f"prefix\n{sample}\nsuffix\n"
    )
    assert proc.returncode != 0, (
        f"scanner FAILED to detect {pattern_label}: {sample!r}\nstderr={proc.stderr!r}"
    )
    assert "REJECT" in proc.stderr or "SECRET" in proc.stderr.upper()


# ---------------------------------------------------------------------------
# state-backup-runner: rsync exclusions + status file
# ---------------------------------------------------------------------------


def test_runner_excludes_secrets() -> None:
    text = (TPL_DIR / "state-backup-runner.sh").read_text()
    # Must explicitly --exclude secrets/, *.token, *.key from rsync.
    for needle in ['--exclude="secrets/"',
                   '--exclude="*.token"',
                   '--exclude="*.key"',
                   '--exclude="*.pem"',
                   '--exclude="*.credentials*"',
                   '--exclude=".env*"']:
        assert needle in text, f"runner must {needle} from rsync"


def test_runner_writes_status_file() -> None:
    """Operator (and Vesna) check .last-run-status.json to know if backup
    is healthy. Runner must produce it on every termination path."""
    text = (TPL_DIR / "state-backup-runner.sh").read_text()
    assert ".last-run-status.json" in text or "STATUS_FILE" in text


def test_runner_invokes_secret_scanner() -> None:
    text = (TPL_DIR / "state-backup-runner.sh").read_text()
    assert "secret-scanner.sh" in text


def test_runner_pushes_via_deploy_key_alias() -> None:
    """The push must use the SSH alias `github-state-backup` (configured
    in /root/.ssh/config to use the dedicated deploy key). Pushing via
    operator's personal SSH key would over-grant scope."""
    text = (TPL_DIR / "state-backup-runner.sh").read_text()
    # Either explicit reference to alias, OR comment documenting it.
    assert "github-state-backup" in text or "deploy key" in text.lower()


# ---------------------------------------------------------------------------
# Restore tool
# ---------------------------------------------------------------------------


def test_restore_script_handles_all_four_agents() -> None:
    text = (TPL_DIR / "restore-from-backup.sh").read_text()
    for agent in ("leto", "tyrion", "varys", "vesna"):
        assert agent in text


def test_restore_script_ownership_split() -> None:
    """User-agents (leto, tyrion, varys) restore as `agent` user; vesna
    as root. Test pins this ownership convention so a future refactor
    doesn't drop the split."""
    text = (TPL_DIR / "restore-from-backup.sh").read_text()
    # Vesna must be flagged as root-owned restore.
    assert re.search(r"vesna\s+root", text), (
        "restore script must restore vesna as root"
    )
    # User-agents must be flagged as agent-owned.
    assert re.search(r"(leto|tyrion|varys)\s+agent", text), (
        "restore script must restore user-agents as agent user"
    )


def test_restore_script_optional_openviking_restore() -> None:
    text = (TPL_DIR / "restore-from-backup.sh").read_text()
    assert "ov-snapshot" in text
    # Must STOP the service before rewriting the SQLite db.
    assert "systemctl stop openviking" in text
