"""BoundaryTracker rendering tests."""

from __future__ import annotations

from agent_gateway.claude_cli.boundary import BoundaryTracker, mask_secrets
from agent_gateway.claude_cli.stream_parser import StreamEvent


def _bt() -> BoundaryTracker:
    bt = BoundaryTracker(started_at=0.0)
    bt.started_at = 0  # ensure stable elapsed for snapshots
    return bt


def test_thinking_appears_in_status():
    bt = _bt()
    bt.feed(StreamEvent(kind="thinking", data={"text": "let me think\nabout this carefully"}))
    out = bt.render_status()
    assert "let me think" in out


def test_text_accumulates_into_final():
    bt = _bt()
    bt.feed(StreamEvent(kind="text", data={"text": "Hello "}))
    bt.feed(StreamEvent(kind="text", data={"text": "world"}))
    assert bt.render_final() == "Hello world"


def test_final_event_overrides_text():
    bt = _bt()
    bt.feed(StreamEvent(kind="text", data={"text": "delta"}))
    bt.feed(StreamEvent(kind="final", data={"text": "consolidated final"}))
    assert bt.render_final() == "consolidated final"


def test_tool_use_renders_in_activity():
    bt = _bt()
    bt.feed(StreamEvent(kind="tool_use", data={
        "name": "Bash", "input": {"command": "git status"}
    }))
    out = bt.render_status()
    assert "bash" in out.lower()
    assert "git status" in out


def test_activity_window_collapses_overflow():
    bt = _bt()
    for i in range(8):
        bt.feed(StreamEvent(kind="tool_use", data={
            "name": "Bash", "input": {"command": f"cmd-{i}"}
        }))
    out = bt.render_status()
    assert "+3 earlier" in out  # ACTIVITY_WINDOW=5, total=8
    assert "cmd-7" in out
    assert "cmd-2" not in out  # outside window


def test_todo_progress_bar():
    bt = _bt()
    bt.feed(StreamEvent(kind="todo", data={"todos": [
        {"content": "a", "status": "completed"},
        {"content": "b", "status": "completed"},
        {"content": "c", "status": "in_progress"},
        {"content": "d", "status": "pending"},
    ]}))
    out = bt.render_status()
    assert "50%" in out
    assert "▰" in out  # at least some progress


def test_subagent_lifecycle():
    bt = _bt()
    bt.feed(StreamEvent(kind="subagent_start", data={
        "id": "t-1", "subagent_type": "Explore", "description": "look around",
    }))
    out = bt.render_status()
    assert "Explore" in out
    assert "now" in out

    bt.feed(StreamEvent(kind="tool_result", data={
        "tool_use_id": "t-1", "content": "found 3 files", "is_error": False,
    }))
    out = bt.render_status()
    assert "done" in out


def test_mask_secrets_redacts_api_key_and_bearer():
    s = mask_secrets("api_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
    assert "[redacted]" in s
    s = mask_secrets("Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz12345")
    assert "[redacted]" in s
