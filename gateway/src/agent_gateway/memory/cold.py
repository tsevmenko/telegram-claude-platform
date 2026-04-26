"""COLD memory utilities — context bridge for /reset and one-off reads."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

BRIDGE_HEADER = "## Context bridge from previous session"


def latest_section(workspace: Path) -> str:
    """Read the most recent section of MEMORY.md for the /reset context bridge.

    Returns the empty string if MEMORY.md is missing, empty, or has no
    section markers (## ...). The agent doesn't see this directly — it's
    injected into the next user message after /reset.
    """
    memory = workspace / "core" / "MEMORY.md"
    if not memory.exists():
        return ""
    try:
        text = memory.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        log.exception("[cold] failed to read %s", memory)
        return ""

    # Find the last "## " heading and return everything from there.
    lines = text.splitlines()
    last_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            last_idx = i
    if last_idx is None:
        return ""
    return "\n".join(lines[last_idx:]).strip()


def context_bridge_preamble(workspace: Path) -> str:
    """Build the context-bridge preamble appended to the first message after /reset."""
    section = latest_section(workspace)
    if not section:
        return ""
    return f"{BRIDGE_HEADER}\n\n{section}\n\n---\n\n"
