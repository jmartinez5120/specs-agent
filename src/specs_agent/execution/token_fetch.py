"""Runtime bearer-token fetcher for pre-request auth injection.

When TestRunConfig.token_fetch is set, the executor uses a TokenFetcher
to obtain a bearer token before each outbound request. The fetcher caches
the token in memory and honors `expires_in` from the token response; if
that field is absent, each call re-fetches (per user requirement — tokens
can expire mid-run and we don't know when).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from specs_agent.models.config import TokenFetchConfig


class TokenFetchError(RuntimeError):
    pass


class TokenFetcher:
    """Async-safe token fetcher with TTL-based caching.

    - If the token response carries `expires_in` (seconds), the token is
      cached until `expires_in - _SAFETY_MARGIN_S` and reused.
    - Otherwise a fresh token is fetched for every call (no cache).
    """

    _SAFETY_MARGIN_S = 5.0

    def __init__(self, config: TokenFetchConfig, *, verify_ssl: bool = True, timeout_s: float = 30.0) -> None:
        self.config = config
        self.verify_ssl = verify_ssl
        self.timeout_s = timeout_s
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        """Return a current bearer token, fetching or refreshing as needed."""
        now = time.monotonic()
        if not force_refresh and self._token and now < self._expires_at:
            return self._token

        async with self._lock:
            # Double-check after acquiring the lock.
            now = time.monotonic()
            if not force_refresh and self._token and now < self._expires_at:
                return self._token

            token, ttl = await self._fetch()
            self._token = token
            # No TTL reported → treat as already expired so the next call refetches.
            self._expires_at = (time.monotonic() + max(ttl - self._SAFETY_MARGIN_S, 0.0)) if ttl > 0 else 0.0
            return token

    async def _fetch(self) -> tuple[str, float]:
        tf = self.config
        if not tf.token_url:
            raise TokenFetchError("token_url is not configured")

        body: dict[str, Any] = {}
        if tf.extra_body.strip():
            try:
                parsed = json.loads(tf.extra_body)
            except json.JSONDecodeError as e:
                raise TokenFetchError(f"Invalid extra_body JSON: {e}") from e
            if not isinstance(parsed, dict):
                raise TokenFetchError("extra_body must decode to a JSON object")
            body.update(parsed)
        if tf.integration_id_field and tf.integration_id_value:
            body[tf.integration_id_field] = tf.integration_id_value
        if tf.scope:
            body["scope"] = tf.scope

        headers: dict[str, str] = {
            "content-type": "application/json",
            "accept": "application/json",
        }
        if tf.headers.strip():
            try:
                extra = json.loads(tf.headers)
            except json.JSONDecodeError as e:
                raise TokenFetchError(f"Invalid headers JSON: {e}") from e
            if not isinstance(extra, dict):
                raise TokenFetchError("headers must decode to a JSON object")
            for k, v in extra.items():
                headers[str(k)] = str(v)

        method = (tf.method or "POST").upper()
        async with httpx.AsyncClient(timeout=self.timeout_s, verify=self.verify_ssl) as client:
            req_kwargs: dict[str, Any] = {"headers": headers}
            if method != "GET":
                req_kwargs["json"] = body
            response = await client.request(method, tf.token_url, **req_kwargs)
        if response.status_code >= 400:
            raise TokenFetchError(
                f"Token endpoint returned {response.status_code}: {response.text[:200]}"
            )

        ct = response.headers.get("content-type", "")
        payload: Any = response.json() if "json" in ct else response.text

        raw = payload if isinstance(payload, str) else _pick_path(payload, tf.token_response_path or "access_token")
        if not isinstance(raw, str) or not raw:
            raise TokenFetchError(
                f"Token not found at path '{tf.token_response_path}' in response"
            )
        if tf.response_has_bearer_prefix:
            raw = raw[len("Bearer "):] if raw.lower().startswith("bearer ") else raw

        ttl = 0.0
        if isinstance(payload, dict):
            ei = payload.get("expires_in")
            if isinstance(ei, (int, float)) and ei > 0:
                ttl = float(ei)

        return raw.strip(), ttl


def _pick_path(obj: Any, path: str) -> Any:
    cur: Any = obj
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur
