# Telegram Claude Platform

A production-grade installer + gateway for running Claude Code agents on a fresh Ubuntu VPS, with Telegram as the primary interface.

## What you get

After running the installer on a fresh Ubuntu 22.04 / 24.04 VPS:

- **Vesna** — root-level admin agent (server administration + manages settings of client agents).
- **Leto** — first user-level chat agent (general-purpose work, voice, multi-modal).
- A 5-layer memory system with cron-driven rotation (HOT / WARM / COLD / archive / L4 semantic search).
- 10 built-in skills, configurable hooks for safety enforcement, OpenViking semantic memory.
- Live progress streaming in Telegram, OOB commands (`/stop`, `/cancel`, `/status`, `/reset`, `/new`), webhook API for external triggers.

Two bots live in a single Telegram forum group with topic-based routing — Main topic for Leto, Technical topic for Vesna.

## Install

On a fresh Ubuntu VPS as root:

```bash
curl -fsSL https://raw.githubusercontent.com/tsevmenko/telegram-claude-platform/main/install.sh | sudo bash
```

The installer:
1. Checks OS and prerequisites (idempotent — safe to rerun).
2. Installs system dependencies, Node 20, Python 3.11+, Claude Code CLI.
3. Creates the `agent` system user with narrow passwordless sudo.
4. Prompts for Telegram bot tokens (validates each via `getMe`, retry/skip flow).
5. Deploys workspaces, systemd units, cron jobs, and OpenViking.
6. Generates a webhook token.
7. Runs a self-check and prints the final report.

After install, run `claude login` once for each user (root and agent) to authenticate Anthropic OAuth.

See [docs/INSTALL.md](docs/INSTALL.md) for the operator pre-flight checklist.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) — pre-flight checklist + installation flow.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system architecture overview.
- [docs/MEMORY.md](docs/MEMORY.md) — 5-layer memory hierarchy.
- [docs/HOOKS.md](docs/HOOKS.md) — Claude Code hook system.
- [docs/SKILLS.md](docs/SKILLS.md) — bundled skills.
- [docs/ADD-NEW-AGENT.md](docs/ADD-NEW-AGENT.md) — adding new client agents via Vesna.
- [docs/CLIENT-TEST-INSTRUCTIONS.md](docs/CLIENT-TEST-INSTRUCTIONS.md) — post-install operator tests.
- [docs/PROMPTS.md](docs/PROMPTS.md) — prompt library for advanced operations.
- [docs/RECOVERY.md](docs/RECOVERY.md) — recovery scenarios via Vesna.
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — common issues.

## License

MIT — see [LICENSE](LICENSE).
