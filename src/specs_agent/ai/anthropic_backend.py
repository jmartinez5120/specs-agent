"""Anthropic Claude backend — uses the official `anthropic` SDK.

Mirrors the public surface of `HttpBackend` so `AIGenerator` can dispatch
to it interchangeably:
    - `is_available()` → quick reachability/credential check
    - `chat_completion(system, user, ...)` → returns the response text

The SDK is imported lazily so installs without `[ai-anthropic]` don't
crash at module load time.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class AnthropicBackend:
    """Anthropic Claude Messages API backend.

    Example:
        backend = AnthropicBackend(api_key="sk-ant-...", model="claude-haiku-4-5")
        backend.chat_completion("You are helpful.", "Hello") → "Hi there!"
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5",
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client: Any = None  # lazy

    # ------------------------------------------------------------------ #
    # SDK lifecycle
    # ------------------------------------------------------------------ #

    @staticmethod
    def sdk_available() -> bool:
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        if not self.api_key:
            return False
        try:
            import anthropic
        except ImportError:
            logger.warning(
                "anthropic SDK not installed — pip install 'specs-agent[ai-anthropic]'"
            )
            return False
        try:
            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
            return True
        except Exception as exc:
            logger.warning("failed to construct Anthropic client: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Public API (mirrors HttpBackend)
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        """True if SDK installed AND we have an API key AND model is set.

        We don't ping the network here — that would slow every status
        check. The first real `chat_completion` will surface auth errors.
        """
        if not self.sdk_available():
            return False
        if not self.api_key or not self.model:
            return False
        return True

    def status(self) -> dict[str, Any]:
        return {
            "backend": "anthropic",
            "model": self.model,
            "sdk_installed": self.sdk_available(),
            "available": self.is_available(),
        }

    def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Send a Messages API call. Returns text content or "" on failure."""
        if not self._ensure_client():
            return ""

        try:
            response = self._client.messages.create(
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        except Exception as exc:
            logger.warning("Anthropic inference failed: %s", exc)
            return ""

        # response.content is a list of content blocks; concatenate text blocks.
        try:
            parts = []
            for block in getattr(response, "content", []) or []:
                # Block may be a TextBlock with .text, or a dict with type=="text"
                text = getattr(block, "text", None)
                if text is None and isinstance(block, dict):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                if text:
                    parts.append(text)
            return "".join(parts)
        except Exception as exc:
            logger.warning("Anthropic response parsing failed: %s", exc)
            return ""
