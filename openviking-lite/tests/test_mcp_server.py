"""MCP server protocol tests — initialise, tools/list, tools/call routing."""

from __future__ import annotations

import asyncio
import json

import pytest

from openviking_lite.mcp_server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    TOOL_DEFS,
    OVClient,
    _handle_call,
)


def test_tool_defs_have_required_fields():
    names = {t["name"] for t in TOOL_DEFS}
    assert names == {"memory_recall", "memory_store", "memory_forget", "memory_health"}
    for t in TOOL_DEFS:
        assert "description" in t
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


def test_protocol_version_is_pinned():
    # Refuse to drift silently — change requires a deliberate edit.
    assert PROTOCOL_VERSION == "2025-06-18"
    assert SERVER_NAME == "openviking-lite"


class _FakeClient(OVClient):
    """Records calls instead of hitting the network."""

    def __init__(self) -> None:
        super().__init__("http://fake", "k", "acc", "u")
        self.calls: list[tuple[str, dict]] = []

    async def search(self, query, kind, mode, limit):
        self.calls.append(("search", {"query": query, "kind": kind, "mode": mode, "limit": limit}))
        return {"resources": [{"ref_id": "v://1", "score": 0.9, "content": "stub"}]}

    async def store(self, uri, content):
        self.calls.append(("store", {"uri": uri, "content": content}))
        return {"status": "ok", "uri": uri}

    async def forget(self, uri):
        self.calls.append(("forget", {"uri": uri}))
        return {"status": "ok"}

    async def health(self):
        self.calls.append(("health", {}))
        return {"status": 200, "body": "ok"}


def test_handle_call_recall_dispatches_search():
    client = _FakeClient()
    result = asyncio.run(_handle_call(client, "memory_recall",
                                      {"query": "what about ferns", "limit": 5}))
    assert client.calls[0][0] == "search"
    assert client.calls[0][1]["query"] == "what about ferns"
    assert client.calls[0][1]["limit"] == 5
    assert result["content"][0]["type"] == "text"


def test_handle_call_store_dispatches_store():
    client = _FakeClient()
    asyncio.run(_handle_call(client, "memory_store",
                             {"uri": "viking://x/1", "content": "hello"}))
    assert client.calls[0][0] == "store"
    assert client.calls[0][1]["uri"] == "viking://x/1"
    assert client.calls[0][1]["content"] == "hello"


def test_handle_call_store_generates_uri_when_missing():
    client = _FakeClient()
    asyncio.run(_handle_call(client, "memory_store", {"content": "no uri"}))
    assert client.calls[0][0] == "store"
    assert client.calls[0][1]["uri"].startswith("viking://memory/")


def test_handle_call_forget_dispatches_forget():
    client = _FakeClient()
    asyncio.run(_handle_call(client, "memory_forget", {"uri": "viking://x/1"}))
    assert client.calls[0][0] == "forget"


def test_handle_call_health_dispatches_health():
    client = _FakeClient()
    asyncio.run(_handle_call(client, "memory_health", {}))
    assert client.calls[0][0] == "health"


def test_handle_call_unknown_tool_raises():
    client = _FakeClient()
    with pytest.raises(ValueError):
        asyncio.run(_handle_call(client, "memory_explode", {}))
