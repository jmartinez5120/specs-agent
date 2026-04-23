"""Elasticsearch index name, mapping, and settings.

One index holds every searchable thing — specs, endpoints, test cases, and
runs — discriminated by the `kind` keyword field. This is the simplest
topology that satisfies the UI requirements (per-kind grouping, top-N per
kind) without the overhead of multiple indices.

Analyzers:
  `standard`              — default for all `text` fields; good word-level
                            tokenization and lowercasing.
  `autocomplete_analyzer` — lowercase + edge_ngram (min=2, max=15). We use
                            this only as the **search** analyzer on `title`
                            so prefix queries work (e.g. "pet" matches
                            "petstore") without inflating the index with
                            ngram tokens.
"""

from __future__ import annotations

from elasticsearch import AsyncElasticsearch, NotFoundError

INDEX_NAME = "specs_agent"

SETTINGS: dict = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        "analyzer": {
            # Search-time analyzer for title: lowercase + edge_ngram so
            # "pet" matches "petstore" without bloating the index.
            "autocomplete_analyzer": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "autocomplete_filter"],
            },
        },
        "filter": {
            "autocomplete_filter": {
                "type": "edge_ngram",
                "min_gram": 2,
                "max_gram": 15,
            },
        },
    },
}

# Field shape — see CLAUDE.md "Search" subsection for the why.
MAPPINGS: dict = {
    "properties": {
        "kind": {"type": "keyword"},
        "spec_id": {"type": "keyword"},
        # `org_id` is nullable and unused today — reserved for multi-tenancy
        # so we don't have to reindex when we add it. Not enforced anywhere.
        "org_id": {"type": "keyword"},
        "title": {
            "type": "text",
            # Index with standard, but allow autocomplete on query.
            "analyzer": "standard",
            "search_analyzer": "autocomplete_analyzer",
            "fields": {
                # Exact-match + sort-friendly.
                "keyword": {"type": "keyword", "ignore_above": 256},
            },
        },
        "subtitle": {"type": "text", "analyzer": "standard"},
        "haystack": {"type": "text", "analyzer": "standard"},
        "tags": {"type": "keyword"},
        "method": {"type": "keyword"},
        "path": {"type": "keyword"},
        "operation_id": {"type": "keyword"},
        "pass_rate": {"type": "float"},
        "updated_at": {"type": "date"},
        # `suggest` enables the completion suggester for typeahead. Even if
        # we don't wire it up in this PR, baking the field into the mapping
        # now means we don't need a reindex later.
        "suggest": {"type": "completion"},
    },
}


async def ensure_index(client: AsyncElasticsearch) -> bool:
    """Create the index if it doesn't exist. Returns True if created.

    Idempotent. Safe to call on every startup. Does NOT validate the
    existing mapping matches — use `reset_index()` for breaking schema
    changes.
    """
    exists = await client.indices.exists(index=INDEX_NAME)
    if exists:
        return False
    await client.indices.create(
        index=INDEX_NAME,
        settings=SETTINGS,
        mappings=MAPPINGS,
    )
    return True


async def reset_index(client: AsyncElasticsearch) -> None:
    """Delete (if exists) and recreate the index with the current mapping.

    Destructive — drops all indexed docs. Used when the mapping changes
    incompatibly. Callers are expected to trigger a backfill afterwards.
    """
    try:
        await client.indices.delete(index=INDEX_NAME)
    except NotFoundError:
        pass
    await client.indices.create(
        index=INDEX_NAME,
        settings=SETTINGS,
        mappings=MAPPINGS,
    )


async def index_is_empty(client: AsyncElasticsearch) -> bool:
    """True if the index exists and holds zero documents."""
    try:
        resp = await client.count(index=INDEX_NAME)
        return int(resp.get("count", 0)) == 0
    except NotFoundError:
        return True
