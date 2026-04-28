"""T20-equivalent: scan repo for accidentally-committed secrets.

Adapted from `qwwiwi/architecture-brain-tests` T20. We don't ship the author's
RU-fallback assertions; we extend the secret-pattern set with Anthropic
``sk-ant-…``, OpenAI ``sk-proj-…``, AWS ``AKIA…`` and Slack ``xox[bp]-…``
which became common after that repo's last update.

Allowlist: test fixtures that intentionally contain fake keys for masking
tests. Anything else hitting these regexes is a real leak — fail loudly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Files allowed to contain secret-shaped strings (test fixtures, this file
# itself with example payloads inside literal strings).
_ALLOWLIST_NAMES = {
    "test_security_regex.py",         # this file
    "test_secret_masking_extended.py",  # planned in P3d.3
    "test_smoke.py",                  # uses 123:fake style placeholders
    "test_p3a.py",                    # uses 123:fake style placeholders
    "test_boundary.py",               # exercises mask_secrets() with fake ghp_ payloads
}

_ALLOWLIST_DIRS = {".git", ".venv", "__pycache__", "node_modules", "fixtures"}

_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "anthropic_classic": re.compile(r"\bsk-ant-api03-[A-Za-z0-9_\-]{40,}"),
    "openai_proj": re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{40,}"),
    "openai_classic": re.compile(r"\bsk-[A-Za-z0-9]{40,}"),
    "groq": re.compile(r"\bgsk_[A-Za-z0-9]{40,}"),
    "github_pat": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"),
    "slack_bot": re.compile(r"\bxox[bp]-\d{8,}-\d{8,}-[A-Za-z0-9]{20,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "jwt_three_part": re.compile(
        r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]{20,}"
    ),
    # Real Telegram bot tokens have ≥ 6 digits + ":AA" — fake test placeholders
    # use shorter formats like "123:fake".
    "telegram_bot": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{32,}\b"),
}


def _candidate_files() -> list[Path]:
    """All text-likely files the repo controls."""
    paths: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        # Skip non-tracked dirs and binary file types.
        if any(part in _ALLOWLIST_DIRS for part in path.parts):
            continue
        if path.name in _ALLOWLIST_NAMES:
            continue
        if path.suffix in {".pyc", ".so", ".dylib", ".png", ".jpg", ".jpeg",
                            ".gif", ".webp", ".pdf", ".zip", ".tar", ".gz"}:
            continue
        # Don't grep into the local skills sync stamp file — non-secret hex.
        if path.name == ".synced-from-sha":
            continue
        paths.append(path)
    return paths


@pytest.mark.parametrize("kind", sorted(_SECRET_PATTERNS.keys()))
def test_no_secrets_in_repo(kind: str) -> None:
    """For each known secret pattern, scan repo and fail on any match.

    Parametrised so failure messages name the leaking pattern.
    """
    pattern = _SECRET_PATTERNS[kind]
    leaks: list[tuple[Path, int, str]] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                # Strip leading/trailing whitespace and cap to 120 chars.
                snippet = line.strip()[:120]
                leaks.append((path.relative_to(REPO_ROOT), lineno, snippet))

    assert not leaks, (
        f"Found {len(leaks)} `{kind}` secret(s) in repo:\n"
        + "\n".join(f"  {p}:{ln}: {s}" for p, ln, s in leaks)
    )


def test_allowlist_files_are_real() -> None:
    """Sanity check: every allowlisted filename should exist somewhere.

    Catches typos in `_ALLOWLIST_NAMES` that would silently neuter the scan.
    """
    found = {p.name for p in REPO_ROOT.rglob("*") if p.is_file()}
    missing = _ALLOWLIST_NAMES - found
    # `test_secret_masking_extended.py` is planned-but-not-yet-created; allow that.
    missing.discard("test_secret_masking_extended.py")
    assert not missing, f"allowlist names not present in repo: {missing}"


def test_pattern_count_does_not_silently_shrink() -> None:
    """If someone removes a pattern, this test reminds them.

    Lock-step with the catch-up plan v2 P6.1 spec (≥ 8 patterns).
    """
    assert len(_SECRET_PATTERNS) >= 8
