"""Pure-function tests for Mongo → ES document conversion.

No Elasticsearch, no Mongo — these exercise the shapes the indexer will
push, including the XSS-escaping contract: every user-supplied string
that could later be rendered as innerHTML on the frontend must be HTML
escaped BEFORE it hits ES.
"""

from __future__ import annotations

import pytest

from specs_agent.search.converters import (
    doc_id,
    endpoint_id_prefix,
    plan_id_prefix,
    plan_to_test_case_docs,
    run_to_doc,
    spec_to_docs,
)


# --------------------------------------------------------------------- #
# spec_to_docs
# --------------------------------------------------------------------- #


class TestSpecToDocs:
    def _spec_row(self, **overrides) -> dict:
        base = {
            "_id": "petstore",
            "title": "Petstore",
            "source": "https://example.com/petstore.yaml",
            "source_type": "url",
            "saved_at": "2026-04-20T10:00:00+00:00",
            "raw_spec": {
                "openapi": "3.0.0",
                "info": {"title": "Petstore", "version": "1.2.3"},
                "servers": [{"url": "https://api.example.com"}],
                "paths": {
                    "/pets": {
                        "get": {
                            "operationId": "listPets",
                            "summary": "List pets",
                            "tags": ["pets"],
                            "responses": {"200": {"description": "ok"}},
                        },
                    },
                },
            },
        }
        base.update(overrides)
        return base

    def test_emits_spec_doc_with_expected_fields(self) -> None:
        docs = spec_to_docs(self._spec_row())
        ids = [d[0] for d in docs]
        assert "spec:petstore" in ids

        spec_doc = next(d[1] for d in docs if d[1]["kind"] == "spec")
        assert spec_doc["spec_id"] == "petstore"
        assert spec_doc["title"] == "Petstore"
        assert "v1.2.3" in spec_doc["subtitle"]
        assert "1 endpoint" in spec_doc["subtitle"]
        # haystack is lowercase and contains both title and source
        assert spec_doc["haystack"] == spec_doc["haystack"].lower()
        assert "petstore" in spec_doc["haystack"]
        assert "example.com" in spec_doc["haystack"]

    def test_emits_endpoint_docs(self) -> None:
        docs = spec_to_docs(self._spec_row())
        ep_docs = [d[1] for d in docs if d[1]["kind"] == "endpoint"]
        assert len(ep_docs) == 1
        ep = ep_docs[0]
        assert ep["method"] == "GET"
        assert ep["path"] == "/pets"
        assert ep["spec_id"] == "petstore"
        assert "GET /pets" in ep["title"]
        # Endpoint IDs are prefixed for easy delete_by_query
        ep_id = next(d[0] for d in docs if d[1]["kind"] == "endpoint")
        assert ep_id.startswith(endpoint_id_prefix("petstore"))

    def test_missing_raw_spec_still_emits_spec_doc(self) -> None:
        docs = spec_to_docs(self._spec_row(raw_spec=None))
        # Just the spec-level doc, no endpoints
        assert len(docs) == 1
        assert docs[0][1]["kind"] == "spec"
        assert "0 endpoints" in docs[0][1]["subtitle"]

    def test_unparseable_raw_spec_degrades_gracefully(self) -> None:
        docs = spec_to_docs(self._spec_row(raw_spec={"garbage": True}))
        # Still get the spec doc; endpoint list is empty.
        kinds = [d[1]["kind"] for d in docs]
        assert "spec" in kinds
        assert "endpoint" not in kinds

    def test_missing_id_yields_no_docs(self) -> None:
        assert spec_to_docs(self._spec_row(_id=None)) == []


# --------------------------------------------------------------------- #
# XSS escaping — the critical safety contract
# --------------------------------------------------------------------- #


class TestXssEscaping:
    """Every user-supplied string is escaped before indexing.

    Frontend renders ES highlight output via innerHTML. ES highlight only
    adds `<mark>` around matched tokens; if those tokens already contain
    raw HTML from the spec, we'd have stored XSS. Escaping at index-time
    closes that gap.
    """

    def test_spec_title_with_script_tag_is_escaped(self) -> None:
        docs = spec_to_docs({
            "_id": "evil",
            "title": "<script>alert(1)</script>",
            "source": "file.yaml",
            "source_type": "file",
            "saved_at": "2026-04-20T00:00:00+00:00",
            "raw_spec": None,
        })
        spec_doc = docs[0][1]
        assert "<script>" not in spec_doc["title"]
        assert "&lt;script&gt;" in spec_doc["title"]

    def test_endpoint_summary_escaped(self) -> None:
        docs = spec_to_docs({
            "_id": "x",
            "title": "X",
            "source": "", "source_type": "file",
            "saved_at": "2026-04-20T00:00:00+00:00",
            "raw_spec": {
                "openapi": "3.0.0",
                "info": {"title": "X", "version": "1"},
                "paths": {
                    "/p": {
                        "get": {
                            "summary": "<img src=x onerror=alert(1)>",
                            "responses": {"200": {"description": "ok"}},
                        },
                    },
                },
            },
        })
        ep = next(d[1] for d in docs if d[1]["kind"] == "endpoint")
        assert "<img" not in ep["subtitle"]
        assert "&lt;img" in ep["subtitle"]

    def test_test_case_name_escaped(self) -> None:
        docs = plan_to_test_case_docs({
            "_id": "Spec Title",
            "spec_title": "Spec Title",
            "created_at": "2026-04-20T00:00:00+00:00",
            "test_cases": [
                {
                    "id": "tc1",
                    "name": "<b>bold</b>",
                    "method": "GET",
                    "endpoint_path": "/x",
                    "assertions": [],
                },
            ],
        })
        tc = docs[0][1]
        assert "<b>" not in tc["title"]
        assert "&lt;b&gt;" in tc["title"]

    def test_run_base_url_escaped(self) -> None:
        docs = run_to_doc({
            "filename": "run_2026.json",
            "spec_title": "Spec",
            "base_url": "http://x/<script>",
            "started_at": "2026-04-20T00:00:00+00:00",
            "total_tests": 1,
            "passed_tests": 1,
            "failed_tests": 0,
            "error_tests": 0,
        })
        meta = docs[0][1]["meta"]
        assert "<script>" not in meta["base_url"]
        assert "&lt;script&gt;" in meta["base_url"]


