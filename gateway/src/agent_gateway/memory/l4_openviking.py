"""L4 semantic memory adapter — fire-and-forget push to OpenViking.

After every completed turn the consumer hands off ``(user_text, agent_response)``
to this module. The push runs in a bounded executor so a burst of messages
cannot spawn unbounded threads.

Anti-pollution guards: messages tagged as forwarded / external media get an
explicit instruction to OV's extractor LLM that the content is NOT the
operator's own preference. Without this guard the operator's profile becomes
polluted with views from third-party content.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

log = logging.getLogger(__name__)

POOL_MAX_WORKERS = 2
TIMEOUT_SHORT = 5
TIMEOUT_LONG = 60
SNIPPET_MAX = 3000


class L4OpenViking:
    """Pushes conversation turns into OpenViking for semantic recall."""

    def __init__(
        self,
        url: str,
        api_key_path: str | Path,
        account: str = "default",
    ) -> None:
        self.base_url = url.rstrip("/")
        self.account = account
        self._api_key: str | None = None
        self._api_key_path = Path(api_key_path) if api_key_path else None
        self._executor = ThreadPoolExecutor(max_workers=POOL_MAX_WORKERS, thread_name_prefix="l4")

    def push(
        self,
        agent_name: str,
        chat_id: int,
        user_text: str,
        agent_response: str,
        source_tag: str = "text",
    ) -> None:
        """Schedule an async push. Returns immediately — never blocks."""
        if not self._is_ready():
            return
        self._executor.submit(self._push_blocking, agent_name, chat_id,
                              user_text, agent_response, source_tag)

    def shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=True, cancel_futures=False)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------

    def _is_ready(self) -> bool:
        return bool(self._resolve_key())

    def _resolve_key(self) -> str:
        if self._api_key is not None:
            return self._api_key
        if self._api_key_path and self._api_key_path.exists():
            self._api_key = self._api_key_path.read_text().strip()
            return self._api_key
        self._api_key = ""
        return self._api_key

    def _headers(self, agent_name: str) -> dict[str, str]:
        return {
            "X-API-Key": self._resolve_key(),
            "X-OpenViking-Account": self.account,
            "X-OpenViking-User": agent_name,
            "Content-Type": "application/json",
        }

    def _push_blocking(
        self,
        agent_name: str,
        chat_id: int,
        user_text: str,
        agent_response: str,
        source_tag: str,
    ) -> None:
        sid = None
        try:
            r = requests.post(
                f"{self.base_url}/api/v1/sessions",
                headers=self._headers(agent_name),
                json={},
                timeout=TIMEOUT_SHORT,
            )
            if r.status_code != 200:
                log.warning("[l4] %s/%s session create failed: %s", agent_name, chat_id, r.status_code)
                return
            sid = r.json().get("result", {}).get("session_id")
            if not sid:
                log.warning("[l4] %s/%s no session id in response", agent_name, chat_id)
                return

            ts = time.strftime("%Y-%m-%d %H:%M")
            guard = self._extraction_guard(source_tag)
            meta_prefix = f"[chat:{chat_id} agent:{agent_name} at {ts}]{guard}\n"

            r_user = requests.post(
                f"{self.base_url}/api/v1/sessions/{sid}/messages",
                headers=self._headers(agent_name),
                json={"role": "user", "content": meta_prefix + user_text[:SNIPPET_MAX]},
                timeout=TIMEOUT_SHORT,
            )
            if r_user.status_code != 200:
                log.warning("[l4] %s/%s user msg rc=%s", agent_name, chat_id, r_user.status_code)
                return

            if agent_response:
                r_asst = requests.post(
                    f"{self.base_url}/api/v1/sessions/{sid}/messages",
                    headers=self._headers(agent_name),
                    json={"role": "assistant", "content": agent_response[:SNIPPET_MAX]},
                    timeout=TIMEOUT_SHORT,
                )
                if r_asst.status_code != 200:
                    log.warning("[l4] %s/%s asst msg rc=%s", agent_name, chat_id, r_asst.status_code)
                    return

            ext = requests.post(
                f"{self.base_url}/api/v1/sessions/{sid}/extract",
                headers=self._headers(agent_name),
                json={},
                timeout=TIMEOUT_LONG,
            )
            extracted = ext.json().get("result", []) if ext.status_code == 200 else []
            log.info("[l4] %s/%s extracted %d memories", agent_name, chat_id, len(extracted))
        except Exception as exc:  # noqa: BLE001
            log.warning("[l4] %s/%s push failed: %s", agent_name, chat_id, exc)
        finally:
            if sid:
                try:
                    requests.delete(
                        f"{self.base_url}/api/v1/sessions/{sid}",
                        headers=self._headers(agent_name),
                        timeout=TIMEOUT_SHORT,
                    )
                except Exception:  # noqa: BLE001
                    pass

    @staticmethod
    def _extraction_guard(source_tag: str) -> str:
        if source_tag.startswith("forwarded"):
            return (
                "\n[extraction hint: this content was FORWARDED to the operator from"
                " someone else. Do NOT extract it as the operator's preferences."
                " Only extract events/cases/entities about the third-party source.]\n"
            )
        if source_tag.startswith("external_media"):
            return (
                "\n[extraction hint: this is external media the operator is sharing,"
                " not their own words. Do NOT extract as preferences.]\n"
            )
        return ""
