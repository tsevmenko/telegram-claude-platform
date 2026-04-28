"""Tests for `workspace-template/hooks/local-recall.sh`.

Local-recall fires on UserPromptSubmit alongside auto-recall. It greps over
local memory files (TOOLS.md, AGENTS.md, LEARNINGS.md, warm/decisions.md) and
emits hits inside `<local-context>...</local-context>`.

Failure modes we guard:
- short prompt → silent exit (don't waste cycles)
- no files → silent exit
- no matches → silent exit (no empty XML block)
- hits → properly wrapped, deduplicated, length-capped
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "workspace-template" / "hooks" / "local-recall.sh"


def _run(workspace: Path, prompt: str) -> tuple[int, str]:
    """Run the hook against a fake workspace, return (exit_code, stdout)."""
    hook_at = workspace / "hooks" / "local-recall.sh"
    if not hook_at.exists():
        (workspace / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOOK, hook_at)
        hook_at.chmod(0o755)
    payload = json.dumps({"prompt": prompt})
    proc = subprocess.run(
        [str(hook_at)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return proc.returncode, proc.stdout


def _make_ws(tmp_path: Path, files: dict[str, str]) -> Path:
    ws = tmp_path / "ws"
    (ws / "core" / "warm").mkdir(parents=True)
    for rel, content in files.items():
        target = ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return ws


def test_outputs_xml_block_on_match(tmp_path: Path) -> None:
    ws = _make_ws(
        tmp_path,
        {
            "core/TOOLS.md": "## Rate limits\n- Stripe API rate limit is 100 RPM per key\n",
        },
    )
    code, out = _run(ws, "what is the rate limit on our API")
    assert code == 0
    assert "<local-context>" in out
    assert "</local-context>" in out
    assert "Stripe API rate limit" in out
    assert "core/TOOLS.md" in out


def test_silent_when_files_missing(tmp_path: Path) -> None:
    """No core/ at all — must exit 0 with no output (don't crash, don't emit empty XML)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    code, out = _run(ws, "any rate limit info")
    assert code == 0
    assert out == ""


def test_silent_on_short_prompt(tmp_path: Path) -> None:
    ws = _make_ws(tmp_path, {"core/TOOLS.md": "rate limit info"})
    code, out = _run(ws, "hi")
    assert code == 0
    assert out == ""


def test_silent_on_no_match(tmp_path: Path) -> None:
    ws = _make_ws(
        tmp_path,
        {"core/TOOLS.md": "## Database\n- Postgres on 5432\n"},
    )
    # Prompt has no shared keywords with file content.
    code, out = _run(ws, "tell me about kubernetes deployment strategies")
    assert code == 0
    assert out == ""


def test_dedups_repeated_lines(tmp_path: Path) -> None:
    """Same line matching multiple keywords must appear only once in output."""
    ws = _make_ws(
        tmp_path,
        {
            "core/TOOLS.md": "rate limit on Stripe API is 100 RPM\n",
        },
    )
    code, out = _run(ws, "what is the rate limit on our Stripe API")
    assert code == 0
    # The single source line should appear exactly once even though it matches
    # multiple keywords ("rate", "limit", "stripe", "API").
    occurrences = out.count("rate limit on Stripe API is 100 RPM")
    assert occurrences == 1, f"expected 1 occurrence, got {occurrences}: {out!r}"


def test_searches_all_four_canonical_files(tmp_path: Path) -> None:
    ws = _make_ws(
        tmp_path,
        {
            "core/TOOLS.md": "kubernetes deployment guide here\n",
            "core/AGENTS.md": "kubernetes is the orchestrator\n",
            "core/LEARNINGS.md": "kubernetes lesson: use Deployments not Pods\n",
            "core/warm/decisions.md": "## decision: use kubernetes 1.30 not 1.31\n",
        },
    )
    code, out = _run(ws, "tell me about kubernetes orchestration setup")
    assert code == 0
    assert "core/TOOLS.md" in out
    assert "core/AGENTS.md" in out
    assert "core/LEARNINGS.md" in out
    assert "core/warm/decisions.md" in out


def test_does_not_block_on_invalid_json(tmp_path: Path) -> None:
    """Hook must never block the prompt — invalid JSON in → exit 0 silent."""
    ws = _make_ws(tmp_path, {"core/TOOLS.md": "ok\n"})
    hook_at = ws / "hooks" / "local-recall.sh"
    if not hook_at.exists():
        (ws / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(HOOK, hook_at)
        hook_at.chmod(0o755)
    proc = subprocess.run(
        [str(hook_at)],
        input="not-json-at-all",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0


@pytest.mark.parametrize("stop_word", ["the", "and", "for", "that"])
def test_drops_stop_words(tmp_path: Path, stop_word: str) -> None:
    """Stop words must not produce hits (otherwise every prompt grep-hits everything)."""
    ws = _make_ws(
        tmp_path,
        {
            "core/TOOLS.md": f"the database the cluster the system\n",
        },
    )
    # Prompt with mostly stop words — should NOT generate output from those.
    code, out = _run(ws, f"{stop_word} {stop_word} {stop_word}")
    assert code == 0
    # Either silent (preferred) or, if any hits, none should be the stop word.
    if out:
        # The matched lines should not have come from stop-word matching.
        # Hard to assert directly; just check no XML block emitted with this lone keyword.
        assert "<local-context>" not in out, (
            f"stop word '{stop_word}' triggered local-context output"
        )
