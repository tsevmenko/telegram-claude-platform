# Skills

A skill is a folder under `<workspace>/.claude/skills/<name>/` with a `SKILL.md` (YAML frontmatter + instructions) and an optional `scripts/` directory. Claude reads the frontmatter, decides when to invoke the skill, and follows the body's instructions. Helper scripts run via the Bash tool — they're not magic, just normal shell / Python.

## Bundled (10 skills)

| Skill | Purpose | API / dep |
|---|---|---|
| `voice-transcribe` | Transcribe `.ogg` → text via Groq Whisper | `groq.key` |
| `web-research` | Web search with citations | Perplexity (paid) → DuckDuckGo (free fallback) |
| `charts-and-tables` | Create published charts/tables/maps | Datawrapper API |
| `diagram-generator` | Generate `.excalidraw` JSON for pipelines / mindmaps / flowcharts | offline (pure Python) |
| `youtube-transcript` | Fetch a video transcript with timestamps | `yt-dlp` (free) → TranscriptAPI |
| `markdown-extract` | Clean Markdown from any URL | `r.jina.ai` (free, international) |
| `onboarding` | First-run wizard, populates `core/USER.md` | none |
| `self-compiler` | Refactor `CLAUDE.md` from accumulated `LEARNINGS.md` | none |
| `quick-reminders` | One-shot reminders up to 48h, zero LLM tokens at fire time | `at` daemon + webhook |
| `present` | Markdown → reveal.js HTML deck | `pandoc` |

## SKILL.md format

```markdown
---
name: <kebab-case>
description: "One-paragraph description (matters for agent triggering)"
user-invocable: true|false
argument-hint: "<arg pattern>"
---

# Title

Body — instructions to the agent on when and how to use this skill.
```

`description` is what the agent sees when deciding whether to invoke. Make it action-oriented and include trigger words ("Use when: ...").

## Adding your own skill

1. Create `workspace-template/skills/<name>/SKILL.md`.
2. Add helper scripts under `workspace-template/skills/<name>/scripts/` if needed. Make them executable.
3. Re-run the installer; the new skill is planted into every workspace.
4. Existing workspaces: copy the new skill folder manually:
   ```bash
   sudo rsync -a workspace-template/skills/<name>/ /home/agent/.claude-lab/leto/.claude/skills/<name>/
   sudo chown -R agent:agent /home/agent/.claude-lab/leto/.claude/skills/<name>
   ```
