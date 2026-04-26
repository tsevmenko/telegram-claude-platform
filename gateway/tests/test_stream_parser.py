"""Stream-json parser tests."""

from __future__ import annotations

import json

from agent_gateway.claude_cli.stream_parser import _classify, parse_line


def _ev(obj):
    return _classify(obj)


def test_init_event():
    ev = _ev({"type": "system", "subtype": "init", "model": "opus", "session_id": "s1"})
    assert ev.kind == "init"
    assert ev.data["model"] == "opus"
    assert ev.data["session_id"] == "s1"


def test_assistant_text_block():
    ev = _ev({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "hello"}]},
    })
    assert ev.kind == "text"
    assert ev.data["text"] == "hello"


def test_assistant_thinking_block():
    ev = _ev({
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": "reasoning..."}]},
    })
    assert ev.kind == "thinking"
    assert ev.data["text"] == "reasoning..."


def test_assistant_tool_use_bash():
    ev = _ev({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": "t1",
            "name": "Bash",
            "input": {"command": "ls -la"},
        }]},
    })
    assert ev.kind == "tool_use"
    assert ev.data["name"] == "Bash"
    assert ev.data["input"]["command"] == "ls -la"


def test_assistant_tool_use_todo_promotes_to_todo_event():
    ev = _ev({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": "t1",
            "name": "TodoWrite",
            "input": {"todos": [
                {"content": "step 1", "status": "completed"},
                {"content": "step 2", "status": "in_progress"},
            ]},
        }]},
    })
    assert ev.kind == "todo"
    assert len(ev.data["todos"]) == 2


def test_assistant_task_promotes_to_subagent_start():
    ev = _ev({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": "t1",
            "name": "Task",
            "input": {"description": "research", "subagent_type": "Explore"},
        }]},
    })
    assert ev.kind == "subagent_start"
    assert ev.data["subagent_type"] == "Explore"


def test_user_tool_result():
    ev = _ev({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": "t1",
            "content": "stdout output",
            "is_error": False,
        }]},
    })
    assert ev.kind == "tool_result"
    assert ev.data["tool_use_id"] == "t1"
    assert ev.data["content"] == "stdout output"


def test_result_final():
    ev = _ev({
        "type": "result",
        "subtype": "success",
        "result": "the final answer",
        "is_error": False,
        "duration_ms": 1234,
    })
    assert ev.kind == "final"
    assert ev.data["text"] == "the final answer"
    assert ev.data["is_error"] is False


def test_parse_line_handles_invalid_json():
    ev = parse_line("not json")
    assert ev is not None
    assert ev.kind == "unknown"


def test_parse_line_skips_blank():
    assert parse_line("   ") is None
    assert parse_line("") is None


def test_tool_result_list_content_is_concatenated():
    ev = _ev({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": "t1",
            "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ],
        }]},
    })
    assert ev.kind == "tool_result"
    assert "line1" in ev.data["content"]
    assert "line2" in ev.data["content"]
