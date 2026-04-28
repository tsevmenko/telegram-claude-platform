# Superpowers (vendored as a pinned upstream clone)

The Superpowers workflow skills (~15 — `brainstorming`, `writing-plans`,
`executing-plans`, `test-driven-development`, `systematic-debugging`,
`requesting-code-review`, `verification-before-completion`,
`dispatching-parallel-agents`, plus more) are NOT forked into this repo.
Instead `telegram-claude-platform/installer/lib/55-plugins.sh` clones
`pcvelz/superpowers` into each agent's `~/.claude/plugins/superpowers/`
at install time, pinned to a specific commit SHA.

## Why not fork

Forking 15 skills means we'd be on the hook to keep them merged with upstream
fixes / new patterns. Pinning the SHA gives us:

- Reproducible installs — every fresh VPS gets the same plugin code.
- Fail-closed safety: `installer/lib/00-preflight.sh::verify_pins` resolves
  the SHA against the GitHub API before install. If upstream rebases or
  deletes the commit, the installer aborts loudly rather than fetching
  unknown code.
- Trivial upgrades: bump `SUPERPOWERS_SHA` in `installer/PINS`, rerun the
  installer, verify the diff before committing.

## Where the SHA lives

- `telegram-claude-platform/installer/PINS` → `SUPERPOWERS_SHA=<sha>`
- `telegram-claude-platform/installer/PINS.repos` → `SUPERPOWERS_SHA=pcvelz/superpowers`
- `telegram-claude-platform/installer/lib/55-plugins.sh` → reads the SHA at install time

## When to fork

If upstream goes inactive, deletes the repo, changes license away from MIT,
or accumulates regressions we can't tolerate, fork into this repo as
`agent-skills/skills/sp-*` per skill. Until then the pin-and-clone path is
strictly less work.

## Manual upgrade

```bash
# 1. Pick a new SHA from upstream (verify it builds + passes their tests)
NEW_SHA=$(gh api repos/pcvelz/superpowers/commits/main --jq .sha)

# 2. Update the pin
sed -i "s/^SUPERPOWERS_SHA=.*/SUPERPOWERS_SHA=$NEW_SHA/" \
    ~/projects/telegram-claude-platform/installer/PINS

# 3. Re-run the installer on a test VPS, verify nothing broke
# 4. Commit the PINS bump separately so it can be rolled back independently.
```
