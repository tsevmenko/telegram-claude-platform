"""Shared pytest fixtures for the gateway test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_gateway.config import AgentConfig


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Build a minimal agent workspace tree in a temp dir, return its path.

    v0.4.0+ layout: workspace lives directly at the path returned (no
    ``.claude/`` subdirectory). The fixture creates a child dir ``ws/`` so
    multiple parallel fixtures using the same tmp_path don't collide.
    """
    ws = tmp_path / "ws"
    (ws / "core" / "warm").mkdir(parents=True)
    (ws / "core" / "hot").mkdir(parents=True)
    (ws / "core" / "archive").mkdir(parents=True)
    (ws / "skills").mkdir()
    (ws / "scripts").mkdir()
    (ws / "hooks").mkdir()
    (ws / "logs").mkdir()
    (ws / "CLAUDE.md").write_text("# Test agent\n")
    (ws / "core" / "USER.md").write_text("# Operator\n")
    (ws / "core" / "rules.md").write_text("# Rules\n")
    (ws / "core" / "MEMORY.md").write_text("# MEMORY\n\n## 2026-04-25\n- old fact\n")
    (ws / "core" / "warm" / "decisions.md").write_text("# WARM\n")
    (ws / "core" / "hot" / "recent.md").write_text("# HOT\n")
    (ws / "core" / "hot" / "handoff.md").write_text("# handoff\n")
    return ws


@pytest.fixture
def agent_cfg(tmp_workspace: Path) -> AgentConfig:
    return AgentConfig(
        enabled=True,
        bot_token="123:fake",
        bot_username="test_bot",
        workspace=str(tmp_workspace),
        model="sonnet",
        timeout_sec=10,
        agent_names=["test"],
    )
