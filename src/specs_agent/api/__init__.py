"""HTTP/WebSocket API for specs-agent.

This module exposes the `Engine` facade over HTTP so the Web UI (and any
other client) can drive the same operations the TUI uses. The API is
stateless: every request passes the data it needs. Persistent state
(plans, config, history) lives in the engine's `Storage` layer.
"""

from specs_agent.api.app import create_app

__all__ = ["create_app"]
