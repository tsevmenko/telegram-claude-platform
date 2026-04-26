"""Spawn N agent producer/consumer pairs in one asyncio event loop.

A single ``Dispatcher`` accepts updates from multiple ``Bot`` instances
(aiogram v3's ``start_polling(*bots)``). Each agent gets its own Router
so handlers stay isolated, and its own ``AgentConsumer`` with its own
queue, workspace, sid map, and model.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from agent_gateway.claude_cli.runner import ClaudeRunner
from agent_gateway.claude_cli.session import SessionStore
from agent_gateway.config import GatewayConfig
from agent_gateway.consumer import AgentConsumer
from agent_gateway.memory.l4_openviking import L4OpenViking
from agent_gateway.tg.producer import attach_to_dispatcher, build_router
from agent_gateway.tg.voice import VoiceTranscriber
from agent_gateway.tg.webhook_api import WebhookAPI

log = logging.getLogger(__name__)


class MultiAgentGateway:
    """Owns the dispatcher, all bots, and all consumer tasks."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.dispatcher = Dispatcher()
        self.bots: list[Bot] = []
        self.consumers: dict[str, AgentConsumer] = {}
        self.runner = ClaudeRunner()
        self.session_store = SessionStore(Path(config.state_dir))
        self.allowed_user_ids = set(config.allowed_user_ids)
        self.allowed_group_ids = set(config.allowed_group_ids)

        groq_key = config.resolved_groq_key()
        self.transcriber: VoiceTranscriber | None = (
            VoiceTranscriber(groq_key, language=config.voice_language) if groq_key else None
        )

        self.l4: L4OpenViking | None = None
        if config.l4.enabled and config.l4.api_key_file:
            self.l4 = L4OpenViking(
                url=config.l4.url,
                api_key_path=config.l4.api_key_file,
                account=config.l4.account,
            )

    def setup(self) -> None:
        for name, agent_cfg in self.config.enabled_agents().items():
            token = agent_cfg.resolved_token()
            if not token:
                log.warning("[%s] no bot token configured — skipping", name)
                continue

            bot = Bot(token=token)
            consumer = AgentConsumer(
                agent_name=name,
                agent_cfg=agent_cfg,
                bot=bot,
                session_store=self.session_store,
                runner=self.runner,
                l4=self.l4,
            )
            router = build_router(
                consumer,
                self.allowed_user_ids,
                self.transcriber,
                self.allowed_group_ids,
            )
            attach_to_dispatcher(self.dispatcher, bot, router)

            self.bots.append(bot)
            self.consumers[name] = consumer

        if not self.bots:
            raise RuntimeError("No enabled agents have a bot token. Nothing to run.")

    async def run(self) -> None:
        for consumer in self.consumers.values():
            consumer.start()

        webhook: WebhookAPI | None = None
        if self.config.webhook.enabled and self.config.webhook.token_file:
            webhook = WebhookAPI(
                consumers=self.consumers,
                token_path=Path(self.config.webhook.token_file),
                listen_host=self.config.webhook.listen_host,
                listen_port=self.config.webhook.listen_port,
            )
            await webhook.start()

        log.info("Starting polling for %d bot(s): %s",
                 len(self.bots),
                 ", ".join(self.consumers.keys()))
        try:
            await self.dispatcher.start_polling(*self.bots, polling_timeout=10)
        finally:
            for consumer in self.consumers.values():
                await consumer.stop()
            for bot in self.bots:
                await bot.session.close()
            if webhook:
                await webhook.stop()
            if self.l4:
                self.l4.shutdown()
