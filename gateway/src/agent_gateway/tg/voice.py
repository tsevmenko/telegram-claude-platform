"""Voice message handling — download .ogg, transcribe via Groq Whisper.

Telegram voice messages arrive as Opus-encoded OGG. Groq's Whisper API
accepts OGG directly (no ffmpeg conversion required for voice messages).
For audio uploaded as ``audio`` document we may need ffmpeg — that's a
phase-9-stretch goal.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import aiohttp
from aiogram import Bot

log = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
DEFAULT_LANGUAGE = "en"


class VoiceTranscriber:
    """Download Telegram audio + transcribe via Groq Whisper."""

    def __init__(self, api_key: str, language: str = DEFAULT_LANGUAGE) -> None:
        self.api_key = api_key
        self.language = language

    async def transcribe_voice(self, bot: Bot, file_id: str) -> str | None:
        """Download a Telegram audio attachment by file_id, transcribe to text.

        Works for ``voice``, ``audio``, and ``video_note`` types — all reach
        Groq Whisper which auto-handles OGG/MP3/MP4/M4A. We rely on Groq's
        media-type sniffing rather than enforcing extensions.
        """
        path = await self._download(bot, file_id)
        if path is None:
            return None
        try:
            text = await self._transcribe(path)
            return text
        finally:
            try:
                path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    async def _download(self, bot: Bot, file_id: str) -> Path | None:
        try:
            tg_file = await bot.get_file(file_id)
        except Exception:  # noqa: BLE001
            log.exception("[voice] get_file failed for %s", file_id)
            return None

        if not tg_file.file_path:
            return None

        tmp = Path(tempfile.mkstemp(suffix=".ogg")[1])
        try:
            await bot.download_file(tg_file.file_path, destination=tmp)
        except Exception:  # noqa: BLE001
            log.exception("[voice] download_file failed")
            tmp.unlink(missing_ok=True)
            return None
        return tmp

    async def _transcribe(self, audio_path: Path) -> str | None:
        if not self.api_key:
            log.warning("[voice] no GROQ_API_KEY configured — skipping")
            return None

        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field("model", GROQ_MODEL)
            data.add_field("response_format", "text")
            data.add_field("language", self.language)
            data.add_field(
                "file",
                audio_path.read_bytes(),
                filename=audio_path.name,
                content_type="audio/ogg",
            )
            try:
                async with session.post(
                    GROQ_TRANSCRIPTION_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning("[voice] groq returned %s: %s", resp.status, body[:200])
                        return None
                    return (await resp.text()).strip()
            except Exception:  # noqa: BLE001
                log.exception("[voice] transcription request failed")
                return None
