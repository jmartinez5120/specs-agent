"""OpenAI backend — uses the official `openai` SDK.

For OpenAI proper or any provider that exposes the same SDK shape via
`base_url` (e.g. Azure OpenAI). Generic OpenAI-compatible endpoints
(Ollama, vLLM, Docker Model Runner) keep using the lighter
`HttpBackend` — that one has no dependency on the SDK.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OpenAIBackend:
    """OpenAI Chat Completions backend.

    Example:
        backend = OpenAIBackend(api_key="sk-...", model="gpt-4o-mini")
        backend.chat_completion("You are helpful.", "Hi!") → "Hello!"
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "",
        timeout: int = 120,
    ) -> None:
        self.api_key = api_key
        self.model = model
        # Empty string means "use SDK default" (api.openai.com/v1).
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.timeout = timeout
        self._client: Any = None  # lazy

    @staticmethod
    def sdk_available() -> bool:
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        if not self.api_key:
            return False
        try:
            import openai
        except ImportError:
            logger.warning(
                "openai SDK not installed — pip install 'specs-agent[ai-openai]'"
            )
            return False
        try:
            kwargs: dict[str, Any] = {"api_key": self.api_key, "timeout": self.timeout}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.OpenAI(**kwargs)
            return True
        except Exception as exc:
            logger.warning("failed to construct OpenAI client: %s", exc)
            return False

    def is_available(self) -> bool:
        if not self.sdk_available():
            return False
        if not self.api_key or not self.model:
            return False
        return True

    def status(self) -> dict[str, Any]:
        return {
            "backend": "openai",
            "model": self.model,
            "base_url": self.base_url or "https://api.openai.com/v1",
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
        if not self._ensure_client():
            return ""

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        except Exception as exc:
            logger.warning("OpenAI inference failed: %s", exc)
            return ""

        try:
            choices = getattr(response, "choices", None) or []
            if not choices:
                return ""
            msg = getattr(choices[0], "message", None)
            content = getattr(msg, "content", None) if msg is not None else None
            if content is None and isinstance(msg, dict):
                content = msg.get("content")
            return content or ""
        except Exception as exc:
            logger.warning("OpenAI response parsing failed: %s", exc)
            return ""
