"""Async Elasticsearch client — lazy singleton bound to ELASTICSEARCH_URL.

One client per process. `get_client()` returns the same `AsyncElasticsearch`
for the lifetime of the app; `close_client()` is called from the FastAPI
lifespan shutdown hook.

We deliberately do NOT auto-reconnect on config changes — the URL is read
once from the environment. Tests that need a different URL should call
`close_client()` to force a fresh connection next time.
"""

from __future__ import annotations

import os
from typing import Optional

from elasticsearch import AsyncElasticsearch


_client: Optional[AsyncElasticsearch] = None


def _resolve_url() -> str:
    """Resolve the ES URL from the environment.

    Defaults to localhost so developers running the API bare-metal against
    a locally-running ES (the common dev path) don't need to set anything.
    Inside Docker, `ELASTICSEARCH_URL=http://elasticsearch:9200` is injected
    by docker-compose.
    """
    return os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")


def get_client() -> AsyncElasticsearch:
    """Return the process-wide AsyncElasticsearch client, creating it lazily.

    Safe to call repeatedly. Not thread-safe across event loops — but the
    FastAPI app runs on a single event loop so that's not a concern.
    """
    global _client
    if _client is None:
        _client = AsyncElasticsearch(
            hosts=[_resolve_url()],
            # Keep retry behavior conservative: if ES is down, fail fast.
            # The lifespan already verified connectivity at startup.
            request_timeout=10,
            max_retries=2,
            retry_on_timeout=False,
        )
    return _client


async def close_client() -> None:
    """Close the singleton client, if any. Idempotent."""
    global _client
    if _client is not None:
        try:
            await _client.close()
        finally:
            _client = None


async def ping() -> bool:
    """Quick reachability check — used by the lifespan startup gate.

    Returns True iff ES answers the cluster-info endpoint. Does NOT
    distinguish between 'cluster red' and 'cluster green'; we just want
    to know the service is reachable before declaring startup OK.
    """
    try:
        await get_client().info()
        return True
    except Exception:
        return False
