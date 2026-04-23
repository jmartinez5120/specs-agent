"""Query facade — the `search()` function the API route delegates to.

Responsibilities:
  * Build the ES query (multi_match across title/subtitle/haystack with
    the weights and fuzziness the UI expects).
  * Run the query, pull highlights.
  * Group results by `kind` so the UI can render "Specs / Endpoints /
    Test Cases / Runs" sections without re-sorting client-side.

Empty query short-circuits to an empty response — we never dump the full
index. The frontend calls `/search` only when the user has typed something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from elasticsearch import NotFoundError

from specs_agent.search.client import get_client
from specs_agent.search.schema import INDEX_NAME


KNOWN_KINDS = ("spec", "endpoint", "test_case", "run")


@dataclass
class SearchHit:
    """One result row, rendered for the UI."""
    kind: str
    id: str
    spec_id: str
    # `title`/`subtitle` are the ES highlight output when the field
    # matched the query, and the escaped original otherwise. Either way
    # they're safe to render as innerHTML (only `<mark>` can be present,
    # and it's wrapped around already-escaped content — see converters.py).
    title: str
    subtitle: str
    score: float
    meta: dict


@dataclass
class SearchResult:
    """Top-level response: results grouped by kind."""
    groups: dict[str, list[SearchHit]] = field(default_factory=dict)
    total: int = 0


async def search(
    q: str,
    *,
    kinds: list[str] | None = None,
    limit: int = 30,
) -> SearchResult:
    """Query Elasticsearch and return grouped-by-kind hits.

    Args:
        q: User input. Empty / whitespace-only → empty result.
        kinds: Optional filter — only return docs with `kind` in this list.
            Defaults to all known kinds.
        limit: Max TOTAL hits across all kinds (ES `size`). The frontend
            typically slices each group to top-5 for display.

    Returns:
        SearchResult with `.groups[kind]` → list of SearchHit.
    """
    q = (q or "").strip()
    if not q:
        return SearchResult(groups={k: [] for k in (kinds or KNOWN_KINDS)}, total=0)

    effective_kinds = [k for k in (kinds or KNOWN_KINDS) if k in KNOWN_KINDS]
    if not effective_kinds:
        return SearchResult(groups={}, total=0)

    body: dict[str, Any] = {
        "size": max(1, min(int(limit), 200)),
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": q,
                            "fields": [
                                "title^3",
                                "subtitle^1.5",
                                "haystack^1",
                            ],
                            "fuzziness": "AUTO",
                            "operator": "and",
                            "minimum_should_match": "75%",
                        },
                    },
                ],
                "filter": [
                    {"terms": {"kind": effective_kinds}},
                ],
            },
        },
        "highlight": {
            "pre_tags": ["<mark>"],
            "post_tags": ["</mark>"],
            "fields": {
                "title": {"number_of_fragments": 0},
                "subtitle": {"number_of_fragments": 0},
            },
        },
    }

    client = get_client()
    try:
        resp = await client.search(index=INDEX_NAME, body=body)
    except NotFoundError:
        # Index missing — treat as empty rather than 500. This shouldn't
        # happen in normal operation (lifespan creates the index on boot)
        # but it's nicer for the UI to show 'no results' than to error.
        return SearchResult(groups={k: [] for k in effective_kinds}, total=0)

    groups: dict[str, list[SearchHit]] = {k: [] for k in effective_kinds}
    hits = resp.get("hits", {}).get("hits", [])
    for h in hits:
        src = h.get("_source", {}) or {}
        kind = str(src.get("kind") or "")
        if kind not in groups:
            continue
        highlight = h.get("highlight") or {}
        # If ES highlighted the field, that's the HTML-safe string to use;
        # otherwise fall back to the already-escaped stored value.
        title = (highlight.get("title") or [src.get("title", "")])[0]
        subtitle = (highlight.get("subtitle") or [src.get("subtitle", "")])[0]

        groups[kind].append(SearchHit(
            kind=kind,
            id=str(h.get("_id") or ""),
            spec_id=str(src.get("spec_id") or ""),
            title=title,
            subtitle=subtitle,
            score=float(h.get("_score") or 0.0),
            meta=src.get("meta") or {},
        ))

    total_obj = resp.get("hits", {}).get("total", 0)
    total = total_obj["value"] if isinstance(total_obj, dict) else int(total_obj)

    return SearchResult(groups=groups, total=int(total))


def result_to_dict(result: SearchResult) -> dict:
    """Serialize a SearchResult to the JSON shape the Web UI consumes."""
    return {
        "groups": {
            kind: [
                {
                    "kind": hit.kind,
                    "id": hit.id,
                    "spec_id": hit.spec_id,
                    "title": hit.title,
                    "subtitle": hit.subtitle,
                    "score": hit.score,
                    "meta": hit.meta,
                }
                for hit in hits
            ]
            for kind, hits in result.groups.items()
        },
        "total": result.total,
    }
