"""Coverage for all Telegram message types — text, voice, audio, video_note,
photo, document, sticker, video, animation, location, contact, poll, dice.

Background: live-VPS regression — operator sent a screenshot + caption to
Leto, agent silently dropped the message because we only had F.text and
F.voice handlers wired. This locks in the broader filter set.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_gateway.tg import producer

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Static analysis: filter coverage. If someone deletes one of these handlers,
# the test fails BEFORE we discover it on a live VPS.
# ---------------------------------------------------------------------------


def test_producer_source_lists_all_supported_filters() -> None:
    src = (
        REPO_ROOT / "gateway" / "src" / "agent_gateway" / "tg" / "producer.py"
    ).read_text(encoding="utf-8")

    must_handle = [
        "F.text",
        "F.voice",       # also matched by F.voice | F.audio | F.video_note
        "F.audio",
        "F.video_note",
        "F.photo",
        "F.document",
        "F.sticker",
        "F.video",
        "F.animation",
        "F.location",
        "F.contact",
        "F.poll",
        "F.dice",
    ]
    missing = [f for f in must_handle if f not in src]
    assert not missing, f"producer.py is missing handlers for: {missing}"


def test_helpers_for_attachment_download_exist() -> None:
    """The big-three helpers must be exported (importable from outside the
    file) so refactor doesn't accidentally break them by renaming."""
    assert hasattr(producer, "_save_telegram_attachment")
    assert hasattr(producer, "_build_photo_prompt")
    assert hasattr(producer, "_build_document_prompt")
    assert hasattr(producer, "_echo_voice_transcript")


# ---------------------------------------------------------------------------
# _build_photo_prompt — composes the prompt Claude sees on a photo turn.
# ---------------------------------------------------------------------------


def test_photo_prompt_uses_read_tool_and_absolute_path(tmp_path: Path) -> None:
    img = tmp_path / "incoming" / "12-abc.jpg"
    img.parent.mkdir()
    img.touch()
    msg = SimpleNamespace(
        text=None, caption="что тут на скриншоте?",
        forward_origin=None, reply_to_message=None,
    )
    out = producer._build_photo_prompt(msg, img.resolve())
    assert "что тут на скриншоте" in out
    assert "Read tool" in out
    assert str(img.resolve()) in out


def test_photo_prompt_handles_no_caption(tmp_path: Path) -> None:
    img = tmp_path / "p.jpg"
    img.touch()
    msg = SimpleNamespace(
        text=None, caption=None, forward_origin=None, reply_to_message=None
    )
    out = producer._build_photo_prompt(msg, img.resolve())
    assert "no caption" in out.lower()
    assert str(img.resolve()) in out


def test_photo_prompt_preserves_reply_context(tmp_path: Path) -> None:
    img = tmp_path / "p.jpg"
    img.touch()
    reply = SimpleNamespace(
        from_user=SimpleNamespace(id=111, is_bot=False),
        text="earlier discussion text",
        caption=None,
    )
    msg = SimpleNamespace(
        text=None, caption="вот скрин по той теме",
        forward_origin=None, reply_to_message=reply,
    )
    out = producer._build_photo_prompt(msg, img.resolve(), self_bot_id=999)
    assert "untrusted metadata" in out
    assert "earlier discussion" in out
    assert "вот скрин по той теме" in out


# ---------------------------------------------------------------------------
# _build_document_prompt — same shape, includes file name.
# ---------------------------------------------------------------------------


def test_document_prompt_includes_filename(tmp_path: Path) -> None:
    doc = tmp_path / "report.pdf"
    doc.touch()
    msg = SimpleNamespace(
        text=None, caption="прочти и дай выжимку",
        forward_origin=None, reply_to_message=None,
        document=SimpleNamespace(file_name="report.pdf"),
    )
    out = producer._build_document_prompt(msg, doc.resolve())
    assert "report.pdf" in out
    assert "прочти и дай выжимку" in out
    assert str(doc.resolve()) in out


