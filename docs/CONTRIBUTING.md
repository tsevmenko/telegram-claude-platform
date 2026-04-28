# Contributing

## Skills

Skills are not authored directly in this repo. Their canonical home is the [`agent-skills`](https://github.com/tsevmenko-bulls/agent-skills) repository (private). This repo vendors a copy under `workspace-template/skills/` so installer ships them without a runtime clone.

### Workflow for editing or adding a skill

```
# 1. Clone agent-skills next to this repo
cd ~/projects && gh repo clone <owner>/agent-skills

# 2. Edit / add skills there, commit, push
cd ~/projects/agent-skills
$EDITOR skills/<your-skill>/SKILL.md
git commit -am "..." && git push

# 3. Sync into telegram-claude-platform
cd ~/projects/telegram-claude-platform
SKILLS_REPO=~/projects/agent-skills tools/sync-skills.sh

# 4. Review and commit the vendored copy separately
git add workspace-template/skills
git commit -m "sync skills from agent-skills@<sha>"
```

`tools/sync-skills.sh` refuses to run if `agent-skills` has uncommitted changes — every vendored copy traces back to a known commit. The source SHA is stamped at `workspace-template/skills/.synced-from-sha`.

### Skill format contract

See `agent-skills/CONTRIBUTING.md` for the SKILL.md schema, frontmatter rules, secrets handling, and anti-patterns.

## Gateway / installer / docs

For everything except skills, the workflow is conventional:

1. Branch off `main`.
2. Make changes.
3. Run baseline tests: `pytest gateway/ openviking-lite/`.
4. Run lint: `ruff check . && ruff format --check .` (when wired).
5. Open a PR.

### Pre-commit gate

Every commit must pass:
- `pytest` baseline (currently 136 tests at v0.1.0; growing as Catch-up Plan v2 phases land).
- `bash -n` on every shell script touched.
- No new RU-jurisdiction services (see `~/.claude/projects/.../memory/no_russian_services.md` rationale).

## Plan reference

The active multi-sprint roadmap is in `~/.claude/plans/delightful-stirring-mitten.md` (Catch-up Plan v2 section).
