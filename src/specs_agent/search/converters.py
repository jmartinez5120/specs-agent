"""Pure functions: Mongo documents → Elasticsearch documents.

These are the only place where OpenAPI spec strings cross into data that
will eventually be rendered as `innerHTML` on the frontend (ES highlight
output wraps matched tokens in `<mark>`, and we send the highlighted
title/subtitle straight into the DOM).

XSS defense: every user-supplied string is HTML-escaped **before** we hand
it to ES. ES highlighting then inserts `<mark>` around already-escaped
content, so what comes back is safe to inject as innerHTML.

Shape of each returned doc mirrors the old `_build_search_index` output
(kind, spec_id, title, subtitle, haystack, plus typed fields like
method/path/pass_rate) so the API response shape stays recognizable.

Every function returns a list of `{"_id": ..., "doc": {...}}` tuples; the
indexer lifts these into `_bulk` actions.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Iterable

from specs_agent.parsing.extractor import extract_spec


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _esc(s: Any) -> str:
    """HTML-escape any value for safe inclusion in indexed strings.

    We escape at index time so that ES highlight output (which only adds
    `<mark>` tags around already-escaped content) is safe for innerHTML
    on the frontend. Non-strings are coerced via `str()`.
    """
    if s is None:
        return ""
    return html.escape(str(s), quote=False)


def _haystack(*parts: str) -> str:
    """Join non-empty, lower-cased parts with spaces.

    Matches the old `_build_search_index` haystack shape so search
    behavior stays recognisable.
    """
    return " ".join(p.lower() for p in parts if p)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def doc_id(kind: str, *parts: str) -> str:
    """Stable ES document ID. Colons separate `kind:spec_id:...:subid`.

    IDs MUST be stable across updates — that's how _bulk upserts dedupe.
    """
    safe = [str(p).replace(":", "_").replace(" ", "_") for p in parts]
    return f"{kind}:" + ":".join(safe)


# --------------------------------------------------------------------- #
# Spec document: one per saved spec, plus N endpoint docs.
# --------------------------------------------------------------------- #


def spec_to_docs(spec_row: dict) -> list[tuple[str, dict]]:
    """Convert a Mongo `specs` document into ES docs.

    Yields the spec doc + one endpoint doc per endpoint (if the raw spec
    can be parsed). Matches the `_build_search_index` semantics: each doc
    carries a `spec_id` that points to the owning saved-spec.

    `spec_row` shape (from MongoStorage.save_spec):
        { _id, title, source, source_type, saved_at, raw_spec }
    """
    spec_id = str(spec_row.get("_id") or spec_row.get("id") or "")
    if not spec_id:
        return []

    spec_title = str(spec_row.get("title") or spec_id)
    source = str(spec_row.get("source") or "")
    source_type = str(spec_row.get("source_type") or "")
    saved_at = str(spec_row.get("saved_at") or _now_iso())
    raw_spec = spec_row.get("raw_spec")

    # Try to parse the raw spec for endpoints/version. If it fails, we
    # still index the spec-level doc — losing endpoints is non-fatal.
    endpoints: list = []
    version = ""
    base_url = ""
    try:
        if raw_spec:
            parsed = extract_spec(raw_spec, source_url=source)
            endpoints = list(parsed.endpoints or [])
            version = parsed.version or ""
            base_url = parsed.base_url or ""
    except Exception:
        endpoints = []

    docs: list[tuple[str, dict]] = []

    # ---- spec-level doc ------------------------------------------------ #
    subtitle_parts: list[str] = []
    if version:
        subtitle_parts.append(f"v{version}")
    count = len(endpoints)
    subtitle_parts.append(f"{count} endpoint{'s' if count != 1 else ''}")
    if source:
        subtitle_parts.append(source)
    spec_subtitle = " · ".join(subtitle_parts)

    docs.append((
        doc_id("spec", spec_id),
        {
            "kind": "spec",
            "spec_id": spec_id,
            "org_id": None,
            "title": _esc(spec_title),
            "subtitle": _esc(spec_subtitle),
            "haystack": _haystack(
                spec_title, version, source, source_type, "spec",
            ),
            "tags": [],
            "updated_at": saved_at,
            "suggest": {"input": [spec_title] if spec_title else []},
            # Meta fields for UI activation — escaped since they render.
            "meta": {
                "source": _esc(source),
                "source_type": _esc(source_type),
                "saved_at": saved_at,
                "version": _esc(version),
                "endpoint_count": count,
                "base_url": _esc(base_url),
            },
        },
    ))

    # ---- endpoint docs ------------------------------------------------- #
    for ep in endpoints:
        method = getattr(ep.method, "value", str(ep.method))
        path = ep.path or ""
        summary = ep.summary or ""
        description = ep.description or ""
        op_id = ep.operation_id or ""
        tags = list(ep.tags or [])

        title = f"{method} {path}"
        sub_parts: list[str] = []
        if summary:
            sub_parts.append(summary)
        if tags:
            sub_parts.append(", ".join(tags))
        subtitle = " · ".join(sub_parts) if sub_parts else op_id

        docs.append((
            doc_id("endpoint", spec_id, method, path),
            {
                "kind": "endpoint",
                "spec_id": spec_id,
                "org_id": None,
                "title": _esc(title),
                "subtitle": _esc(subtitle),
                "haystack": _haystack(
                    method, path, summary, description, op_id,
                    " ".join(tags), spec_title,
                ),
                "tags": [_esc(t) for t in tags],
                "method": method,
                "path": path,
                "operation_id": op_id,
                "updated_at": saved_at,
                "suggest": {"input": [p for p in (title, op_id) if p]},
                "meta": {
                    "method": method,
                    "path": _esc(path),
                    "operation_id": _esc(op_id),
                    "tags": [_esc(t) for t in tags],
                    "summary": _esc(summary),
                },
            },
        ))

    return docs


# --------------------------------------------------------------------- #
# Plan → test case docs
# --------------------------------------------------------------------- #


def plan_to_test_case_docs(
    plan_row: dict,
    *,
    spec_id: str | None = None,
) -> list[tuple[str, dict]]:
    """Convert a Mongo `plans` document into one ES doc per test case.

    `plan_row` shape (from MongoStorage.save_plan):
        { _id: spec_title, name, spec_title, base_url, test_cases: [...] }

    `spec_id` is the Mongo-side spec `_id` that owns this plan. When not
    supplied, we derive a best-effort one from `spec_title` using the same
    slug rule MongoStorage uses (lowercase + underscores, max 40 chars).
    """
    spec_title = str(plan_row.get("spec_title") or "")
    if not spec_id:
        spec_id = _slugify_spec_id(spec_title)
    if not spec_id:
        return []

    saved_at = str(plan_row.get("created_at") or _now_iso())
    docs: list[tuple[str, dict]] = []

    for tc in plan_row.get("test_cases", []) or []:
        tc_id = str(tc.get("id") or "")
        if not tc_id:
            continue
        tc_method = str(tc.get("method") or "GET")
        tc_path = str(tc.get("endpoint_path") or "")
        tc_name = str(tc.get("name") or "")
        tc_desc = str(tc.get("description") or "")
        tc_type = str(tc.get("test_type") or "")
        expected = _expected_status_from_assertions(tc.get("assertions") or [])

        title = tc_name or f"{tc_method} {tc_path}"
        subtitle = f"Expects {expected}" if expected else tc_desc

        docs.append((
            doc_id("test_case", spec_id, tc_id),
            {
                "kind": "test_case",
                "spec_id": spec_id,
                "org_id": None,
                "title": _esc(title),
                "subtitle": _esc(subtitle),
                "haystack": _haystack(
                    tc_method, tc_path, tc_name, tc_desc, tc_type,
                    expected, spec_title,
                ),
                "tags": [],
                "method": tc_method,
                "path": tc_path,
                "updated_at": saved_at,
                "suggest": {"input": [title] if title else []},
                "meta": {
                    "test_case_id": _esc(tc_id),
                    "method": tc_method,
                    "path": _esc(tc_path),
                    "test_type": _esc(tc_type),
                    "description": _esc(tc_desc),
                    "expected_status": _esc(expected),
                },
            },
        ))

    return docs


def _expected_status_from_assertions(assertions: list) -> str:
    """Pull the `status_code` expectation out of a test case's assertions."""
    for a in assertions or []:
        atype = a.get("type") if isinstance(a, dict) else getattr(a, "type", None)
        atype = getattr(atype, "value", atype)
        if str(atype).lower() in ("status_code", "status"):
            exp = a.get("expected") if isinstance(a, dict) else getattr(a, "expected", None)
            try:
                return str(exp) if exp is not None else ""
            except Exception:
                return ""
    return ""