# ---------------------------------------------------------------------------
# _save_telegram_attachment — writes file to <workspace>/incoming/
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_photo_writes_to_workspace_incoming(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    bot = MagicMock()
    download_mock = AsyncMock()

    async def fake_download(file_id: str, destination: Path) -> None:
        Path(destination).write_bytes(b"fake-jpeg-bytes")

    bot.download = fake_download
    photo = SimpleNamespace(file_id="ABC", file_unique_id="UNIQ123")
    msg = SimpleNamespace(message_id=42, photo=[photo], document=None)

    saved = await producer._save_telegram_attachment(
        bot=bot, message=msg, workspace=workspace, kind="photo"
    )
    assert saved is not None
    assert saved.exists()
    assert saved.read_bytes() == b"fake-jpeg-bytes"
    # Path shape: <workspace>/incoming/<msg_id>-<unique>.jpg
    assert saved.parent.name == "incoming"
    assert "42" in saved.name
    assert "UNIQ123" in saved.name
    assert saved.suffix == ".jpg"


@pytest.mark.asyncio
async def test_save_attachment_idempotent(tmp_path: Path) -> None:
    """Same Telegram file_unique_id arriving twice → reuse cached file,
    don't re-download."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    download_calls = 0
    bot = MagicMock()

    async def fake_download(file_id: str, destination: Path) -> None:
        nonlocal download_calls
        download_calls += 1
        Path(destination).write_bytes(b"first-call")

    bot.download = fake_download
    photo = SimpleNamespace(file_id="ABC", file_unique_id="UNIQ")
    msg = SimpleNamespace(message_id=7, photo=[photo], document=None)

    p1 = await producer._save_telegram_attachment(
        bot=bot, message=msg, workspace=workspace, kind="photo"
    )
    p2 = await producer._save_telegram_attachment(
        bot=bot, message=msg, workspace=workspace, kind="photo"
    )
    assert p1 == p2
    assert download_calls == 1, "second call should reuse cached file"


@pytest.mark.asyncio
async def test_save_attachment_picks_largest_photo_size(tmp_path: Path) -> None:
    """Telegram sends multiple PhotoSize objects sorted small→large.
    We must pick the LAST (largest) for OCR / detail."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    captured_file_id: list[str] = []
    bot = MagicMock()

    async def fake_download(file_id: str, destination: Path) -> None:
        captured_file_id.append(file_id)
        Path(destination).touch()

    bot.download = fake_download
    msg = SimpleNamespace(
        message_id=1,
        photo=[
            SimpleNamespace(file_id="thumb", file_unique_id="t"),
            SimpleNamespace(file_id="medium", file_unique_id="m"),
            SimpleNamespace(file_id="largest", file_unique_id="l"),
        ],
        document=None,
    )
    await producer._save_telegram_attachment(
        bot=bot, message=msg, workspace=workspace, kind="photo"
    )
    assert captured_file_id == ["largest"]


# ---------------------------------------------------------------------------
# Document MIME allow-list: produced by ACCEPTED_DOC_MIME — sanity check it
# rejects exes / archives but accepts pdf / images / text.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mime,allowed",
    [
        ("application/pdf",            True),
        ("text/plain",                 True),
        ("text/markdown",              True),
        ("text/csv",                   True),
        ("application/json",           True),
        ("image/png",                  True),
        ("image/jpeg",                 True),
        ("image/webp",                 True),
        ("application/x-msdownload",   False),  # Windows .exe
        ("application/zip",            False),
        ("application/octet-stream",   False),  # generic binary
        ("video/mp4",                  False),  # too big, too useless
        ("application/x-shellscript",  False),  # security: no remote shell
    ],
)
def test_document_mime_allowlist(mime: str, allowed: bool) -> None:
    if allowed:
        assert mime in producer.ACCEPTED_DOC_MIME, f"{mime} should be accepted"
    else:
        assert mime not in producer.ACCEPTED_DOC_MIME, f"{mime} should be rejected"


# ---------------------------------------------------------------------------
# Telegram bot file size cap (20 MB) — constant matches Telegram docs.
# ---------------------------------------------------------------------------


def test_download_limit_matches_telegram_bot_cap() -> None:
    # Telegram Bot API: bots can request files up to 20 MiB via getFile.
    assert producer.TELEGRAM_BOT_DOWNLOAD_LIMIT == 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Voice transcriber — works for voice + audio + video_note paths
# ---------------------------------------------------------------------------


def test_voice_transcriber_docstring_mentions_audio_and_video_note() -> None:
    """Future-me check: the entry point is now generic across audio types."""
    src = (
        REPO_ROOT / "gateway" / "src" / "agent_gateway" / "tg" / "voice.py"
    ).read_text(encoding="utf-8")
    docstring = inspect.getsource(
        __import__("agent_gateway.tg.voice", fromlist=["VoiceTranscriber"])
        .VoiceTranscriber
        .transcribe_voice
    )
    assert "video_note" in docstring or "video_note" in src
    assert "audio" in docstring or "audio" in src
