"""T26-adapted: production code references only opus/sonnet 4.7.

Author's T26 also forbids OpenRouter, requires Codex GPT-5 second reviewer,
and asserts "Sonnet for code review forbidden". We drop those assertions —
our model strategy is opus + sonnet from Anthropic only, with no Codex
double-review path.

Skill files are EXEMPT — `codex-review` skill legitimately mentions GPT models
in its description, and `web-research` may mention Perplexity Sonar.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
SKIP_NAMES = {".synced-from-sha"}

# Files in these subtrees are skipped — they legitimately mention other models.
SKILL_TREE = REPO_ROOT / "workspace-template" / "skills"
DOCS_TREE = REPO_ROOT / "docs"  # docs may compare against author's model lineup

# Production code roots we DO scan.
PRODUCTION_TREES = [
    REPO_ROOT / "gateway" / "src",
    REPO_ROOT / "openviking-lite" / "src",
    REPO_ROOT / "installer",
]


def _production_files() -> list[Path]:
    out: list[Path] = []
    for root in PRODUCTION_TREES:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.name in SKIP_NAMES:
                continue
            if path.suffix not in {".py", ".sh", ".tmpl", ".md", ".json", ".yml", ".yaml"}:
                continue
            out.append(path)
    return out


# ---------------------------------------------------------------------------
# Model name references
# ---------------------------------------------------------------------------


def test_no_openrouter_in_production_code() -> None:
    """Author rule: never route Opus through OpenRouter — only via Anthropic
    Max or native API. We adopt the same constraint."""
    leaks: list[Path] = []
    for path in _production_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "openrouter.ai" in text.lower() or "openrouter" in text.lower():
            leaks.append(path.relative_to(REPO_ROOT))
    assert not leaks, f"production code mentions OpenRouter: {leaks}"


def test_no_gpt_models_in_production_code() -> None:
    """Production code uses Anthropic models only. GPT references in non-skill
    code are a sign of accidental drift toward an OpenAI runtime path."""
    skill_paths = {p.resolve() for p in SKILL_TREE.rglob("*") if p.is_file()}
    docs_paths = {p.resolve() for p in DOCS_TREE.rglob("*") if p.is_file()}
    pattern = re.compile(r"\bgpt-[\w.\-]+", flags=re.IGNORECASE)
    leaks: list[tuple[Path, str]] = []
    for path in _production_files():
        # Skip skills + docs trees (skills like codex-review reference GPT
        # legitimately; docs may discuss alternatives in comparison text).
        rp = path.resolve()
        if rp in skill_paths or rp in docs_paths:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        m = pattern.search(text)
        if m:
            leaks.append((path.relative_to(REPO_ROOT), m.group(0)))
    assert not leaks, f"production code references gpt-* models: {leaks}"


@pytest.mark.parametrize(
    "valid_model",
    [
        "opus",         # short alias accepted by `claude --model`
        "sonnet",       # ditto
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-opus-4-7",
        "claude-sonnet-4-7",
    ],
)
def test_model_aliases_appear_somewhere_in_production(valid_model: str) -> None:
    """Sanity check: at least one of the accepted Anthropic model identifiers
    is referenced in production code or installer config templates. If this
    suite ever stops finding any of them, someone has neutralised the model
    layer entirely — surface it."""
    found = False
    for path in _production_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if valid_model in text:
            found = True
            break
    # We don't fail if a SPECIFIC model is absent — Anthropic releases come and
    # go. What we want is that AT LEAST one of the parametrized values is
    # referenced. Use a session-scoped collector via xfail strict=False:
    # actually simpler — just assert non-empty across the parametrize union.
    # Implementation: collect into a class-attr; fail in a final test.
    if found:
        _present_models.add(valid_model)


_present_models: set[str] = set()


def test_at_least_one_anthropic_model_referenced() -> None:
    """Aggregate of the previous parametrized test."""
    assert _present_models, (
        "no recognised opus/sonnet model identifier found in production code"
    )


def test_no_codex_double_review_in_production() -> None:
    """Author's pipeline does Opus + Codex GPT-5 cross-review. We don't.
    A cross-reference to Codex in non-skill code would mean someone wired
    that path in by mistake."""
    skill_paths = {p.resolve() for p in SKILL_TREE.rglob("*") if p.is_file()}
    docs_paths = {p.resolve() for p in DOCS_TREE.rglob("*") if p.is_file()}
    leaks: list[Path] = []
    for path in _production_files():
        rp = path.resolve()
        if rp in skill_paths or rp in docs_paths:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"\bcodex\b", text, flags=re.IGNORECASE):
            leaks.append(path.relative_to(REPO_ROOT))
    assert not leaks, (
        f"production code references Codex outside skills/: {leaks}"
    )
