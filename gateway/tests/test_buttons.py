"""Inline button extraction tests."""

from __future__ import annotations

from agent_gateway.tg.buttons import build_keyboard, extract_buttons


def test_no_marker_passes_through():
    text, rows = extract_buttons("Just a normal reply.")
    assert text == "Just a normal reply."
    assert rows == []


def test_simple_marker():
    text, rows = extract_buttons(
        "Should I commit?\n[BUTTONS: [Yes|commit:yes] [No|commit:no]]"
    )
    assert text == "Should I commit?"
    assert len(rows) == 1
    assert rows[0][0].label == "Yes"
    assert rows[0][0].callback_data == "commit:yes"
    assert rows[0][1].label == "No"


def test_multiple_rows():
    text, rows = extract_buttons(
        "[BUTTONS: [A|x:1] [B|x:2]] some prose [BUTTONS: [C|y:3]]"
    )
    assert "x:1" not in text
    assert "y:3" not in text
    assert len(rows) == 2
    assert [b.callback_data for b in rows[0]] == ["x:1", "x:2"]
    assert [b.callback_data for b in rows[1]] == ["y:3"]


def test_callback_data_truncated_to_64_bytes():
    long_payload = "z" * 100
    text, rows = extract_buttons(f"[BUTTONS: [Click|{long_payload}]]")
    assert len(rows[0][0].callback_data.encode("utf-8")) <= 64


def test_build_keyboard_none_when_empty():
    assert build_keyboard([]) is None


def test_build_keyboard_returns_markup():
    text, rows = extract_buttons("[BUTTONS: [A|do:a] [B|do:b]]")
    kb = build_keyboard(rows)
    assert kb is not None
    assert len(kb.inline_keyboard) == 1
    assert kb.inline_keyboard[0][0].text == "A"
