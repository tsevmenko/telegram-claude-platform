"""HOT memory writes — append every turn to ``core/hot/recent.md``.

Concurrency: ``fcntl.LOCK_EX`` guarantees that two messages arriving
simultaneously to different chats of the same agent (or different agents
sharing a workspace, edge case) cannot interleave their writes.

Emergency trim: if recent.md grows past ``EMERGENCY_TRIM_BYTES`` we keep the
last ``KEEP_LINES`` lines so the cron rotation hasn't run yet doesn't wedge
the file. The find-first-``### `` skip ensures we never start mid-entry.
"""

from __future__ import annotations

import fcntl
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

EMERGENCY_TRIM_BYTES = 20 * 1024
KEEP_LINES = 600  # ~150 entries assuming 4 lines/entry
SNIPPET_LEN = 200


def append_turn(
    workspace: Path,
    agent_name: str,
    user_text: str,
    agent_response: str,
    source_tag: str = "text",
) -> None:
    """Append a single turn to the agent's HOT journal."""
    hot_file = workspace / "core" / "hot" / "recent.md"
    if not hot_file.parent.exists():
        log.debug("[hot] hot/ dir missing for %s; skip", workspace)
        return

    ts = time.strftime("%Y-%m-%d %H:%M")
    user_snippet = (user_text or "").replace("\n", " ")[:SNIPPET_LEN]
    agent_snippet = (agent_response or "(inline)").replace("\n", " ")[:SNIPPET_LEN]
    title = agent_name.capitalize() or "Agent"
    entry = (
        f"\n### {ts} [{source_tag}]\n"
        f"**User:** {user_snippet}\n"
        f"**{title}:** {agent_snippet}\n"
    )

    try:
        with hot_file.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(entry)
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        size = hot_file.stat().st_size
        if size > EMERGENCY_TRIM_BYTES:
            _emergency_trim(hot_file, size)
    except Exception:  # noqa: BLE001
        log.exception("[hot] append failed for %s", hot_file)


def _emergency_trim(hot_file: Path, current_size: int) -> None:
    log.warning("[hot] %s size %dB exceeds %dB — emergency trim",
                hot_file, current_size, EMERGENCY_TRIM_BYTES)
    text = hot_file.read_text(encoding="utf-8")
    lines = text.split("\n")
    if len(lines) <= KEEP_LINES:
        return

    kept = lines[-KEEP_LINES:]
    # Don't start mid-entry: skip until we hit the next "### " header.
    for i, ln in enumerate(kept):
        if ln.startswith("### "):
            kept = kept[i:]
            break

    header = "# HOT memory — full rolling 24h journal\n"
    new = header + "\n" + "\n".join(kept)
    with hot_file.open("w", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(new)
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    log.warning("[hot] emergency trim complete: %dB → %dB", current_size, len(new))
