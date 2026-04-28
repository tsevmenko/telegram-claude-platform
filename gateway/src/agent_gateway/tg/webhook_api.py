"""Webhook API — POST /hooks/agent injects a message into an agent's queue.

Use cases:
- Cron jobs and reminders deliver scheduled messages to the operator.
- Monitoring sends alerts that surface as agent messages.
- External services pipe events through the agent.

Auth: ``Authorization: Bearer <token>``. Token is generated at install time
and rotated by Vesna's ``regenerate_webhook_token`` admin command.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

from agent_gateway.consumer import AgentConsumer, IncomingMessage

log = logging.getLogger(__name__)


class WebhookAPI:
    """Tiny HTTP server (aiohttp) accepting external message injections."""

    def __init__(
        self,
        consumers: dict[str, AgentConsumer],
        token_path: Path,
        listen_host: str,
        listen_port: int,
    ) -> None:
        self.consumers = consumers
        self.token_path = Path(token_path)
        self.host = listen_host
        self.port = listen_port
        self._app = web.Application()
        self._app.router.add_post("/hooks/agent", self._handle_inject)
        self._app.router.add_get("/health", self._handle_health)
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        log.info("webhook api listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    # ------------------------------------------------------------------

    def _expected_token(self) -> str:
        if not self.token_path.exists():
            return ""
        return self.token_path.read_text().strip()

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "agents": list(self.consumers.keys())})

    async def _handle_inject(self, request: web.Request) -> web.Response:
        token = self._expected_token()
        if not token:
            return web.json_response({"error": "webhook token not configured"}, status=503)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[len("Bearer "):] != token:
            return web.json_response({"error": "unauthorised"}, status=401)

        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "invalid json"}, status=400)

        # Accept both naming conventions:
        # - Pythonic (our default):  {"agent", "chat_id", "text", "thread_id"}
        # - Workshop / camelCase:    {"agentId", "chatId", "message", "threadId"}
        # Operators copy-pasting curl examples from the edgelab.su workshop hit
        # the camelCase form; we silently normalise so neither breaks.
        agent = payload.get("agent") or payload.get("agentId")
        chat_id = payload.get("chat_id") or payload.get("chatId")
        text = payload.get("text") or payload.get("message") or ""
        thread_id = payload.get("thread_id") or payload.get("threadId")

        if not agent or not chat_id or not text:
            return web.json_response(
                {
                    "error": (
                        "missing fields: need (agent or agentId), "
                        "(chat_id or chatId), (text or message)"
                    )
                },
                status=400,
            )

        consumer = self.consumers.get(agent)
        if not consumer:
            return web.json_response({"error": f"unknown agent: {agent}"}, status=404)

        msg = IncomingMessage(
            chat_id=int(chat_id),
            user_id=0,
            message_id=0,
            thread_id=thread_id,
            text=text,
            is_oob=False,
            source="webhook",
        )
        await consumer.queue.put(msg)
        return web.json_response({"status": "queued", "agent": agent})
