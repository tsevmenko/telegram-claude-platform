"""Parse ``claude -p --output-format stream-json`` line-by-line output.

The CLI emits one JSON object per line. Top-level event types we care about:

- ``system`` (subtype=``init``) — session metadata, model, tools.
- ``assistant`` — assistant message envelope; the interesting work is in
  ``message.content[]`` with content-block types ``thinking``, ``text``,
  ``tool_use``.
- ``user`` — synthetic ``tool_result`` echoes (after each tool call).
- ``result`` (subtype=``success`` or ``error_*``) — final outcome with
  ``result`` field carrying the final text.

We yield typed events that ``BoundaryTracker`` consumes to build live UI.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StreamEvent:
    kind: str
    """One of: init | text | thinking | tool_use | tool_result | todo |
    subagent_start | subagent_stop | final | unknown."""
    data: dict[str, Any] = field(default_factory=dict)


def parse_line(line: str) -> StreamEvent | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return StreamEvent(kind="unknown", data={"raw": line})

    return _classify(obj)


def _classify(obj: dict[str, Any]) -> StreamEvent:
    top = obj.get("type")

    if top == "system" and obj.get("subtype") == "init":
        return StreamEvent(
            kind="init",
            data={
                "session_id": obj.get("session_id", ""),
                "model": obj.get("model", ""),
                "tools": obj.get("tools", []),
            },
        )

    if top == "result":
        return StreamEvent(
            kind="final",
            data={
                "is_error": obj.get("is_error", False),
                "subtype": obj.get("subtype", ""),
                "text": obj.get("result", ""),
                "duration_ms": obj.get("duration_ms", 0),
                "total_cost_usd": obj.get("total_cost_usd", 0.0),
            },
        )

    if top == "assistant":
        msg = obj.get("message", {})
        content = msg.get("content", [])
        # An assistant message may carry several blocks. We emit one event
        # per block so the renderer can update incrementally.
        events = list(_assistant_blocks(content))
        if len(events) == 1:
            return events[0]
        # Bundle multiple blocks into a synthetic "batch" event the consumer
        # can iterate over. For simplicity we just return the first; the
        # parse_line caller is expected to handle multi-block via parse_obj
        # which yields all events.
        return events[0] if events else StreamEvent(kind="unknown", data=obj)

    if top == "user":
        # tool_result echoes after a tool finishes. The block structure is
        # ``message.content[].type == "tool_result"`` with output text.
        msg = obj.get("message", {})
        content = msg.get("content", [])
        for block in content:
            if block.get("type") == "tool_result":
                return StreamEvent(
                    kind="tool_result",
                    data={
                        "tool_use_id": block.get("tool_use_id", ""),
                        "content": _stringify_tool_result(block.get("content", "")),
                        "is_error": block.get("is_error", False),
                    },
                )
        return StreamEvent(kind="unknown", data=obj)

    return StreamEvent(kind="unknown", data=obj)


def _assistant_blocks(blocks: list[dict[str, Any]]) -> list[StreamEvent]:
    out: list[StreamEvent] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "thinking":
            out.append(StreamEvent(kind="thinking", data={"text": block.get("thinking", "")}))
        elif btype == "text":
            out.append(StreamEvent(kind="text", data={"text": block.get("text", "")}))
        elif btype == "tool_use":
            tool_input = block.get("input", {}) or {}
            event_kind = "tool_use"
            data = {
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "input": tool_input,
            }
            # Special-case TodoWrite to emit a `todo` event with structured items.
            if block.get("name") == "TodoWrite":
                data["todos"] = tool_input.get("todos", [])
                event_kind = "todo"
            elif block.get("name") == "Task":
                data["description"] = tool_input.get("description", "")
                data["subagent_type"] = tool_input.get("subagent_type", "")
                event_kind = "subagent_start"
            out.append(StreamEvent(kind=event_kind, data=data))
        else:
            out.append(StreamEvent(kind="unknown", data=block))
    return out


def _stringify_tool_result(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(raw)


async def parse_stream(lines: AsyncIterator[str]) -> AsyncIterator[StreamEvent]:
    """Parse a stream of stdout lines, yielding one event per content block."""
    async for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            yield StreamEvent(kind="unknown", data={"raw": line})
            continue

        if obj.get("type") == "assistant":
            content = obj.get("message", {}).get("content", [])
            for ev in _assistant_blocks(content):
                yield ev
        else:
            ev = _classify(obj)
            if ev:
                yield ev
