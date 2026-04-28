"""v0.3.0 security release — verify hardening artefacts are wired up."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 15-hardening.sh — installer step exists and does the safe-by-default things
# ---------------------------------------------------------------------------


def test_hardening_step_file_exists() -> None:
    p = REPO_ROOT / "installer" / "lib" / "15-hardening.sh"
    assert p.is_file()
    assert p.stat().st_mode & 0o100, "15-hardening.sh must be chmod +x"


def test_hardening_step_in_installer_steps_list() -> None:
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "15-hardening" in text
    # Must come after 10-system-deps (apt available) and before 40-secrets
    # (so fail2ban is up before we open new attack surface).
    pos_10 = text.find("10-system-deps")
    pos_15 = text.find("15-hardening")
    pos_40 = text.find("40-secrets")
    assert pos_10 < pos_15 < pos_40


@pytest.mark.parametrize(
    "feature",
    [
        "unattended-upgrades",
        "fail2ban",
        "ufw",
        "MaxAuthTries",
    ],
)
def test_hardening_installs_feature(feature: str) -> None:
    text = (REPO_ROOT / "installer" / "lib" / "15-hardening.sh").read_text()
    assert feature in text, f"15-hardening.sh missing {feature} setup"


def test_hardening_does_not_disable_password_auth_unilaterally() -> None:
    """The baseline step must NOT touch PermitRootLogin or PasswordAuthentication
    — that risks locking the operator out. Aggressive lockdown lives in the
    Vesna `harden-vps` skill, run after operator confirms key access works.
    """
    text = (REPO_ROOT / "installer" / "lib" / "15-hardening.sh").read_text()
    # The function name 'apply_sshd_setting' calls these keys; check the
    # actual `apply_sshd_setting "<key>"` invocations don't include the
    # risky two.
    risky = re.findall(
        r'apply_sshd_setting\s+"(PermitRootLogin|PasswordAuthentication)"',
        text,
    )
    assert not risky, (
        f"15-hardening.sh must not auto-set {risky} — that locks operators out"
    )


def test_hardening_skip_envvar_honoured() -> None:
    text = (REPO_ROOT / "installer" / "lib" / "15-hardening.sh").read_text()
    assert "HARDENING_SKIP" in text
    assert "skipping baseline hardening" in text.lower()


def test_hardening_whitelists_install_ip_in_fail2ban() -> None:
    """Hard-locking out the operator with their own fail2ban rule mid-install
    is a perennial gotcha. We auto-whitelist the SSH source IP."""
    text = (REPO_ROOT / "installer" / "lib" / "15-hardening.sh").read_text()
    assert "SSH_CLIENT" in text or "SSH_CONNECTION" in text
    assert "ignoreip" in text


# ---------------------------------------------------------------------------
# Webhook default — bound to 127.0.0.1 (not 0.0.0.0)
# ---------------------------------------------------------------------------


def test_user_gateway_webhook_defaults_to_loopback() -> None:
    text = (
        REPO_ROOT / "installer" / "templates" / "user-gateway-config.json.tmpl"
    ).read_text()
    assert '"listen_host": "127.0.0.1"' in text
    assert '"listen_host": "0.0.0.0"' not in text


# ---------------------------------------------------------------------------
# systemd hardening for Leto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive",
    [
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        "PrivateTmp=true",
        "LockPersonality=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "RestrictNamespaces=true",
        "RestrictRealtime=true",
        "RestrictSUIDSGID=true",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK",
        "SystemCallFilter=@system-service",
        "CapabilityBoundingSet=",
        "MemoryMax=2G",
    ],
)
def test_leto_systemd_unit_has_hardening_directive(directive: str) -> None:
    text = (
        REPO_ROOT
        / "installer"
        / "templates"
        / "systemd"
        / "agent-user-gateway.service.tmpl"
    ).read_text()
    assert directive in text, (
        f"agent-user-gateway.service.tmpl missing hardening directive: {directive}"
    )


# ---------------------------------------------------------------------------
# Vesna's harden-vps skill exists and has the right structure
# ---------------------------------------------------------------------------


def test_vesna_harden_vps_skill_exists() -> None:
    p = (
        REPO_ROOT
        / "workspace-template"
        / "skills"
        / "harden-vps"
        / "SKILL.md"
    )
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "tailscale" in text.lower()
    assert "ufw" in text.lower()


def test_harden_vps_skill_documents_rollback() -> None:
    text = (
        REPO_ROOT
        / "workspace-template"
        / "skills"
        / "harden-vps"
        / "SKILL.md"
    ).read_text()
    assert "rollback" in text.lower() or "out-of-band" in text.lower()


def test_harden_vps_skill_warns_about_step2_verification() -> None:
    """The single most common failure mode: locking down ssh BEFORE verifying
    Tailscale-SSH works. Skill MUST document this anti-pattern."""
    text = (
        REPO_ROOT
        / "workspace-template"
        / "skills"
        / "harden-vps"
        / "SKILL.md"
    ).read_text()
    assert "verify" in text.lower() or "verification" in text.lower()
    assert "Anti-patterns" in text


# ---------------------------------------------------------------------------
# Self-check now reports hardening status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row",
    [
        "ufw enabled",
        "fail2ban running",
        "unattended-upgrades enabled",
        "sshd MaxAuthTries",
        "webhook bound to 127.0.0.1",
    ],
)
def test_self_check_reports_hardening(row: str) -> None:
    text = (
        REPO_ROOT / "installer" / "lib" / "99-self-check.sh"
    ).read_text(encoding="utf-8")
    assert row in text, f"99-self-check.sh missing row: {row}"