# --------------------------------------------------------------------- #
# plan_to_test_case_docs
# --------------------------------------------------------------------- #


class TestPlanToTestCaseDocs:
    def _plan_row(self, **overrides) -> dict:
        base = {
            "_id": "Petstore",
            "spec_title": "Petstore",
            "name": "Petstore Test Plan",
            "base_url": "https://api.example.com",
            "created_at": "2026-04-20T00:00:00+00:00",
            "test_cases": [
                {
                    "id": "tc1",
                    "name": "List pets — happy",
                    "method": "GET",
                    "endpoint_path": "/pets",
                    "description": "2xx response",
                    "test_type": "happy",
                    "assertions": [
                        {"type": "status_code", "expected": 200, "description": "200"},
                    ],
                },
                {
                    "id": "tc2",
                    "name": "List pets — sad",
                    "method": "GET",
                    "endpoint_path": "/pets",
                    "description": "auth missing",
                    "test_type": "sad",
                    "assertions": [
                        {"type": "status_code", "expected": 401, "description": "401"},
                    ],
                },
            ],
        }
        base.update(overrides)
        return base

    def test_one_doc_per_test_case(self) -> None:
        docs = plan_to_test_case_docs(self._plan_row())
        assert len(docs) == 2
        titles = [d[1]["title"] for d in docs]
        assert any("happy" in t for t in titles)
        assert any("sad" in t for t in titles)

    def test_expected_status_surfaced_in_subtitle(self) -> None:
        docs = plan_to_test_case_docs(self._plan_row())
        subtitles = [d[1]["subtitle"] for d in docs]
        assert "Expects 200" in subtitles
        assert "Expects 401" in subtitles

    def test_spec_id_slug_matches_mongo_storage(self) -> None:
        # MongoStorage slugs spec titles to `_id` via replace(' ', '_').lower()[:40].
        # The test_case docs should share that slug via `spec_id`.
        docs = plan_to_test_case_docs(self._plan_row(spec_title="My Big API"))
        for _id, src in docs:
            assert src["spec_id"] == "my_big_api"
            assert _id.startswith(plan_id_prefix("my_big_api"))

    def test_explicit_spec_id_override(self) -> None:
        docs = plan_to_test_case_docs(self._plan_row(), spec_id="override")
        for _, src in docs:
            assert src["spec_id"] == "override"

    def test_cases_without_id_are_skipped(self) -> None:
        row = self._plan_row()
        row["test_cases"].append({"name": "no id"})
        docs = plan_to_test_case_docs(row)
        assert len(docs) == 2  # 2 kept, 1 skipped

    def test_missing_spec_title_yields_no_docs(self) -> None:
        assert plan_to_test_case_docs({"test_cases": [{"id": "tc"}]}) == []


# --------------------------------------------------------------------- #
# run_to_doc
# --------------------------------------------------------------------- #


class TestRunToDoc:
    def _run_row(self, **overrides) -> dict:
        base = {
            "_id": "abc123:run_2026-04-20_10-00-00.json",
            "spec_hash": "abc123",
            "filename": "run_2026-04-20_10-00-00.json",
            "spec_title": "Petstore",
            "base_url": "https://api.example.com",
            "started_at": "2026-04-20T10:00:00+00:00",
            "total_tests": 10,
            "passed_tests": 8,
            "failed_tests": 2,
            "error_tests": 0,
        }
        base.update(overrides)
        return base

    def test_derives_pass_rate_from_counts(self) -> None:
        docs = run_to_doc(self._run_row())
        assert docs
        src = docs[0][1]
        assert src["pass_rate"] == pytest.approx(0.8)

    def test_subtitle_format(self) -> None:
        docs = run_to_doc(self._run_row())
        assert "8/10 passed" in docs[0][1]["subtitle"]

    def test_spec_id_is_slug_of_spec_title(self) -> None:
        docs = run_to_doc(self._run_row(spec_title="My Big API"))
        assert docs[0][1]["spec_id"] == "my_big_api"

    def test_missing_filename_yields_no_doc(self) -> None:
        assert run_to_doc(self._run_row(filename="")) == []

    def test_preexisting_pass_rate_is_preserved(self) -> None:
        docs = run_to_doc(self._run_row(pass_rate=0.42))
        assert docs[0][1]["pass_rate"] == pytest.approx(0.42)


# --------------------------------------------------------------------- #
# doc_id helpers
# --------------------------------------------------------------------- #


class TestDocIds:
    def test_doc_id_stable_across_calls(self) -> None:
        assert doc_id("spec", "a") == doc_id("spec", "a")

    def test_doc_id_escapes_colons(self) -> None:
        # Raw colons would clobber our prefix conventions.
        assert ":" not in doc_id("endpoint", "s:id", "GET", "/x")[len("endpoint:") :].split(":")[0]

    def test_endpoint_prefix_terminates_with_colon(self) -> None:
        assert endpoint_id_prefix("s").endswith(":")

    def test_plan_prefix_terminates_with_colon(self) -> None:
        assert plan_id_prefix("s").endswith(":")
