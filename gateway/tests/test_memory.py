"""Memory layer tests — HOT writes, cold context bridge."""

from __future__ import annotations

from pathlib import Path

from agent_gateway.memory.cold import context_bridge_preamble, latest_section
from agent_gateway.memory.hot import (
    EMERGENCY_TRIM_BYTES,
    KEEP_LINES,
    SNIPPET_LEN,
    append_turn,
)


def test_append_turn_writes_entry(tmp_workspace: Path):
    append_turn(tmp_workspace, "leto", "hi there", "hello back", "tg-text")
    body = (tmp_workspace / "core" / "hot" / "recent.md").read_text()
    assert "### " in body
    assert "[tg-text]" in body
    assert "hi there" in body
    assert "hello back" in body


def test_append_turn_truncates_snippets(tmp_workspace: Path):
    long = "x" * (SNIPPET_LEN * 3)
    append_turn(tmp_workspace, "leto", long, long, "tg-text")
    body = (tmp_workspace / "core" / "hot" / "recent.md").read_text()
    # Each snippet capped to SNIPPET_LEN chars.
    user_line = next(line for line in body.splitlines() if line.startswith("**User:**"))
    payload = user_line.removeprefix("**User:** ")
    assert len(payload) <= SNIPPET_LEN


def test_emergency_trim_kicks_in(tmp_workspace: Path):
    hot = tmp_workspace / "core" / "hot" / "recent.md"
    # Pre-fill with > EMERGENCY_TRIM_BYTES of fake entries.
    blob = ("\n### 2026-04-26 12:00 [tg-text]\n**User:** u\n**Leto:** a\n" * 800)
    hot.write_text(blob)
    assert hot.stat().st_size > EMERGENCY_TRIM_BYTES

    # Adding another turn triggers the trim.
    append_turn(tmp_workspace, "leto", "trigger", "trim", "tg-text")
    body = hot.read_text()

    # Should have been emergency-trimmed: file size is much smaller now.
    assert hot.stat().st_size < EMERGENCY_TRIM_BYTES
    # Header re-applied.
    assert body.startswith("# HOT memory")
    # Lines kept ≤ KEEP_LINES.
    assert len(body.splitlines()) <= KEEP_LINES + 5


def test_latest_section_picks_last_h2(tmp_workspace: Path):
    memory = tmp_workspace / "core" / "MEMORY.md"
    memory.write_text(
        "# MEMORY\n"
        "\n## 2026-04-01\n- old fact\n"
        "\n## 2026-04-26\n- recent fact\n- another recent\n"
    )
    section = latest_section(tmp_workspace)
    assert "2026-04-26" in section
    assert "recent fact" in section
    assert "old fact" not in section


def test_latest_section_empty_when_no_headings(tmp_workspace: Path):
    memory = tmp_workspace / "core" / "MEMORY.md"
    memory.write_text("# MEMORY\n\nno sections yet\n")
    assert latest_section(tmp_workspace) == ""


def test_context_bridge_preamble_includes_separator(tmp_workspace: Path):
    preamble = context_bridge_preamble(tmp_workspace)
    assert "Context bridge" in preamble
    assert "---" in preamble


def test_context_bridge_empty_when_no_section(tmp_workspace: Path):
    (tmp_workspace / "core" / "MEMORY.md").write_text("# MEMORY\n\nempty\n")
    assert context_bridge_preamble(tmp_workspace) == ""
