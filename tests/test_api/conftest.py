"""Shared fixtures for API tests.

Every API test gets an engine backed by a tmp-path FileStorage so tests
never collide with the real `~/.specs-agent/` on the dev machine.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from specs_agent.api import create_app
from specs_agent.engine import Engine, FileStorage
from specs_agent.history import storage as hstore


FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def engine(tmp_path: Path, monkeypatch) -> Engine:
    """Engine with isolated storage root + isolated history dir."""
    storage = FileStorage(root=tmp_path / "specs-agent")
    monkeypatch.setattr(hstore, "HISTORY_DIR", tmp_path / "specs-agent" / "history")
    return Engine(storage=storage)


@pytest.fixture
def client(engine: Engine) -> TestClient:
    app = create_app(engine=engine)
    return TestClient(app)


@pytest.fixture
def petstore_spec() -> str:
    return str(FIXTURES / "petstore_v3.json")
