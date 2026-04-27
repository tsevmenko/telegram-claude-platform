"""OpenAI embeddings + cosine similarity for semantic search.

When the server is configured with an OpenAI API key, content added to
``messages`` and ``resources`` gets vectorised via
``text-embedding-3-small`` (1536-dim, $0.02 / 1M input tokens) and stored
as ``BLOB`` next to the row. Search can then run in three modes:

- ``fts5``     — keyword/lexical (free, immediate, BM25 ranking).
- ``semantic`` — cosine similarity against query embedding.
- ``hybrid``   — both, normalised and combined 0.5/0.5.

Vectors are serialised as little-endian float32 (1536 × 4 = 6144 bytes per
embedding). Brute-force scan is fine for ≤ 100K rows; an upgrade path to
``sqlite-vec`` is documented in the README.
"""

from __future__ import annotations

import logging
import math
import struct

import aiohttp

log = logging.getLogger(__name__)

OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIM = 1536
MAX_INPUT_CHARS = 8000  # OpenAI accepts up to ~8K tokens; chars proxy.


class EmbeddingProvider:
    """Tiny async client for OpenAI's embedding endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        dim: int = DEFAULT_DIM,
        api_base: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.api_base = api_base.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def embed(self, text: str) -> list[float] | None:
        if not self.configured:
            return None
        payload = {"model": self.model, "input": (text or "")[:MAX_INPUT_CHARS]}
        url = f"{self.api_base}/embeddings"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        log.warning("[embed] %s returned %s: %s",
                                    url, resp.status, body[:300])
                        return None
                    data = await resp.json()
                    return list(data["data"][0]["embedding"])
        except Exception as exc:  # noqa: BLE001
            log.warning("[embed] request failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Serialisation + math
# ---------------------------------------------------------------------------


def encode(vec: list[float]) -> bytes:
    """Serialise a vector as little-endian float32. ~4 bytes / dim."""
    return struct.pack(f"<{len(vec)}f", *vec)


def decode(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def topk_brute(query: list[float], candidates: list[tuple[str, bytes]],
               k: int = 20) -> list[tuple[str, float]]:
    """Return the top-k (ref_id, score) pairs by cosine similarity."""
    scored = [(ref_id, cosine(query, decode(blob))) for ref_id, blob in candidates]
    scored.sort(key=lambda r: -r[1])
    return scored[:k]
