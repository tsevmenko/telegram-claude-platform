#!/usr/bin/env python3
"""Learnings-engine — capture / score / lint / promote.

Pipeline (per workshop methodology):

    user correction
        → correction-detector.sh (trigger match)
        → learnings-engine capture       (append/upsert episode in episodes.jsonl)
        → learnings-engine score         (composite score per episode)
        → learnings-engine lint          (flag HOT / STALE / PROMOTE candidates)
        → learnings-engine promote       (write a proposal for self-compiler)

Episode schema (one JSONL line per episode in core/episodes.jsonl):

    {
        "id": "EP-20260427-001",
        "type": "correction",
        "lang": "ru|uk|en",
        "trigger": "<exact phrase that fired>",
        "context": "<truncated user prompt>",
        "first_seen": "2026-04-27T10:00:00Z",
        "last_seen":  "2026-04-27T10:00:00Z",
        "freq": 1,
        "impact": "medium",
        "tags": [],
        "status": "active|stale|promoted|archived"
    }

Composite score = recency * 0.4 + frequency * 0.3 + impact * 0.3
- recency:   1 - min(days_since_last_seen / 30, 1)
- frequency: min(freq / 3, 1)
- impact:    {critical:1.0, high:0.7, medium:0.4, low:0.1}

Flags:
- score >= 0.8 OR freq >= 3 → PROMOTE candidate
- score <  0.15              → STALE
- freq  >= 3                 → HOT (rule isn't sticking; needs a system change)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

IMPACT_WEIGHTS = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}
RECENCY_WINDOW_DAYS = 30.0
FREQ_CAP = 3
DEDUP_WINDOW_HOURS = 24  # same trigger within 24h → bump freq, not new episode
PROMOTE_SCORE = 0.8
STALE_SCORE = 0.15

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def episodes_path(workspace: Path) -> Path:
    return workspace / "core" / "episodes.jsonl"


def learnings_path(workspace: Path) -> Path:
    return workspace / "core" / "LEARNINGS.md"


def proposals_path(workspace: Path) -> Path:
    return workspace / "core" / "PROPOSALS.md"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_episodes(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def save_episodes(path: Path, episodes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for ep in episodes:
            f.write(json.dumps(ep, ensure_ascii=False) + "\n")
    tmp.replace(path)


def next_id(episodes: list[dict]) -> str:
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    seq = 1
    for ep in episodes:
        eid = ep.get("id", "")
        if eid.startswith(f"EP-{today}-"):
            try:
                n = int(eid.rsplit("-", 1)[1])
                seq = max(seq, n + 1)
            except ValueError:
                continue
    return f"EP-{today}-{seq:03d}"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def episode_score(ep: dict, *, now: dt.datetime | None = None) -> float:
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    last_seen = ep.get("last_seen") or ep.get("first_seen") or now_iso()
    try:
        last = parse_iso(last_seen)
    except ValueError:
        last = now
    age_days = max(0.0, (now - last).total_seconds() / 86400.0)
    recency = max(0.0, 1.0 - min(age_days / RECENCY_WINDOW_DAYS, 1.0))
    freq = min(ep.get("freq", 1) / FREQ_CAP, 1.0)
    impact = IMPACT_WEIGHTS.get(ep.get("impact", "medium"), 0.4)
    return round(recency * 0.4 + freq * 0.3 + impact * 0.3, 4)


def classify(ep: dict, score: float) -> list[str]:
    flags: list[str] = []
    freq = ep.get("freq", 1)
    if score >= PROMOTE_SCORE or freq >= FREQ_CAP:
        flags.append("PROMOTE")
    if freq >= FREQ_CAP:
        flags.append("HOT")
    if score < STALE_SCORE:
        flags.append("STALE")
    return flags


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_capture(args: argparse.Namespace) -> int:
    """Append a correction episode (or bump freq if a duplicate within 24h)."""
    ws = Path(args.workspace)
    ep_path = episodes_path(ws)
    episodes = load_episodes(ep_path)

    trigger = args.trigger.strip()
    lang = args.lang or "en"
    prompt_snippet = (args.prompt or "")[:240].replace("\n", " ")

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=DEDUP_WINDOW_HOURS)

    # Look for a matching active episode within the dedup window.
    bumped = False
    for ep in episodes:
        if ep.get("status", "active") != "active":
            continue
        if ep.get("trigger") != trigger or ep.get("lang") != lang:
            continue
        try:
            seen = parse_iso(ep.get("last_seen") or ep.get("first_seen") or now_iso())
        except ValueError:
            seen = now
        if seen >= cutoff:
            ep["freq"] = ep.get("freq", 1) + 1
            ep["last_seen"] = now_iso()
            bumped = True
            break

    if not bumped:
        episodes.append({
            "id":         next_id(episodes),
            "type":       "correction",
            "lang":       lang,
            "trigger":    trigger,
            "context":    prompt_snippet,
            "first_seen": now_iso(),
            "last_seen":  now_iso(),
            "freq":       1,
            "impact":     args.impact,
            "tags":       [t for t in (args.tags or "").split(",") if t.strip()],
            "status":     "active",
        })

    save_episodes(ep_path, episodes)

    # Mirror to human-readable LEARNINGS.md.
    lp = learnings_path(ws)
    lp.parent.mkdir(parents=True, exist_ok=True)
    if not lp.exists():
        lp.write_text("# LEARNINGS — Lessons archive\n\n", encoding="utf-8")
    with lp.open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} [{lang}] CORRECTION-FLAG trigger=\"{trigger}\": {prompt_snippet}\n")

    print(f"captured: {trigger} (lang={lang}, freq-bump={bumped})")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    ws = Path(args.workspace)
    episodes = load_episodes(episodes_path(ws))
    if not episodes:
        print("no episodes")
        return 0
    rows = []
    for ep in episodes:
        s = episode_score(ep)
        flags = classify(ep, s)
        rows.append((s, ep, flags))
    rows.sort(key=lambda r: -r[0])

    if args.format == "json":
        out = [
            {"id": ep["id"], "score": s, "freq": ep.get("freq", 1),
             "lang": ep.get("lang", ""), "trigger": ep.get("trigger", ""),
             "flags": flags, "status": ep.get("status", "active")}
            for s, ep, flags in rows
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"{'SCORE':>5} {'FREQ':>4} {'LANG':>4} {'FLAGS':<22} {'TRIGGER'}")
        for s, ep, flags in rows:
            tag = ",".join(flags) or "-"
            print(f"{s:>5.2f} {ep.get('freq', 1):>4} {ep.get('lang', ''):>4} {tag:<22} {ep.get('trigger', '')}")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    ws = Path(args.workspace)
    episodes = load_episodes(episodes_path(ws))
    promote = []
    stale = []
    hot = []
    for ep in episodes:
        if ep.get("status", "active") != "active":
            continue
        s = episode_score(ep)
        flags = classify(ep, s)
        if "PROMOTE" in flags:
            promote.append((s, ep))
        if "STALE" in flags:
            stale.append((s, ep))
        if "HOT" in flags:
            hot.append((s, ep))

    out = {
        "promote": [{"id": ep["id"], "score": s, "trigger": ep.get("trigger", "")}
                    for s, ep in promote],
        "hot":     [{"id": ep["id"], "score": s, "freq": ep.get("freq", 1),
                     "trigger": ep.get("trigger", "")} for s, ep in hot],
        "stale":   [{"id": ep["id"], "score": s, "trigger": ep.get("trigger", "")}
                    for s, ep in stale],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Write a promotion proposal to PROPOSALS.md and mark the episode 'promoted'.

    The actual CLAUDE.md edit is performed by the self-compiler skill — this
    command only captures intent. Human (or self-compiler) reviews PROPOSALS.md
    and merges into CLAUDE.md.
    """
    ws = Path(args.workspace)
    ep_path = episodes_path(ws)
    episodes = load_episodes(ep_path)

    targets: list[tuple[float, dict]] = []
    if args.id:
        for ep in episodes:
            if ep["id"] == args.id and ep.get("status", "active") == "active":
                targets.append((episode_score(ep), ep))
                break
    else:
        for ep in episodes:
            if ep.get("status", "active") != "active":
                continue
            s = episode_score(ep)
            if "PROMOTE" in classify(ep, s):
                targets.append((s, ep))

    if not targets:
        print("no promotion candidates")
        return 0

    pp = proposals_path(ws)
    pp.parent.mkdir(parents=True, exist_ok=True)
    if not pp.exists():
        pp.write_text(
            "# PROPOSALS — pending CLAUDE.md changes\n\n"
            "_Generated by `learnings-engine promote`._\n"
            "_Reviewed by the self-compiler skill or the operator manually._\n\n",
            encoding="utf-8",
        )

    with pp.open("a", encoding="utf-8") as f:
        for s, ep in targets:
            f.write(
                f"## {ep['id']} (score={s:.2f}, freq={ep.get('freq', 1)}, "
                f"lang={ep.get('lang', '?')})\n"
                f"- **trigger:** `{ep.get('trigger', '')}`\n"
                f"- **context:** {ep.get('context', '')[:200]}\n"
                f"- **proposed rule:** _the agent should append a concrete rule "
                f"to CLAUDE.md so this correction stops repeating_\n\n"
            )
            ep["status"] = "promoted"

    save_episodes(ep_path, episodes)
    print(f"wrote {len(targets)} proposal(s) to {pp}")
    return 0


