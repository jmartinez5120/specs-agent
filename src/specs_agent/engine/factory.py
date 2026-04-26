"""Storage factory — env-var driven selector for FileStorage vs MongoStorage.

Usage:
    engine = Engine(storage=build_storage_from_env())

Environment variables:
    SPECS_AGENT_STORAGE  — "file" (default) or "mongo"
    SPECS_AGENT_MONGO_URL — connection URL (default: mongodb://localhost:27017)
    SPECS_AGENT_MONGO_DB  — database name (default: specs_agent)
    SPECS_AGENT_DATA_DIR  — file-storage root (default: ~/.specs-agent)

This is the single point where the backend is chosen, so Dockerized
deployments flip `SPECS_AGENT_STORAGE=mongo` and everything else stays
identical.
"""

from __future__ import annotations

import os
from pathlib import Path

from specs_agent.engine.storage import FileStorage, Storage


def build_storage_from_env() -> Storage:
    backend = os.environ.get("SPECS_AGENT_STORAGE", "file").lower()

    if backend == "mongo":
        # Import lazily so pymongo is only required when actually used.
        from specs_agent.engine.mongo_storage import (
            DEFAULT_DB_NAME,
            DEFAULT_MONGO_URL,
            MongoStorage,
        )
        url = os.environ.get("SPECS_AGENT_MONGO_URL", DEFAULT_MONGO_URL)
        db_name = os.environ.get("SPECS_AGENT_MONGO_DB", DEFAULT_DB_NAME)
        return MongoStorage(url=url, db_name=db_name)

    # Default: file-based
    root = os.environ.get("SPECS_AGENT_DATA_DIR")
    return FileStorage(root=Path(root).expanduser() if root else None)