def _slugify_spec_id(title: str) -> str:
    """Match MongoStorage.save_spec's slug rule so we stay linkable."""
    if not title:
        return ""
    return title.replace(" ", "_").lower()[:40]


# --------------------------------------------------------------------- #
# Run → run doc
# --------------------------------------------------------------------- #


def run_to_doc(run_row: dict) -> list[tuple[str, dict]]:
    """Convert a Mongo `history` document (one run) into an ES doc.

    `run_row` shape (from MongoStorage.save_run):
        { _id: "{spec_hash}:{filename}", spec_hash, filename,
          spec_title, base_url, started_at, total_tests,
          passed_tests, failed_tests, error_tests, pass_rate, ... }

    Derives `spec_id` via the same slug rule MongoStorage uses for specs.
    That means a run and its owning spec share a `spec_id`, so the UI
    can jump from a run hit directly into the spec detail view.
    """
    filename = str(run_row.get("filename") or "")
    spec_title = str(run_row.get("spec_title") or "")
    spec_id = _slugify_spec_id(spec_title)
    if not spec_id or not filename:
        return []

    base_url = str(run_row.get("base_url") or "")
    started_at = str(run_row.get("started_at") or _now_iso())
    total = int(run_row.get("total_tests") or run_row.get("total") or 0)
    passed = int(run_row.get("passed_tests") or run_row.get("passed") or 0)
    failed = int(run_row.get("failed_tests") or run_row.get("failed") or 0)
    errors = int(run_row.get("error_tests") or run_row.get("errors") or 0)
    pass_rate = run_row.get("pass_rate")
    if pass_rate is None and total:
        pass_rate = passed / total

    ts_display = started_at[:16].replace("T", " ") if started_at else ""
    title = f"Run {ts_display}" if ts_display else "Run"
    subtitle = f"{passed}/{total} passed" if total else "run"

    return [(
        doc_id("run", spec_id, filename),
        {
            "kind": "run",
            "spec_id": spec_id,
            "org_id": None,
            "title": _esc(title),
            "subtitle": _esc(subtitle),
            "haystack": _haystack(
                spec_title, "run", started_at, subtitle, filename,
            ),
            "tags": [],
            "pass_rate": float(pass_rate) if pass_rate is not None else None,
            "updated_at": started_at,
            "suggest": {"input": [title]},
            "meta": {
                "filename": _esc(filename),
                "timestamp": started_at,
                "total": total,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "pass_rate": pass_rate,
                "base_url": _esc(base_url),
                "spec_title": _esc(spec_title),
            },
        },
    )]


# --------------------------------------------------------------------- #
# Delete ID helpers — used by the change-stream tailer on delete events.
# --------------------------------------------------------------------- #


def ids_for_spec_delete(spec_id: str) -> Iterable[str]:
    """IDs to remove when a spec is deleted.

    The spec itself and all of its endpoints. Test cases for the spec's
    plan and its runs are handled when those Mongo docs are deleted — we
    don't try to cascade here since change streams give us each delete
    separately.
    """
    # Endpoint docs are opaque-suffixed (method:path) — a prefix delete
    # via ES `delete_by_query` is simpler than enumerating them.
    return [doc_id("spec", spec_id)]  # plus delete_by_query on prefix


def plan_id_prefix(spec_id: str) -> str:
    """Prefix for every test-case doc belonging to a spec's plan.

    Used with `delete_by_query` in the indexer when a plan is deleted.
    """
    return doc_id("test_case", spec_id) + ":"


def run_id(spec_id: str, filename: str) -> str:
    """ES doc ID for a specific run."""
    return doc_id("run", spec_id, filename)


def endpoint_id_prefix(spec_id: str) -> str:
    """Prefix for every endpoint doc belonging to a spec."""
    return doc_id("endpoint", spec_id) + ":"