def cmd_archive_stale(args: argparse.Namespace) -> int:
    """Move STALE episodes to status='stale' so they drop out of active scoring."""
    ws = Path(args.workspace)
    ep_path = episodes_path(ws)
    episodes = load_episodes(ep_path)
    moved = 0
    for ep in episodes:
        if ep.get("status", "active") != "active":
            continue
        s = episode_score(ep)
        if "STALE" in classify(ep, s):
            ep["status"] = "stale"
            moved += 1
    save_episodes(ep_path, episodes)
    print(f"archived {moved} stale episode(s)")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="learnings-engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("capture", help="Record a correction episode.")
    sp.add_argument("--workspace", required=True)
    sp.add_argument("--trigger",   required=True)
    sp.add_argument("--lang",      default="en", choices=["en", "ru", "uk"])
    sp.add_argument("--prompt",    default="")
    sp.add_argument("--impact",    default="medium",
                    choices=["critical", "high", "medium", "low"])
    sp.add_argument("--tags",      default="")
    sp.set_defaults(fn=cmd_capture)

    sp = sub.add_parser("score", help="Score every episode (sorted desc).")
    sp.add_argument("--workspace", required=True)
    sp.add_argument("--format",    default="text", choices=["text", "json"])
    sp.set_defaults(fn=cmd_score)

    sp = sub.add_parser("lint", help="Emit JSON of HOT/STALE/PROMOTE candidates.")
    sp.add_argument("--workspace", required=True)
    sp.set_defaults(fn=cmd_lint)

    sp = sub.add_parser("promote", help="Write proposal(s) and mark episode(s) promoted.")
    sp.add_argument("--workspace", required=True)
    sp.add_argument("--id", default=None,
                    help="Promote a specific episode by id (default: all PROMOTE-flagged).")
    sp.set_defaults(fn=cmd_promote)

    sp = sub.add_parser("archive-stale", help="Mark STALE episodes as inactive.")
    sp.add_argument("--workspace", required=True)
    sp.set_defaults(fn=cmd_archive_stale)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
