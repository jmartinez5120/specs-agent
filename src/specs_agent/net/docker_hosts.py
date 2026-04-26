"""Host rewriting utilities for running inside Docker.

Two complementary rewrites:

* :func:`rewrite_localhost_for_docker` — at request time, swap
  ``localhost`` / ``127.0.0.1`` for ``host.docker.internal`` so a call
  fired from inside the api container actually reaches the host.

* :func:`rewrite_for_display` — at display time, swap
  ``host.docker.internal`` back to ``localhost`` so the user (who types
  ``localhost:8080`` in their browser) isn't confused by docker-internal
  hostnames the backend needed for fetching.

Both are no-ops outside of Docker, and no-ops for non-HTTP URLs.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_DOCKER_HOST = "host.docker.internal"


def running_in_docker() -> bool:
    """True if this process is in a Docker container."""
    flag = os.environ.get("SPECS_AGENT_IN_DOCKER", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    return Path("/.dockerenv").exists()


def rewrite_localhost_for_docker(source: str) -> str:
    """Swap loopback hosts for ``host.docker.internal`` when in Docker."""
    if not source or not isinstance(source, str):
        return source
    if not source.startswith(("http://", "https://")):
        return source
    if not running_in_docker():
        return source

    parts = urlsplit(source)
    host = (parts.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return source

    netloc = _DOCKER_HOST
    if parts.port is not None:
        netloc += f":{parts.port}"
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def rewrite_for_display(source: str) -> str:
    """Swap ``host.docker.internal`` back to ``localhost`` for display.

    Applied to spec-server URLs after extraction so the UI shows what the
    user typed, not the docker-internal form the backend used to fetch.
    """
    if not source or not isinstance(source, str):
        return source
    if not source.startswith(("http://", "https://")):
        return source
    if not running_in_docker():
        return source

    parts = urlsplit(source)
    host = (parts.hostname or "").lower()
    if host != _DOCKER_HOST:
        return source

    netloc = "localhost"
    if parts.port is not None:
        netloc += f":{parts.port}"
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
