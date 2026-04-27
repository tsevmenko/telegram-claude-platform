---
name: skill-finder
description: "Discover and install Claude Code skills from public sources (skills.sh catalogue, GitHub repos). Use when: find a skill, install a skill, looking for a skill, what skills are available."
user-invocable: true
argument-hint: "<query-or-github-url>"
---

# Skill Finder

Discover new skills by keyword or install a skill straight from a GitHub URL.

## When to use

- The operator asks for a capability you don't have ("find me a skill for X").
- You see a TODO that would be cleaner as a reusable skill.
- You're given a `https://github.com/<owner>/<repo>` link to a SKILL.

## Two modes

### 1. Search the catalogue

```bash
bash $CLAUDE_SKILL_DIR/scripts/find.sh "google docs"
```

Returns a JSON list of matches (name, description, source URL). Backed by
the public skills.sh registry; falls back to a `gh search repos --topic
claude-skill <query>` search if skills.sh is unreachable.

### 2. Install a specific skill

```bash
bash $CLAUDE_SKILL_DIR/scripts/install.sh https://github.com/<owner>/<skill-repo>
```

The script:
1. Clones the repo (depth 1) into a temp directory.
2. Verifies a `SKILL.md` is at the root (or refuses).
3. Copies it to `<workspace>/.claude/skills/<repo-name>/`.
4. Sets executable bits on any `scripts/*.sh` and `scripts/*.py`.
5. Prints the description so you can confirm.

## Skills directory schema

Every skill in `<workspace>/.claude/skills/<name>/` has:

- `SKILL.md` (required) — YAML frontmatter (`name`, `description`, optional
  `user-invocable`, `argument-hint`) followed by the body Claude reads when
  the skill triggers.
- `scripts/` (optional) — bash / python helpers.

## Safety

- Always preview `SKILL.md` body and any helper scripts BEFORE installing
  on operator's machine. Don't execute helpers blindly.
- If a skill demands keys (Datawrapper, Perplexity, …), tell the operator
  where they go before adding the skill.
- Refuse skills that pipe `curl … | bash` from third-party URLs.
