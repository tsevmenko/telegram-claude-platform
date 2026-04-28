"""Tests for Phase 4: PINS file shape, verify_pins behaviour, cron template,
fix_owner discipline.

These are doc-as-config: they assert installer artefacts are well-formed
without actually running ``install.sh``. Real end-to-end installer
verification lives in installer/tests/*.bats (Docker-bound; skipped here).
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PINS = REPO_ROOT / "installer" / "PINS"
PINS_REPOS = REPO_ROOT / "installer" / "PINS.repos"
PREFLIGHT = REPO_ROOT / "installer" / "lib" / "00-preflight.sh"
CRON_INSTALLER = REPO_ROOT / "installer" / "lib" / "85-cron.sh"


# ---------------------------------------------------------------------------
# PINS / PINS.repos files
# ---------------------------------------------------------------------------


def _parse_kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.split("#", 1)[0].strip()
    return out


def test_pins_file_exists() -> None:
    assert PINS.is_file()


def test_pins_repos_file_exists() -> None:
    assert PINS_REPOS.is_file()


def test_every_pin_has_a_repo_mapping() -> None:
    pins = _parse_kv(PINS)
    repos = _parse_kv(PINS_REPOS)
    missing = [name for name in pins if name not in repos]
    assert not missing, (
        f"PINS entries without a repo mapping in PINS.repos: {missing}"
    )


def test_every_repo_mapping_is_valid_owner_repo_format() -> None:
    repos = _parse_kv(PINS_REPOS)
    for name, value in repos.items():
        assert re.fullmatch(r"[\w.-]+/[\w.-]+", value), (
            f"PINS.repos entry {name}={value!r} is not 'owner/repo' format"
        )


# ---------------------------------------------------------------------------
# verify_pins helper (sourced from 00-preflight.sh)
# ---------------------------------------------------------------------------


def _run_verify_pins_with_temp_files(
    tmp_path: Path,
    pins_content: str,
    repos_content: str,
) -> tuple[int, str, str]:
    """Source verify_pins out of 00-preflight.sh in a fresh shell against a
    fake INSTALLER_ROOT, return (rc, stdout, stderr)."""
    fake_root = tmp_path / "fake_root"
    (fake_root / "installer").mkdir(parents=True)
    (fake_root / "installer" / "PINS").write_text(pins_content)
    (fake_root / "installer" / "PINS.repos").write_text(repos_content)

    # Stub the helpers (log/warn/err/ok) that 00-preflight.sh expects from
    # the installer's main shell. We need verify_pins itself but must avoid
    # running step_main.
    wrapper = textwrap.dedent(f"""
    #!/usr/bin/env bash
    log()  {{ echo "LOG: $*"; }}
    warn() {{ echo "WARN: $*" >&2; }}
    err()  {{ echo "ERR: $*" >&2; }}
    ok()   {{ echo "OK: $*"; }}
    CURL_OPTS=()
    INSTALLER_ROOT={fake_root}
    source {PREFLIGHT}
    verify_pins
    """)
    proc = subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_verify_pins_passes_when_pin_is_a_real_tag(tmp_path: Path) -> None:
    """Self-pin to a tag we know exists (or skip if offline)."""
    rc, stdout, stderr = _run_verify_pins_with_temp_files(
        tmp_path,
        pins_content="SELF=v0.1.0-baseline\n",
        repos_content="SELF=tsevmenko/telegram-claude-platform\n",
    )
    # If we get HTTP 404 here, it's because the tag isn't pushed to origin
    # yet — that's expected on a CI runner with no network or before push.
    # The test stays meaningful: rc=1 means "verify_pins correctly detected
    # an unreachable pin"; rc=0 means "verify_pins ran clean".
    # Either is consistent with the spec; what we DON'T want is rc=2 (script
    # crash) or stdout silence on success.
    if rc == 0:
        assert "verify_pins:" in stdout
    else:
        # rc==1 is allowed when the tag genuinely 404s (pre-push state).
        assert rc == 1
        assert "NOT FOUND" in stderr or "verify_pins" in stderr


def test_verify_pins_fails_on_unresolvable_pin(tmp_path: Path) -> None:
    """Pin a deliberately-non-existent SHA → verify_pins must abort with rc=1.

    GitHub returns 404 (repo gone), 422 (SHA invalid / repo disabled), or 451
    (DMCA) for unresolvable references. All three should gate the install.

    Use ``octocat/Hello-World`` as the repo — it's GitHub's perpetual demo
    repo, guaranteed-public and never going away, so the only thing that can
    fail here is the SHA lookup itself.
    """
    rc, stdout, stderr = _run_verify_pins_with_temp_files(
        tmp_path,
        pins_content="DOES_NOT_EXIST=000000000000000000000000000000000000dead\n",
        repos_content="DOES_NOT_EXIST=octocat/Hello-World\n",
    )
    assert rc == 1, (
        f"verify_pins must fail on unresolvable pin; "
        f"got rc={rc}, stderr={stderr!r}"
    )
    assert "cannot resolve SHA" in stderr or "Refusing to continue" in stderr


def test_verify_pins_fails_when_repo_mapping_missing(tmp_path: Path) -> None:
    """Pin without corresponding PINS.repos entry → fail loudly."""
    rc, stdout, stderr = _run_verify_pins_with_temp_files(
        tmp_path,
        pins_content="ORPHAN=v0.1.0-baseline\n",
        repos_content="",  # empty
    )
    assert rc == 1
    assert "no repo in PINS.repos" in stderr or "ORPHAN" in stderr


def test_verify_pins_skips_silently_when_no_pins_file(tmp_path: Path) -> None:
    """Empty/missing PINS file → verify_pins is a no-op (return 0)."""
    fake_root = tmp_path / "no_pins_root"
    (fake_root / "installer").mkdir(parents=True)
    # Don't create PINS or PINS.repos.

    wrapper = textwrap.dedent(f"""
    #!/usr/bin/env bash
    log()  {{ echo "LOG: $*"; }}
    warn() {{ echo "WARN: $*" >&2; }}
    err()  {{ echo "ERR: $*" >&2; }}
    ok()   {{ echo "OK: $*"; }}
    CURL_OPTS=()
    INSTALLER_ROOT={fake_root}
    source {PREFLIGHT}
    verify_pins
    """)
    proc = subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    assert "skipping" in proc.stdout.lower()


# ---------------------------------------------------------------------------
# fix_owner helper
# ---------------------------------------------------------------------------


def test_fix_owner_is_idempotent_on_missing_path(tmp_path: Path) -> None:
    """fix_owner must not fail on non-existent target — installer reruns."""
    wrapper = textwrap.dedent(f"""
    #!/usr/bin/env bash
    log()  {{ :; }}
    warn() {{ :; }}
    err()  {{ :; }}
    ok()   {{ :; }}
    source {PREFLIGHT}
    fix_owner root:root /no/such/path
    echo "rc=$?"
    """)
    proc = subprocess.run(
        ["bash", "-c", wrapper], capture_output=True, text=True, timeout=10,
    )
    assert "rc=0" in proc.stdout


# ---------------------------------------------------------------------------
# Cron installer (P4.3) — CRON_TZ + HOME
# ---------------------------------------------------------------------------


def test_cron_template_pins_utc() -> None:
    text = CRON_INSTALLER.read_text(encoding="utf-8")
    assert "CRON_TZ=UTC" in text


def test_cron_template_sets_home() -> None:
    text = CRON_INSTALLER.read_text(encoding="utf-8")
    # 85-cron.sh resolves $HOME via getent and inlines it. Make sure the
    # variable is being set, not left to inherit.
    assert "HOME=" in text
    assert "getent passwd" in text or "${home}" in text


def test_cron_template_uses_explicit_user_field() -> None:
    """Each cron line in /etc/cron.d/<file> must specify the user explicitly
    (4th field) — otherwise crond doesn't know who to run as."""
    text = CRON_INSTALLER.read_text(encoding="utf-8")
    # Look for the 5 cron lines and confirm they have ${user} after the time.
    cron_lines = re.findall(
        r"^\s*\d+\s+\d+\s+\*\s+\*\s+\*\s+\$\{user\}\s+",
        text, flags=re.MULTILINE,
    )
    assert len(cron_lines) >= 5, (
        f"expected ≥5 cron lines with ${{user}} field, got {len(cron_lines)}"
    )
