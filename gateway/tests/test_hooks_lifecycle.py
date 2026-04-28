"""T18-equivalent: cross-cutting lifecycle checks for every hook script.

These complement `test_hooks.py` (which exercises individual hook behaviour)
with structural assertions that hold for ALL hooks:

- bash syntactically valid (`bash -n`)
- starts with `#!/usr/bin/env bash` shebang
- explicitly does not `set -e` (hooks must control exit codes themselves;
  Claude Code treats exit 2 as block, anything else as warn — we never want
  an unset variable to accidentally abort with a hard failure)
- doesn't reference `set -e` to keep author-style discipline
- has at least one comment explaining what it does
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = (
    Path(__file__).resolve().parents[2] / "workspace-template" / "hooks"
)


def _all_hooks() -> list[Path]:
    return sorted(HOOKS_DIR.glob("*.sh"))


@pytest.mark.parametrize(
    "hook",
    _all_hooks(),
    ids=lambda p: p.name,
)
def test_hook_is_syntactically_valid_bash(hook: Path) -> None:
    """`bash -n` parses but doesn't execute. Catches typos before live deploy."""
    proc = subprocess.run(
        ["bash", "-n", str(hook)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0, f"{hook.name}: bash -n failed:\n{proc.stderr}"


@pytest.mark.parametrize("hook", _all_hooks(), ids=lambda p: p.name)
def test_hook_has_shebang(hook: Path) -> None:
    first = hook.read_text(encoding="utf-8").splitlines()[0]
    assert first == "#!/usr/bin/env bash", (
        f"{hook.name}: first line must be '#!/usr/bin/env bash', got: {first!r}"
    )


@pytest.mark.parametrize("hook", _all_hooks(), ids=lambda p: p.name)
def test_hook_does_not_use_set_e(hook: Path) -> None:
    """Hooks must NEVER `set -e`.

    Claude Code's hook protocol uses exit codes meaningfully:
    - 0 = proceed
    - 2 = block (PreToolUse) or surface stderr to operator
    - any other non-zero = warn, but proceeds

    `set -e` aborts on the first failing command — even harmless ones like a
    grep with no match — and converts soft failures into hard exits, which
    can accidentally block legitimate prompts. Use `set +e` (or no `set` at
    all) and check return codes explicitly when needed.
    """
    text = hook.read_text(encoding="utf-8")
    # Allow `set +e` (explicit OFF) and `set -euo pipefail` is also discouraged
    # for hook scripts but cron scripts in scripts/ are different — only
    # check hooks here.
    bad = re.search(r"^\s*set\s+-e\b", text, flags=re.MULTILINE)
    assert bad is None, (
        f"{hook.name}: hook scripts must not `set -e`. "
        f"Use explicit return-code checks instead (line: {bad.group(0).strip()!r})"
    )


@pytest.mark.parametrize("hook", _all_hooks(), ids=lambda p: p.name)
def test_hook_has_a_comment(hook: Path) -> None:
    """Every hook should have at least one explanatory comment after shebang."""
    lines = hook.read_text(encoding="utf-8").splitlines()
    # Skip shebang and empty lines, find first comment OR code.
    saw_comment = False
    for line in lines[1:20]:  # check first 20 lines
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            saw_comment = True
            break
        # Hit code without seeing a comment.
        break
    assert saw_comment, f"{hook.name}: missing explanatory comment after shebang"


@pytest.mark.parametrize("hook", _all_hooks(), ids=lambda p: p.name)
def test_hook_is_executable(hook: Path) -> None:
    """Hooks must be `chmod +x` so the installer can register them directly."""
    mode = hook.stat().st_mode
    # Owner exec bit (S_IXUSR = 0o100)
    assert mode & 0o100, f"{hook.name}: not chmod +x (mode={oct(mode)})"


def test_at_least_thirteen_hooks_present() -> None:
    """v2 catch-up adds local-recall.sh on top of the 12 baseline hooks.

    13 total at this point. If something deletes a hook, this test reminds
    you to update both `settings.json.tmpl` and `docs/HOOKS.md` to match.
    """
    hooks = _all_hooks()
    assert len(hooks) >= 13, (
        f"only {len(hooks)} hooks found in {HOOKS_DIR}; expected ≥ 13"
    )


def test_every_hook_is_referenced_in_settings_template() -> None:
    """If a hook exists on disk but isn't registered in settings.json.tmpl, it
    will never fire — likely an orphan from a removed feature. Either delete
    the file or add a registration."""
    settings_tmpl = (
        Path(__file__).resolve().parents[2]
        / "installer"
        / "templates"
        / "claude"
        / "settings.json.tmpl"
    )
    settings_text = settings_tmpl.read_text(encoding="utf-8")
    orphans: list[str] = []
    for hook in _all_hooks():
        if hook.name not in settings_text:
            orphans.append(hook.name)
    assert not orphans, (
        f"hooks present on disk but not registered in settings.json.tmpl: "
        f"{orphans}"
    )


def test_every_settings_referenced_hook_exists() -> None:
    """Mirror of the previous test: registration without a file is a 404."""
    settings_tmpl = (
        Path(__file__).resolve().parents[2]
        / "installer"
        / "templates"
        / "claude"
        / "settings.json.tmpl"
    )
    text = settings_tmpl.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\{\{HOOKS_DIR\}\}/([\w\-]+\.sh)", text))
    on_disk = {p.name for p in _all_hooks()}
    missing = referenced - on_disk
    assert not missing, (
        f"settings.json.tmpl references missing hook scripts: {missing}"
    )
