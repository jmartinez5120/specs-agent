"""Tests for the `/search` FastAPI route.

The route delegates to `specs_agent.search.service.search()`. We patch
the service at the module boundary so these tests don't need a running
Elasticsearch — they verify wiring, not ES behavior (that's in
`tests/test_search/test_service.py`).

Because the default client fixture uses FileStorage, `app.state.search_enabled`
is False and the route 503s. We add a dedicated fixture below that flips
the flag so we can exercise the success path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from specs_agent.api import create_app
from specs_agent.engine import Engine, FileStorage
from specs_agent.search.service import SearchHit, SearchResult


# --------------------------------------------------------------------- #
# 503 path (file-storage default)
# --------------------------------------------------------------------- #


class TestSearchRouteFileStorage:
    def test_returns_503_on_file_storage(self, client: TestClient) -> None:
        r = client.post("/search", json={"q": "foo"})
        assert r.status_code == 503
        assert "mongo" in r.json()["detail"].lower()

    def test_validates_limit_bounds(self, client: TestClient) -> None:
        # limit below 1 should 422 (pydantic validation), not 503.
        r = client.post("/search", json={"q": "foo", "limit": 0})
        assert r.status_code == 422

    def test_accepts_empty_query(self, client: TestClient) -> None:
        # Empty query is a valid request shape; the 503 still fires because
        # we never even reach the service layer.
        r = client.post("/search", json={"q": ""})
        assert r.status_code == 503


# --------------------------------------------------------------------- #
# Success path (search_enabled flipped, service mocked)
# --------------------------------------------------------------------- #


@pytest.fixture
def enabled_client(tmp_path, monkeypatch) -> TestClient:
    """Build a fresh app and flip `search_enabled` on post-construction.

    The default `client` fixture (from conftest.py) uses the normal app
    factory with FileStorage; it reflects the real 503 behavior. This
    fixture sidesteps the lifespan (we don't connect to ES) and forces
    `search_enabled=True` so we can test the wiring between route and
    service layer.
    """
    engine = Engine(storage=FileStorage(root=tmp_path / "specs-agent"))
    app = create_app(engine=engine)
    # Bypass the lifespan gate — we're not testing ES here.
    app.state.search_enabled = True
    return TestClient(app)


class TestSearchRouteSuccess:
    def test_delegates_to_service_and_serializes(self, enabled_client, monkeypatch) -> None:
        # Mock the service layer import target inside the route.
        async def fake_search(q, *, kinds=None, limit=30):
            assert q == "pets"
            assert kinds == ["spec", "endpoint"]
            assert limit == 10
            return SearchResult(
                groups={
                    "spec": [
                        SearchHit(
                            kind="spec", id="spec:petstore",
                            spec_id="petstore",
                            title="<mark>Pet</mark>store",
                            subtitle="v1 · 10 endpoints",
                            score=1.5, meta={"source": "x.yaml"},
                        ),
                    ],
                    "endpoint": [],
                },
                total=1,
            )

        monkeypatch.setattr(
            "specs_agent.search.service.search",
            fake_search,
        )

        r = enabled_client.post("/search", json={
            "q": "pets", "kinds": ["spec", "endpoint"], "limit": 10,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert "spec" in body["groups"]
        spec_hits = body["groups"]["spec"]
        assert len(spec_hits) == 1
        # Highlight `<mark>` tags survive serialization — the frontend
        # renders them verbatim via innerHTML.
        assert "<mark>" in spec_hits[0]["title"]
        assert spec_hits[0]["spec_id"] == "petstore"
        assert spec_hits[0]["meta"]["source"] == "x.yaml"

    def test_default_kinds_and_limit(self, enabled_client, monkeypatch) -> None:
        captured = {}

        async def fake_search(q, *, kinds=None, limit=30):
            captured["kinds"] = kinds
            captured["limit"] = limit
            return SearchResult(groups={}, total=0)

        monkeypatch.setattr(
            "specs_agent.search.service.search",
            fake_search,
        )

        r = enabled_client.post("/search", json={"q": "hello"})
        assert r.status_code == 200
        # No kinds → None is passed through; service does its own default.
        assert captured["kinds"] is None
        assert captured["limit"] == 30
