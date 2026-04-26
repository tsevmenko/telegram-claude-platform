# agent-gateway

Telegram → Claude Code CLI gateway with multi-agent routing, 5-layer memory, and live streaming UI.

## Layout

- `src/agent_gateway/tg/` — aiogram bot, multi-bot polling, OOB commands, voice, media, group/topic routing.
- `src/agent_gateway/claude_cli/` — `claude` CLI subprocess management, stream-json parsing, BoundaryTracker, kill-tree.
- `src/agent_gateway/memory/` — HOT writes (`fcntl.LOCK_EX`), handoff, COLD bridge, OpenViking adapter.
- `src/agent_gateway/admin/` — Vesna-only admin commands (add/remove agent, restart, regenerate webhook token).
- `src/agent_gateway/multi_agent.py` — N agents in one process, shared executor.

## Dev

```bash
cd gateway
pip install -e .[dev]
ruff check src tests
black --check src tests
mypy src
pytest
```
