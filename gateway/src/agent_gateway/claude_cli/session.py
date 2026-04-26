"""Session ID management — one UUID per (agent, chat_id), persisted to disk."""

from __future__ import annotations

import uuid
from pathlib import Path


class SessionStore:
    """Plain-text session ID storage at ``state/sid-<agent>-<chat_id>.txt``."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, agent: str, chat_id: int) -> Path:
        return self.state_dir / f"sid-{agent}-{chat_id}.txt"

    def get(self, agent: str, chat_id: int) -> str | None:
        path = self._path(agent, chat_id)
        if not path.exists():
            return None
        sid = path.read_text().strip()
        return sid or None

    def get_or_create(self, agent: str, chat_id: int) -> tuple[str, bool]:
        """Return (sid, created). created=True means a fresh UUID was generated."""
        existing = self.get(agent, chat_id)
        if existing:
            return existing, False
        sid = str(uuid.uuid4())
        self._path(agent, chat_id).write_text(sid)
        return sid, True

    def reset(self, agent: str, chat_id: int) -> None:
        path = self._path(agent, chat_id)
        if path.exists():
            path.unlink()
