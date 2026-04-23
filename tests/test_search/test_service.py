"""Integration tests for the ES query facade.

These hit a real Elasticsearch instance at `ELASTICSEARCH_URL`. Skipped
when that env var is unset so CI / laptops without the docker stack up
don't fail the suite. The `docker compose up` path in development runs
ES on :9200, which is what these tests target.

Each test uses a throwaway index name (suffixed with a per-test uuid) so
parallel / repeated runs don't collide. We monkey-patch
`specs_agent.search.schema.INDEX_NAME` to point at the throwaway.
"""

from __future__ import annotations

import os
import uuid

import pytest

from specs_agent.search import client as client_mod
from specs_agent.search import schema as schema_mod
from specs_agent.search import service as service_mod


pytestmark = pytest.mark.skipif(
    not os.environ.get("ELASTICSEARCH_URL"),
    reason="ELASTICSEARCH_URL not set — skipping live ES integration tests",
)


# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #


@pytest.fixture
async def es_index(monkeypatch):
    """Create a throwaway ES index; drop it on teardown.

    Yields the ES client so the test can index docs directly. The index
    name is patched into both `schema_mod.INDEX_NAME` and
    `service_mod.INDEX_NAME` so `search()` queries the right place.
    """
    name = f"specs_agent_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(schema_mod, "INDEX_NAME", name)
    monkeypatch.setattr(service_mod, "INDEX_NAME", name)

    # Force a fresh client so this test's URL env is respected.
    await client_mod.close_client()
    client = client_mod.get_client()

    await schema_mod.ensure_index(client)
    try:
        yield client
    finally:
        try:
            await client.indices.delete(index=name)
        except Exception:
            pass
        await client_mod.close_client()


async def _index(client, name: str, docs: list[tuple[str, dict]]) -> None:
    """Bulk-index the given (id, source) pairs and refresh the index."""
    for doc_id, source in docs:
        await client.index(index=name, id=doc_id, document=source)
    await client.indices.refresh(index=name)


# --------------------------------------------------------------------- #
# Empty query behavior
# --------------------------------------------------------------------- #


class TestEmptyQuery:
    async def test_empty_string_returns_empty_result(self, es_index) -> None:
        result = await service_mod.search("")
        assert result.total == 0
        # groups key is populated even when empty — frontend iterates it.
        assert set(result.groups.keys()) == set(service_mod.KNOWN_KINDS)
        assert all(v == [] for v in result.groups.values())

    async def test_whitespace_only_returns_empty_result(self, es_index) -> None:
        result = await service_mod.search("   ")
        assert result.total == 0


# --------------------------------------------------------------------- #
# Basic match + grouping
# --------------------------------------------------------------------- #


class TestBasicSearch:
    async def test_finds_and_groups_by_kind(self, es_index) -> None:
        name = schema_mod.INDEX_NAME
        await _index(es_index, name, [
            ("spec:petstore", {
                "kind": "spec", "spec_id": "petstore",
                "title": "Petstore API", "subtitle": "v1 · 10 endpoints",
                "haystack": "petstore api spec", "tags": [],
            }),
            ("endpoint:petstore:GET:/pets", {
                "kind": "endpoint", "spec_id": "petstore",
                "title": "GET /pets", "subtitle": "List pets",
                "haystack": "get /pets list pets petstore",
                "method": "GET", "path": "/pets",
            }),
            ("test_case:petstore:tc1", {
                "kind": "test_case", "spec_id": "petstore",
                "title": "List pets — happy", "subtitle": "Expects 200",
                "haystack": "get /pets list pets happy petstore",
            }),
            ("run:petstore:run_2026.json", {
                "kind": "run", "spec_id": "petstore",
                "title": "Run 2026-04-20", "subtitle": "8/10 passed",
                "haystack": "petstore run 2026",
                "pass_rate": 0.8,
            }),
        ])

        result = await service_mod.search("petstore")
        assert result.total > 0
        # At minimum the spec doc should land in the spec group.
        assert any(h.kind == "spec" for h in result.groups["spec"])
        # Endpoint / test_case matched because "petstore" is in their haystack.
        assert any(h.kind == "endpoint" for h in result.groups["endpoint"])

    async def test_kinds_filter(self, es_index) -> None:
        name = schema_mod.INDEX_NAME
        await _index(es_index, name, [
            ("spec:a", {
                "kind": "spec", "spec_id": "a",
                "title": "Alpha", "subtitle": "", "haystack": "alpha",
            }),
            ("endpoint:a:GET:/x", {
                "kind": "endpoint", "spec_id": "a",
                "title": "GET /x", "subtitle": "alpha", "haystack": "get /x alpha",
            }),
        ])

        result = await service_mod.search("alpha", kinds=["spec"])
        # Only spec hits surface, endpoint group is absent (filter dropped it).
        assert "endpoint" not in result.groups
        assert any(h.kind == "spec" for h in result.groups["spec"])


# --------------------------------------------------------------------- #
# Highlights
# --------------------------------------------------------------------- #


class TestHighlights:
    async def test_title_match_returns_mark_tags(self, es_index) -> None:
        name = schema_mod.INDEX_NAME
        await _index(es_index, name, [
            ("spec:petstore", {
                "kind": "spec", "spec_id": "petstore",
                "title": "Petstore API",
                "subtitle": "v1",
                "haystack": "petstore api",
            }),
        ])

        result = await service_mod.search("petstore")
        hit = result.groups["spec"][0]
        assert "<mark>" in hit.title
        assert "</mark>" in hit.title

    async def test_escaped_input_survives_highlight(self, es_index) -> None:
        """The XSS contract: stored title is already HTML-escaped.

        ES highlighting wraps `<mark>` around the escaped form, so the
        output is safe to render as innerHTML.
        """
        name = schema_mod.INDEX_NAME
        # `converters._esc("<script>alert(1)</script>")` would produce this.
        await _index(es_index, name, [
            ("spec:evil", {
                "kind": "spec", "spec_id": "evil",
                "title": "&lt;script&gt;alert(1)&lt;/script&gt;",
                "subtitle": "",
                "haystack": "script alert",
            }),
        ])

        result = await service_mod.search("script")
        hit = result.groups["spec"][0]
        # Critically: no raw `<script>` tag in the output. The only
        # unescaped `<` / `>` characters that may appear are the
        # highlighter's own `<mark>` / `</mark>` wrappers — every bit of
        # user content around them stays escaped as `&lt;` / `&gt;`.
        # (ES wraps `<mark>` around matched tokens, so the contiguous
        # `&lt;script&gt;` gets split into `&lt;<mark>script</mark>&gt;`.)
        assert "<script>" not in hit.title
        # User-supplied angle brackets are still entity-encoded.
        assert "&lt;" in hit.title and "&gt;" in hit.title
        # Strip the highlighter's wrappers — everything else must be a
        # mixture of entity-encoded characters and plain text.
        stripped = hit.title.replace("<mark>", "").replace("</mark>", "")
        assert "<" not in stripped and ">" not in stripped


# --------------------------------------------------------------------- #
# Missing index
# --------------------------------------------------------------------- #


class TestMissingIndex:
    async def test_returns_empty_when_index_absent(self, monkeypatch) -> None:
        """If the index doesn't exist, search returns empty, not 500."""
        monkeypatch.setattr(schema_mod, "INDEX_NAME", "definitely_not_a_real_index_x9")
        monkeypatch.setattr(service_mod, "INDEX_NAME", "definitely_not_a_real_index_x9")
        await client_mod.close_client()
        result = await service_mod.search("anything")
        assert result.total == 0
        await client_mod.close_client()
