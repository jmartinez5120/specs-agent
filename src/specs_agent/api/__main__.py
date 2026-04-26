"""Run the specs-agent API server via `python -m specs_agent.api`.

Environment variables:
    SPECS_AGENT_HOST     — bind host (default: 127.0.0.1)
    SPECS_AGENT_PORT     — bind port (default: 8765)
    SPECS_AGENT_RELOAD   — "1" enables uvicorn auto-reload (dev)
    SPECS_AGENT_STORAGE  — "file" (default) or "mongo"
    SPECS_AGENT_MONGO_URL — mongo connection URL when storage=mongo
    SPECS_AGENT_MONGO_DB  — mongo database name when storage=mongo
"""

from __future__ import annotations

import os

import uvicorn

from specs_agent.api.app import create_app
from specs_agent.engine import Engine, build_storage_from_env


def _make_app():
    """App factory — resolves storage from env so Docker flips to Mongo."""
    return create_app(engine=Engine(storage=build_storage_from_env()))


def main() -> None:
    host = os.environ.get("SPECS_AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("SPECS_AGENT_PORT", "8765"))
    reload = os.environ.get("SPECS_AGENT_RELOAD", "0") == "1"
    uvicorn.run(
        "specs_agent.api.__main__:_make_app",
        host=host,
        port=port,
        factory=True,
        reload=reload,
    )


if __name__ == "__main__":
    main()
