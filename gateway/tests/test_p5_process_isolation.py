"""Tests for Phase 5: Vesna and Leto run from separate venvs and code copies.

Verifies installer scripts and systemd units are wired up so a regression in
one process can't take the other down.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VESNA_INSTALLER = REPO_ROOT / "installer" / "lib" / "50-vesna.sh"
LETO_INSTALLER = REPO_ROOT / "installer" / "lib" / "60-user-gateway.sh"
VESNA_SVC = REPO_ROOT / "installer" / "templates" / "systemd" / "agent-vesna.service.tmpl"
LETO_SVC = REPO_ROOT / "installer" / "templates" / "systemd" / "agent-user-gateway.service.tmpl"
ARCH_DOC = REPO_ROOT / "docs" / "ARCHITECTURE.md"


def test_vesna_installer_creates_own_venv() -> None:
    text = VESNA_INSTALLER.read_text(encoding="utf-8")
    assert "${home}/.venv" in text or "/root/vesna/.venv" in text
    assert "python3 -m venv" in text
    # Each agent runs `<venv>/bin/pip install` against its own source. The
    # quoted form `"…/pip" install` separates the command from its argv, so
    # match on the venv's pip binary.
    assert re.search(r"\.venv/bin/pip\W+install", text), (
        "Vesna installer must run `<venv>/bin/pip install` against its own venv"
    )


def test_leto_installer_creates_own_venv() -> None:
    text = LETO_INSTALLER.read_text(encoding="utf-8")
    assert "${UG_DIR}/.venv" in text or "/home/agent/gateway/.venv" in text
    assert "python3 -m venv" in text
    assert re.search(r"\.venv/bin/pip\W+install", text), (
        "Leto installer must run `<venv>/bin/pip install` against its own venv"
    )


def test_vesna_and_leto_venvs_do_not_share_path() -> None:
    """The two venvs must live at different paths — otherwise one re-pip
    would clobber the other."""
    vesna_text = VESNA_INSTALLER.read_text(encoding="utf-8")
    leto_text = LETO_INSTALLER.read_text(encoding="utf-8")

    # Pull all `*.venv` paths and confirm no common entry.
    vesna_venvs = set(re.findall(r"[/\w${}.\-]+\.venv", vesna_text))
    leto_venvs = set(re.findall(r"[/\w${}.\-]+\.venv", leto_text))
    overlap = vesna_venvs & leto_venvs
    assert not overlap, f"Vesna and Leto share venv paths: {overlap}"


def test_installers_rsync_excludes_venv() -> None:
    """rsync must not propagate the local dev .venv into the deployed copy.
    Otherwise the installer would mix host Python deps with the agent user's
    venv, breaking on different OS / Python versions."""
    for path in (VESNA_INSTALLER, LETO_INSTALLER):
        text = path.read_text(encoding="utf-8")
        # Either pattern is acceptable; both prevent venv propagation.
        assert "--exclude '.venv'" in text or "--exclude=.venv" in text, (
            f"{path.name}: rsync must --exclude .venv"
        )


def test_vesna_systemd_uses_own_venv() -> None:
    text = VESNA_SVC.read_text(encoding="utf-8")
    assert "/root/vesna/.venv/bin/python" in text
    # Must not point at the user-gateway venv.
    assert "/home/agent/gateway/.venv" not in text


def test_leto_systemd_uses_own_venv() -> None:
    text = LETO_SVC.read_text(encoding="utf-8")
    assert "/home/agent/gateway/.venv/bin/python" in text
    assert "/root/vesna/.venv" not in text


def test_vesna_runs_as_root() -> None:
    text = VESNA_SVC.read_text(encoding="utf-8")
    assert "User=root" in text


def test_leto_runs_as_agent() -> None:
    text = LETO_SVC.read_text(encoding="utf-8")
    assert "User=agent" in text


def test_architecture_doc_describes_isolation() -> None:
    text = ARCH_DOC.read_text(encoding="utf-8")
    assert "Process isolation" in text
    # The trade-off is explicitly called out so future readers know why we
    # pay the 2× cost.
    assert "2×" in text or "trade-off" in text.lower() or "Trade-off" in text


def test_no_shared_state_dirs_between_agents() -> None:
    """Quick guard: the two installer scripts shouldn't both write to the same
    state directory — that would defeat the isolation."""
    vesna_text = VESNA_INSTALLER.read_text(encoding="utf-8")
    leto_text = LETO_INSTALLER.read_text(encoding="utf-8")

    # Find directories the script declares it'll write to via `install -d`.
    vesna_dirs = set(re.findall(r"/(?:root|home/agent|var/lib)\S*", vesna_text))
    leto_dirs = set(re.findall(r"/(?:root|home/agent|var/lib)\S*", leto_text))

    # Trim trailing punctuation to avoid false positives on quoted strings.
    def _normalize(d: str) -> str:
        return re.sub(r"[\"'$\\]+$", "", d).rstrip("/")

    vesna_dirs = {_normalize(d) for d in vesna_dirs}
    leto_dirs = {_normalize(d) for d in leto_dirs}

    # /var/lib/agent-installer is shared (idempotency state) — that's fine.
    shared_ok = {"/var/lib/agent-installer/state.json"}
    overlap = (vesna_dirs & leto_dirs) - shared_ok
    # Filter overlap to only paths likely to be writes (drop obvious refs to
    # the OTHER service's path, which both scripts may legitimately mention).
    real_overlap = {
        d for d in overlap
        if "/root/" in d and "/home/agent" not in d
        or "/home/agent/" in d and "/root/" not in d
    }
    # We're being defensive; if anything triggers, surface it for review.
    assert not real_overlap, (
        f"installers write to overlapping paths under each agent's home: "
        f"{real_overlap}"
    )
