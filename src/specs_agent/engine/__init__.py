"""Core engine for specs-agent.

The engine holds all business logic — parsing, plan generation, execution,
persistence — behind a single facade. TUI and Web UI are thin clients that
call into the engine; they do not contain business logic.

Storage is abstracted via the `Storage` protocol. `FileStorage` wraps the
local `~/.specs-agent/` file-based persistence. `MongoStorage` is used for
dockerized / server deployments. The `build_storage_from_env()` factory
selects between them based on environment variables (see `factory.py`).
"""

from specs_agent.engine.engine import Engine, MergeResult, SpecLoadResult
from specs_agent.engine.factory import build_storage_from_env
from specs_agent.engine.storage import FileStorage, Storage

__all__ = [
    "Engine",
    "Storage",
    "FileStorage",
    "MergeResult",
    "SpecLoadResult",
    "build_storage_from_env",
]
