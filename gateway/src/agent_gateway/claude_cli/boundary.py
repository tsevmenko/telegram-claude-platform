"""Build a compact live status view from a stream of ``StreamEvent``s.

Renders a single Telegram message that the consumer keeps editing as new
events arrive. The status format aims to be mobile-friendly and information-
dense:

    working — 45s

    <thinking snippet, 3-4 lines>

    ▸ bash git status
    ▸ read /etc/hosts
    ▸ ... +2 earlier

    ▰▰▰▰▰▱▱▱▱▱ 50%
      x done task
      > in-progress task
        pending task

    1 | researcher — done
    2 | writer ← now
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from agent_gateway.claude_cli.stream_parser import StreamEvent

PROGRESS_BAR_WIDTH = 10
ACTIVITY_WINDOW = 5
THINKING_LINES = 4

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|bearer)[\s:=]+\S+"),
    re.compile(r"(ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def mask_secrets(text: str) -> str:
    out = text
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[redacted]", out)
    return out


@dataclass
class ToolCall:
    tag: str
    name: str
    detail: str


@dataclass
class TodoItem:
    content: str
    status: str  # "pending" | "in_progress" | "completed"


@dataclass
class Subagent:
    label: str
    description: str
    status: str  # "running" | "done"
    summary: str = ""


@dataclass
class BoundaryTracker:
    """Aggregates stream events into a compact rendered status string."""

    started_at: float = field(default_factory=time.time)
    final_text: str = ""

    _thinking: str = ""
    _tool_calls: list[ToolCall] = field(default_factory=list)
    _todos: list[TodoItem] = field(default_factory=list)
    _subagents: list[Subagent] = field(default_factory=list)
    _pending_subagent_by_id: dict[str, int] = field(default_factory=dict)

    def feed(self, event: StreamEvent) -> None:
        if event.kind == "thinking":
            self._thinking = self._truncate_thinking(event.data.get("text", ""))
        elif event.kind == "text":
            # Plain text deltas accumulate into final_text. The final result
            # event also carries the full text, but tracking deltas lets us
            # show prose-in-progress for streaming_mode=progress.
            self.final_text += event.data.get("text", "")
        elif event.kind == "tool_use":
            self._tool_calls.append(self._summarise_tool(event.data))
        elif event.kind == "todo":
            todos = event.data.get("todos", [])
            self._todos = [
                TodoItem(content=t.get("content", ""), status=t.get("status", "pending"))
                for t in todos
            ]
        elif event.kind == "subagent_start":
            label = event.data.get("subagent_type") or "subagent"
            description = event.data.get("description", "")
            sa = Subagent(label=label, description=description, status="running")
            idx = len(self._subagents)
            self._subagents.append(sa)
            sa_id = event.data.get("id", "")
            if sa_id:
                self._pending_subagent_by_id[sa_id] = idx
        elif event.kind == "tool_result":
            tool_id = event.data.get("tool_use_id", "")
            idx = self._pending_subagent_by_id.pop(tool_id, None)
            if idx is not None and 0 <= idx < len(self._subagents):
                self._subagents[idx].status = "done"
                self._subagents[idx].summary = self._truncate(event.data.get("content", ""), 60)
        elif event.kind == "final":
            text = event.data.get("text", "")
            if text:
                self.final_text = text

    def render_status(self) -> str:
        elapsed = int(time.time() - self.started_at)
        lines: list[str] = [f"working — {elapsed}s"]

        if self._thinking:
            lines.append("")
            lines.append(self._thinking)

        if self._tool_calls:
            lines.append("")
            lines.extend(self._render_activity())

        if self._todos:
            lines.append("")
            lines.extend(self._render_todos())

        if self._subagents:
            lines.append("")
            lines.extend(self._render_subagents())

        return "\n".join(lines).strip()

    def render_final(self) -> str:
        return self.final_text.strip()

    # ------------------------------------------------------------------

    def _summarise_tool(self, data: dict[str, Any]) -> ToolCall:
        name = data.get("name", "")
        tinput = data.get("input", {}) or {}
        detail = self._humanise_tool(name, tinput)
        return ToolCall(tag="tool", name=name, detail=mask_secrets(detail))

    @staticmethod
    def _humanise_tool(name: str, tinput: dict[str, Any]) -> str:
        if name == "Bash":
            return f"bash {tinput.get('command', '')[:80]}"
        if name == "Read":
            return f"read {tinput.get('file_path', '')}"
        if name in ("Edit", "Write"):
            return f"{name.lower()} {tinput.get('file_path', '')}"
        if name in ("Grep", "Glob"):
            return f"{name.lower()} {tinput.get('pattern', '')}"
        if name == "WebFetch":
            return f"webfetch {tinput.get('url', '')[:60]}"
        if name == "WebSearch":
            return f"websearch {tinput.get('query', '')[:60]}"
        if name == "Task":
            return f"task {tinput.get('description', '')[:60]}"
        return name.lower()

    def _render_activity(self) -> list[str]:
        total = len(self._tool_calls)
        recent = self._tool_calls[-ACTIVITY_WINDOW:]
        lines: list[str] = []
        if total > len(recent):
            lines.append(f"▸ ... +{total - len(recent)} earlier")
        for tc in recent:
            lines.append(f"▸ {tc.detail[:80]}")
        return lines

    def _render_todos(self) -> list[str]:
        done = sum(1 for t in self._todos if t.status == "completed")
        total = len(self._todos)
        bar = self._progress_bar(done, total)
        out = [bar]
        # Show last completed (if any), all in-progress, and up to 2 pending.
        completed = [t for t in self._todos if t.status == "completed"]
        in_progress = [t for t in self._todos if t.status == "in_progress"]
        pending = [t for t in self._todos if t.status == "pending"]

        if done > 1:
            out.append(f"  ... +{done - 1} done")
        if completed:
            out.append(f"  x {self._truncate(completed[-1].content, 60)}")
        for t in in_progress:
            out.append(f"  > {self._truncate(t.content, 60)}")
        for t in pending[:2]:
            out.append(f"    {self._truncate(t.content, 60)}")
        if len(pending) > 2:
            out.append(f"    ... +{len(pending) - 2} more")
        return out

    def _render_subagents(self) -> list[str]:
        total = len(self._subagents)
        out: list[str] = ["steps:"]
        start = max(0, total - 4)
        for i, sa in enumerate(self._subagents[start:], start=start + 1):
            if sa.status == "done":
                marker = f" — {sa.summary}" if sa.summary else ""
                out.append(f" {i} | {sa.label} — done{marker}")
            else:
                out.append(f" {i} | {sa.label} ← now")
        return out

    @staticmethod
    def _progress_bar(done: int, total: int) -> str:
        if total <= 0:
            return ""
        ratio = done / total
        filled = round(ratio * PROGRESS_BAR_WIDTH)
        bar = "▰" * filled + "▱" * (PROGRESS_BAR_WIDTH - filled)
        pct = int(ratio * 100)
        return f"{bar} {pct}%"

    @staticmethod
    def _truncate(text: str, length: int) -> str:
        text = text.replace("\n", " ").strip()
        return text[:length]

    @staticmethod
    def _truncate_thinking(text: str) -> str:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines[:THINKING_LINES])
