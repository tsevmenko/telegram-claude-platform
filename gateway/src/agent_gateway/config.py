"""Pydantic config models for the gateway.

Two top-level config shapes:

- ``RootAgentConfig`` — for ``agent-vesna.service`` (single agent, root user).
- ``UserGatewayConfig`` — for ``agent-user-gateway.service`` (multi-agent).

Both share the ``AgentConfig`` building block. Loaded from a JSON file passed
as ``--config`` to ``python -m agent_gateway``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StreamingMode = Literal["off", "partial", "progress"]


class AgentConfig(BaseModel):
    """Per-agent configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    bot_token: str = ""
    bot_token_file: str | None = None
    bot_username: str = ""
    workspace: str
    """Absolute path to the agent's `.claude/` directory."""

    model: Literal["opus", "sonnet"] = "opus"
    """Default model for this agent. Overridden per-call by `claude --model`."""

    timeout_sec: int = 300
    streaming_mode: StreamingMode = "partial"
    streaming_mode_private: StreamingMode = "progress"
    streaming_mode_group: StreamingMode = "off"

    system_reminder: str = ""
    system_reminder_private: str = ""
    system_reminder_group: str = ""

    agent_names: list[str] = Field(default_factory=list)
    """Names this agent answers to in group chats (`@<name>` mention detection)."""

    topic_routing: dict[str, list[str]] = Field(default_factory=dict)
    """Map of `chat_id` -> list of `topic_id` strings this agent handles."""

    bypass_permissions: bool = True
    """Pass `--dangerously-skip-permissions` to claude CLI. True for non-root agents."""

    @field_validator("workspace")
    @classmethod
    def _workspace_must_be_absolute(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError(f"workspace must be an absolute path, got: {v}")
        return v

    def resolved_token(self) -> str:
        """Read bot token from inline value or token file."""
        if self.bot_token:
            return self.bot_token
        if self.bot_token_file:
            path = Path(self.bot_token_file).expanduser()
            return path.read_text().strip()
        return ""


class L4Config(BaseModel):
    """L4 semantic memory (OpenViking) configuration."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    url: str = "http://127.0.0.1:1933"
    api_key_file: str = ""
    account: str = "default"


class WebhookConfig(BaseModel):
    """External-injection webhook API."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    listen_host: str = "0.0.0.0"
    listen_port: int = 8080
    token_file: str = ""


class GatewayConfig(BaseModel):
    """Top-level gateway config (multi-agent)."""

    model_config = ConfigDict(extra="forbid")

    poll_interval_sec: int = 2
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    l4: L4Config = Field(default_factory=L4Config)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    state_dir: str = "./state"
    logs_dir: str = "./logs"

    groq_api_key: str = ""
    groq_api_key_file: str | None = None
    voice_language: str = "en"

    @classmethod
    def load(cls, path: str | Path) -> GatewayConfig:
        return cls.model_validate(json.loads(Path(path).read_text()))

    def enabled_agents(self) -> dict[str, AgentConfig]:
        return {name: cfg for name, cfg in self.agents.items() if cfg.enabled}

    def resolved_groq_key(self) -> str:
        if self.groq_api_key:
            return self.groq_api_key
        if self.groq_api_key_file:
            p = Path(self.groq_api_key_file).expanduser()
            if p.exists():
                return p.read_text().strip()
        return ""
