"""Tests for workspace-template/scripts/learnings-engine.py.

The engine is a workspace-template script (not part of the gateway package).
We import it directly via importlib.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ENGINE_PATH = (
    Path(__file__).resolve().parents[2]
    / "workspace-template" / "scripts" / "learnings-engine.py"
)


@pytest.fixture
def engine():
    spec = importlib.util.spec_from_file_location("learnings_engine", ENGINE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["learnings_engine"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture
def workspace(tmp_path: Path):
    (tmp_path / "core").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


def test_capture_creates_episode(engine, workspace, capsys):
    rc = engine.main([
        "capture",
        "--workspace", str(workspace),
        "--trigger", "не надо",
        "--lang", "ru",
        "--prompt", "не надо так делать",
    ])
    assert rc == 0
    body = (workspace / "core" / "episodes.jsonl").read_text()
    assert "не надо" in body
    ep = json.loads(body.strip().splitlines()[0])
    assert ep["lang"] == "ru"
    assert ep["freq"] == 1
    assert ep["status"] == "active"


def test_capture_dedup_within_window_bumps_freq(engine, workspace):
    for _ in range(3):
        engine.main([
            "capture",
            "--workspace", str(workspace),
            "--trigger", "не надо",
            "--lang", "ru",
            "--prompt", "...",
        ])
    eps = (workspace / "core" / "episodes.jsonl").read_text().strip().splitlines()
    assert len(eps) == 1
    ep = json.loads(eps[0])
    assert ep["freq"] == 3


def test_capture_different_triggers_separate_episodes(engine, workspace):
    engine.main(["capture", "--workspace", str(workspace),
                 "--trigger", "не надо", "--lang", "ru", "--prompt", "..."])
    engine.main(["capture", "--workspace", str(workspace),
                 "--trigger", "you forgot", "--lang", "en", "--prompt", "..."])
    eps = (workspace / "core" / "episodes.jsonl").read_text().strip().splitlines()
    assert len(eps) == 2


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def test_score_recent_episode_is_high(engine):
    ep = {"freq": 1, "impact": "medium", "first_seen": engine.now_iso(),
          "last_seen": engine.now_iso()}
    s = engine.episode_score(ep)
    # Just-created: recency≈1, freq≈0.33, impact=0.4
    # → 0.4 + 0.1 + 0.12 = 0.62 give or take
    assert 0.5 <= s <= 0.85


def test_score_old_episode_decays(engine):
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    ep = {"freq": 1, "impact": "low", "first_seen": old, "last_seen": old}
    s = engine.episode_score(ep)
    # Recency = 0, freq ≈ 0.33, impact = 0.1 → ≈ 0.13
    assert s < 0.2


def test_score_high_freq_promotes(engine):
    ep = {"freq": 5, "impact": "high", "first_seen": engine.now_iso(),
          "last_seen": engine.now_iso()}
    s = engine.episode_score(ep)
    flags = engine.classify(ep, s)
    assert "PROMOTE" in flags
    assert "HOT" in flags


def test_score_critical_impact_promotes_quickly(engine):
    ep = {"freq": 1, "impact": "critical", "first_seen": engine.now_iso(),
          "last_seen": engine.now_iso()}
    s = engine.episode_score(ep)
    # 0.4*1 + 0.3*(1/3) + 0.3*1.0 ≈ 0.8
    assert s >= 0.79


# ---------------------------------------------------------------------------
# lint + promote
# ---------------------------------------------------------------------------


def test_lint_buckets(engine, workspace, capsys):
    # Hot/promote: 3 captures of the same trigger → freq=3.
    for _ in range(3):
        engine.main([
            "capture", "--workspace", str(workspace),
            "--trigger", "you forgot", "--lang", "en", "--prompt", "...",
        ])
    capsys.readouterr()  # discard stdout from captures

    rc = engine.main(["lint", "--workspace", str(workspace)])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert any(p["trigger"] == "you forgot" for p in parsed["promote"])
    assert any(p["trigger"] == "you forgot" for p in parsed["hot"])
    assert rc == 0


def test_promote_writes_proposal_and_marks_episode(engine, workspace):
    for _ in range(3):
        engine.main(["capture", "--workspace", str(workspace),
                     "--trigger", "you forgot", "--lang", "en", "--prompt", "..."])
    engine.main(["promote", "--workspace", str(workspace)])

    proposals = (workspace / "core" / "PROPOSALS.md").read_text()
    assert "you forgot" in proposals

    ep = json.loads(
        (workspace / "core" / "episodes.jsonl").read_text().strip().splitlines()[0]
    )
    assert ep["status"] == "promoted"


def test_archive_stale(engine, workspace):
    # Manually craft a stale-looking episode.
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    ep_path = workspace / "core" / "episodes.jsonl"
    ep_path.parent.mkdir(parents=True, exist_ok=True)
    ep_path.write_text(json.dumps({
        "id": "EP-old", "type": "correction", "lang": "en",
        "trigger": "ancient", "context": "...", "first_seen": old,
        "last_seen": old, "freq": 1, "impact": "low", "tags": [],
        "status": "active",
    }) + "\n")
    engine.main(["archive-stale", "--workspace", str(workspace)])
    body = ep_path.read_text()
    assert '"status": "stale"' in body
