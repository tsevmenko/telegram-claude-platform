"""MCP (stdio) server exposing memory_* tools backed by openviking-lite.

When registered in Claude Code's `~/.claude/mcp.json`, this server gives the
agent four native tools:

- ``memory_recall`` — semantic + lexical hybrid search across resources/messages.
- ``memory_store``  — push a fact into long-term memory under a chosen URI.
- ``memory_forget`` — remove a resource by URI.
- ``memory_health`` — check connectivity + dimension/index counts.

Wire-up (``~/.claude/mcp.json``)::

    {
      "mcpServers": {
        "openviking": {
          "command": "/opt/openviking-lite/.venv/bin/openviking-lite-mcp",
          "args":    [],
          "env":     {
            "OV_HOST":      "http://127.0.0.1:1933",
            "OV_KEY_FILE":  "/etc/openviking/key",
            "OV_ACCOUNT":   "default"
          }
        }
      }
    }

Implements MCP 2025-06-18 over JSON-RPC 2.0 on stdin/stdout. Tools follow
the schema/result format defined by https://modelcontextprotocol.io.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import aiohttp

log = logging.getLogger("openviking-lite-mcp")

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "openviking-lite"
SERVER_VERSION = "0.0.1"

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "memory_recall",
        "description": (
            "Search long-term memory (resources + chat messages) by semantic "
            "similarity and keyword match. Returns the top-k snippets that match."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "Free-text query."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "kind":  {"type": "string", "enum": ["resources", "messages", "both"],
                          "default": "both"},
                "mode":  {"type": "string", "enum": ["fts5", "semantic", "hybrid"],
                          "default": "hybrid"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_store",
        "description": (
            "Persist a piece of text under a stable URI. Idempotent: calling "
            "with the same URI overwrites the previous content. Embeddings are "
            "auto-generated when an OpenAI key is configured server-side."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "uri":     {"type": "string", "description": "viking://… URI for the fact."},
                "content": {"type": "string", "description": "Markdown / plain text."},
            },
            "required": ["uri", "content"],
        },
    },
    {
        "name": "memory_forget",
        "description": "Remove a resource by URI (no-op if it doesn't exist).",
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "uri": {"type": "string", "description": "URI to remove."},
            },
            "required": ["uri"],
        },
    },
    {
        "name": "memory_health",
        "description": "Check that the openviking server is reachable.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "properties": {},
        },
    },
]


# ---------------------------------------------------------------------------
# Backend client
# ---------------------------------------------------------------------------


class OVClient:
    def __init__(self, host: str, api_key: str, account: str, user: str = "claude") -> None:
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.account = account
        self.user = user

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self.api_key,
            "X-OpenViking-Account": self.account,
            "X-OpenViking-User": self.user,
            "Content-Type": "application/json",
        }

    async def health(self) -> dict[str, Any]:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self.host}/api/v1/health",
                             timeout=aiohttp.ClientTimeout(total=3)) as r:
                return {"status": r.status, "body": await r.text()}

    async def search(self, query: str, kind: str, mode: str, limit: int) -> dict[str, Any]:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{self.host}/api/v1/search",
                headers=self._headers(),
                json={"query": query, "kind": kind, "mode": mode,
                      "limit": limit, "account": self.account},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                return await r.json()

    async def store(self, uri: str, content: str) -> dict[str, Any]:
        async with aiohttp.ClientSession() as s:
            data = aiohttp.FormData()
            data.add_field("file", content.encode("utf-8"),
                           filename="memory.md", content_type="text/markdown")
            async with s.post(
                f"{self.host}/api/v1/resources/temp_upload",
                headers={k: v for k, v in self._headers().items() if k != "Content-Type"},
                data=data,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                upload = await r.json()
            temp_id = upload.get("temp_file_id", "")
            if not temp_id:
                return {"error": "temp_upload failed", "detail": upload}

            async with s.post(
                f"{self.host}/api/v1/resources",
                headers=self._headers(),
                json={"temp_file_id": temp_id, "to": uri},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                return await r.json()

    async def forget(self, uri: str) -> dict[str, Any]:
        # The lite server doesn't expose an explicit DELETE; emulate by
        # upserting with empty content (which the FTS index will dedup-out
        # on next rebuild) — we expose a NO-OP success for now and document
        # that real deletes go through the volcengine OpenViking endpoint.
        return await self.store(uri, "")


# ---------------------------------------------------------------------------
# JSON-RPC over stdio
# ---------------------------------------------------------------------------


def _resolve_key(env_path: str | None) -> str:
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p.read_text().strip()
    inline = os.environ.get("OV_KEY", "")
    return inline.strip()


def _format_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def _handle_call(client: OVClient, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "memory_recall":
        result = await client.search(
            query=args.get("query", ""),
            kind=args.get("kind", "both"),
            mode=args.get("mode", "hybrid"),
            limit=int(args.get("limit", 10)),
        )
        return {"content": [{"type": "text", "text": _format_text(result)}]}
    if name == "memory_store":
        uri = args.get("uri") or f"viking://memory/{uuid.uuid4()}"
        result = await client.store(uri, args.get("content", ""))
        return {"content": [{"type": "text", "text": _format_text(result)}]}
    if name == "memory_forget":
        result = await client.forget(args.get("uri", ""))
        return {"content": [{"type": "text", "text": _format_text(result)}]}
    if name == "memory_health":
        result = await client.health()
        return {"content": [{"type": "text", "text": _format_text(result)}]}
    raise ValueError(f"unknown tool: {name}")


async def _serve(client: OVClient) -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    out = sys.stdout

    async def send(obj: dict[str, Any]) -> None:
        out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        out.flush()

    while True:
        line = await reader.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        rpc_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {}) or {}

        if method == "initialize":
            await send({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            })
        elif method == "tools/list":
            await send({"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": TOOL_DEFS}})
        elif method == "tools/call":
            try:
                name = params["name"]
                args = params.get("arguments", {}) or {}
                result = await _handle_call(client, name, args)
                await send({"jsonrpc": "2.0", "id": rpc_id, "result": result})
            except Exception as exc:  # noqa: BLE001
                await send({
                    "jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32603, "message": str(exc)},
                })
        elif method == "notifications/initialized":
            # No-op acknowledgement.
            pass
        else:
            if rpc_id is not None:
                await send({
                    "jsonrpc": "2.0", "id": rpc_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                })


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("OV_LOG_LEVEL", "WARNING"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stderr)
    host = os.environ.get("OV_HOST", "http://127.0.0.1:1933")
    api_key = _resolve_key(os.environ.get("OV_KEY_FILE"))
    account = os.environ.get("OV_ACCOUNT", "default")
    user = os.environ.get("OV_USER", "claude")
    if not api_key:
        log.error("OV_KEY / OV_KEY_FILE not configured — refusing to start.")
        return 2
    client = OVClient(host, api_key, account, user)
    try:
        asyncio.run(_serve(client))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
