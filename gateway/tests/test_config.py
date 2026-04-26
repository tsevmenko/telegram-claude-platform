"""GatewayConfig + AgentConfig validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_gateway.config import AgentConfig, GatewayConfig


def test_workspace_must_be_absolute():
    with pytest.raises(ValidationError):
        AgentConfig(workspace="relative/path")


def test_load_minimal_config(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "agents": {
            "leto": {
                "bot_token": "1:tok",
                "workspace": "/tmp/ws"
            }
        }
    }))
    cfg = GatewayConfig.load(cfg_path)
    assert "leto" in cfg.agents
    assert cfg.agents["leto"].model == "opus"
    assert cfg.agents["leto"].bypass_permissions is True


def test_resolved_token_inline(tmp_path):
    cfg = AgentConfig(workspace="/tmp/ws", bot_token="abc:def")
    assert cfg.resolved_token() == "abc:def"


def test_resolved_token_from_file(tmp_path: Path):
    f = tmp_path / "tok"
    f.write_text("file:secret\n")
    cfg = AgentConfig(workspace="/tmp/ws", bot_token_file=str(f))
    assert cfg.resolved_token() == "file:secret"


def test_enabled_agents_filters_disabled():
    cfg = GatewayConfig(agents={
        "a": AgentConfig(workspace="/tmp/a", enabled=True),
        "b": AgentConfig(workspace="/tmp/b", enabled=False),
    })
    assert list(cfg.enabled_agents().keys()) == ["a"]


def test_resolved_groq_key_missing(tmp_path: Path):
    cfg = GatewayConfig()
    assert cfg.resolved_groq_key() == ""


def test_resolved_groq_key_inline_wins():
    cfg = GatewayConfig(groq_api_key="inline-key", groq_api_key_file="/nonexistent")
    assert cfg.resolved_groq_key() == "inline-key"


def test_resolved_groq_key_from_file(tmp_path: Path):
    p = tmp_path / "g.key"
    p.write_text("from-file\n")
    cfg = GatewayConfig(groq_api_key_file=str(p))
    assert cfg.resolved_groq_key() == "from-file"
