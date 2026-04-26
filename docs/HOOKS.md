# Hooks

Hooks are shell commands run by Claude Code on lifecycle events. **CLAUDE.md is a suggestion (~80% compliance). Hooks are enforcement (100%).**

## Wiring

`~/.claude/settings.json` declares hooks under `"hooks"`. The installer template (`installer/templates/claude/settings.json.tmpl`) wires the bundled hooks for both Vesna and the user-gateway.

Each hook receives a JSON payload on stdin and:
- Exit `0` → proceed (stdout becomes context for `SessionStart` and `UserPromptSubmit`).
- Exit `2` → block the action; stderr is shown to the operator.

## Bundled hooks

| Script | Event | Purpose |
|---|---|---|
| `block-dangerous.sh` | PreToolUse / Bash | Blocks `rm -rf /…`, `git push --force`, `DROP TABLE`, `curl ... \| bash`, fork bombs, etc. |
| `protect-files.sh` | PreToolUse / Edit, Write | Blocks edits to `.env`, `.pem`, `.key`, lockfiles, sudoers, `/etc/passwd`, `/etc/shadow`, agent secrets. |
| `activity-logger.sh` | PostToolUse | Appends a JSONL audit entry per tool call to `logs/activity/YYYY-MM-DD.jsonl`. Best-effort, `chmod 600`. |
| `correction-detector.sh` | UserPromptSubmit | Pattern-matches "actually I meant", "не надо", etc. → flags into `core/LEARNINGS.md` and tells the agent to record a permanent lesson. |
| `write-handoff.sh` | Stop | Regenerates `core/hot/handoff.md` from the last 10 entries of `recent.md`. |

## Adding your own

1. Drop the script into `workspace-template/hooks/your-hook.sh`. Make it executable. Read JSON from stdin.
2. Register it in `installer/templates/claude/settings.json.tmpl` under the right event matcher.
3. Re-run the installer (or manually `cp` to `~/.claude/settings.json`).

## Best practices

- **Best-effort by default.** A broken hook should never wedge the agent. Use `set +e` and swallow errors unless you specifically want to block.
- **Mask secrets.** If you log tool input, run a `sed` regex over `(api_key|token|secret|password)` to redact.
- **No network.** Keep hooks fast (≤1s). External calls go in skills, not hooks.
- **Match precisely.** A `PreToolUse / Bash` matcher fires on every Bash call. Filter cheaply (`grep -qE 'pattern'`) before doing anything expensive.
