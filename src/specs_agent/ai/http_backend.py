"""HTTP-based LLM backend — calls an OpenAI-compatible Chat Completions API.

Works with:
- Docker Model Runner (the primary target: host-side Metal GPU acceleration)
- Ollama (`/v1/chat/completions`)
- LM Studio
- vLLM
- OpenAI / Anthropic / any compatible endpoint

This backend is drop-in for the in-process llama-cpp-python backend.
The `AIGenerator` picks between them based on config — no LLM caller
knows or cares which backend is answering.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class HttpBackend:
    """OpenAI-compatible HTTP LLM backend.

    Example config for Docker Model Runner:
        base_url = "http://model-runner.docker.internal/engines/v1"
        model    = "ai/gemma3"

    Example config for host-accessible Docker Model Runner:
        base_url = "http://localhost:12434/engines/v1"
        model    = "ai/gemma3"
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._warmed = False

    def is_available(self) -> bool:
        """Return True if the endpoint responds to a models list request."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models",
                headers=self._headers(),
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return "data" in data or "object" in data
        except Exception as exc:
            logger.debug("HTTP backend unavailable: %s", exc)
            return False

    def status(self) -> dict[str, Any]:
        available = self.is_available()
        return {
            "backend": "http",
            "base_url": self.base_url,
            "model": self.model,
            "available": available,
        }

    def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Send a chat completion and return the raw response content.

        Returns an empty string on failure (caller falls back to Faker).
        """
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={**self._headers(), "Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                choices = data.get("choices", [])
                if not choices:
                    return ""
                msg = choices[0].get("message", {})
                return msg.get("content", "")
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            logger.warning(
                "HTTP backend inference failed: HTTP %s — %s",
                e.code, body_text or e.reason,
            )
            return ""
        except Exception as exc:
            logger.warning("HTTP backend inference failed: %s", exc)
            return ""

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h
