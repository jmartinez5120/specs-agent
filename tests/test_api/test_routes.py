"""Unit tests for the REST routes of the specs-agent API.

Each route is tested in isolation with an engine backed by a tmp-path
FileStorage. The WebSocket `/ws/execute` endpoint has its own test file.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


# ------------------------------------------------------------------ #
# Health
# ------------------------------------------------------------------ #


class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["service"] == "specs-agent-api"


# ------------------------------------------------------------------ #
# Specs
# ------------------------------------------------------------------ #


class TestLoadSpec:
    def test_load_from_file(self, client: TestClient, petstore_spec: str) -> None:
        r = client.post("/specs/load", json={"source": petstore_spec})
        assert r.status_code == 200
        body = r.json()
        assert "spec" in body
        assert body["spec"]["title"]
        assert len(body["spec"]["endpoints"]) > 0
        assert body["source_type"] == "file"
        assert isinstance(body["warnings"], list)

    def test_load_nonexistent_returns_400(self, client: TestClient) -> None:
        r = client.post("/specs/load", json={"source": "/nonexistent/fake.yaml"})
        assert r.status_code == 400
        assert "detail" in r.json()

    def test_missing_source_field_422(self, client: TestClient) -> None:
        r = client.post("/specs/load", json={})
        assert r.status_code == 422


# ------------------------------------------------------------------ #
# Plans
# ------------------------------------------------------------------ #


def _load_spec(client: TestClient, source: str) -> dict:
    return client.post("/specs/load", json={"source": source}).json()


class TestGeneratePlan:
    def test_generate_plan_happy(self, client: TestClient, petstore_spec: str) -> None:
        loaded = _load_spec(client, petstore_spec)
        r = client.post(
            "/plans/generate",
            json={"spec": {"raw_spec": loaded["spec"]["raw_spec"], "source": petstore_spec}},
        )
        assert r.status_code == 200
        plan = r.json()
        assert plan["name"]
        assert plan["spec_title"]
        assert len(plan["test_cases"]) > 0
        # Structural sanity
        first = plan["test_cases"][0]
        assert "endpoint_path" in first
        assert "method" in first
        assert "assertions" in first

    def test_generate_with_garbage_spec_yields_empty_plan(self, client: TestClient) -> None:
        """The extractor is tolerant — a non-OpenAPI dict just produces zero endpoints
        and therefore zero test cases. It does not error."""
        r = client.post(
            "/plans/generate",
            json={"spec": {"raw_spec": {"garbage": True}, "source": ""}},
        )
        assert r.status_code == 200
        plan = r.json()
        assert plan["test_cases"] == []


class TestGenerateOrMergePlan:
    def test_no_saved_plan_merge_is_null(
        self, client: TestClient, petstore_spec: str
    ) -> None:
        loaded = _load_spec(client, petstore_spec)
        r = client.post(
            "/plans/generate-or-merge",
            json={"spec": {"raw_spec": loaded["spec"]["raw_spec"], "source": petstore_spec}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["merge"] is None
        assert len(body["plan"]["test_cases"]) > 0

    def test_with_saved_plan_merges(self, client: TestClient, petstore_spec: str) -> None:
        loaded = _load_spec(client, petstore_spec)
        raw_payload = {"spec": {"raw_spec": loaded["spec"]["raw_spec"], "source": petstore_spec}}

        # Generate initial, edit, save
        plan = client.post("/plans/generate", json=raw_payload).json()
        plan["auth_type"] = "bearer"
        plan["auth_value"] = "tok"
        save_resp = client.post("/plans/save", json={"plan": plan})
        assert save_resp.status_code == 200
        assert Path(save_resp.json()["path"]).exists()

        # Re-generate with merge
        r = client.post("/plans/generate-or-merge", json=raw_payload)
        assert r.status_code == 200
        body = r.json()
        assert body["merge"] is not None
        assert body["merge"]["kept"] > 0
        assert body["merge"]["new"] == 0
        assert body["plan"]["auth_type"] == "bearer"
        assert body["plan"]["auth_value"] == "tok"


class TestSaveLoadPlan:
    def test_save_and_load_roundtrip(self, client: TestClient, petstore_spec: str) -> None:
        loaded = _load_spec(client, petstore_spec)
        spec_title = loaded["spec"]["title"]
        raw_payload = {"spec": {"raw_spec": loaded["spec"]["raw_spec"], "source": petstore_spec}}

        plan = client.post("/plans/generate", json=raw_payload).json()
        plan["test_cases"][0]["path_params"]["petId"] = "USER-EDIT"
        client.post("/plans/save", json={"plan": plan})

        r = client.get(f"/plans/{spec_title}")
        assert r.status_code == 200
        loaded_plan = r.json()
        edited = next(
            tc for tc in loaded_plan["test_cases"]
            if tc["name"] == plan["test_cases"][0]["name"]
        )
        assert edited["path_params"].get("petId") == "USER-EDIT"

    def test_load_missing_plan_404(self, client: TestClient) -> None:
        r = client.get("/plans/NonExistentSpecTitle")
        assert r.status_code == 404

    def test_archive_plan(self, client: TestClient, petstore_spec: str) -> None:
        loaded = _load_spec(client, petstore_spec)
        raw_payload = {"spec": {"raw_spec": loaded["spec"]["raw_spec"], "source": petstore_spec}}
        plan = client.post("/plans/generate", json=raw_payload).json()

        r = client.post("/plans/archive", json={"plan": plan})
        assert r.status_code == 200
        path = r.json()["path"]
        assert path
        assert "archive" in path
        assert Path(path).exists()


# ------------------------------------------------------------------ #
# Config
# ------------------------------------------------------------------ #


class TestConfigRoutes:
    def test_get_config_default(self, client: TestClient) -> None:
        r = client.get("/config")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] >= 1
        assert "timeout_seconds" in body
        assert "theme" in body

    def test_put_config_roundtrip(self, client: TestClient, tmp_path, monkeypatch) -> None:
        # Point config persistence at the tmp dir
        from specs_agent import config as cfg_mod
        monkeypatch.setattr(cfg_mod, "get_config_dir", lambda: tmp_path)
        monkeypatch.setattr(cfg_mod, "get_config_path", lambda: tmp_path / "config.yaml")

        current = client.get("/config").json()
        current["base_url"] = "https://new.example"
        current["timeout_seconds"] = 77.0
        current["theme"] = "light"

        r = client.put("/config", json=current)
        assert r.status_code == 204

        back = client.get("/config").json()
        assert back["base_url"] == "https://new.example"
        assert back["timeout_seconds"] == 77.0
        assert back["theme"] == "light"


# ------------------------------------------------------------------ #
# History
# ------------------------------------------------------------------ #


class TestHistoryRoutes:
    def test_list_history_empty(self, client: TestClient) -> None:
        r = client.get("/history", params={"spec_title": "X", "base_url": "http://x"})
        assert r.status_code == 200
        assert r.json() == []

    def test_list_history_validates_params(self, client: TestClient) -> None:
        r = client.get("/history")  # missing required params
        assert r.status_code == 422

    def test_load_missing_run_404(self, client: TestClient) -> None:
        r = client.get(
            "/history/run",
            params={"spec_title": "X", "base_url": "http://x", "filename": "missing.json"},
        )
        assert r.status_code == 404


# ------------------------------------------------------------------ #
# Report rendering
# ------------------------------------------------------------------ #


class TestSearchInFileMode:
    """In file-storage mode (the fixture default), /search must 503.

    Search is Elasticsearch-backed now and only available when the engine
    is running on MongoStorage with change streams driving the index.
    See `specs_agent.search` and PR 2 of the search pivot.
    """

    def test_post_search_returns_503_on_file_storage(self, client: TestClient) -> None:
        r = client.post("/search", json={"q": "anything"})
        assert r.status_code == 503
        assert "mongo" in r.json()["detail"].lower()

    def test_legacy_get_search_index_is_gone(self, client: TestClient) -> None:
        r = client.get("/search/index")
        # Removed — nothing should answer this path anymore.
        assert r.status_code == 404


class TestRenderReport:
    def _minimal_report_dict(self) -> dict:
        return {
            "plan_name": "Test",
            "base_url": "http://x",
            "spec_title": "Test Spec",
            "started_at": "2026-04-15T00:00:00+00:00",
            "finished_at": "2026-04-15T00:00:01+00:00",
            "duration_seconds": 1.0,
            "functional_results": [],
            "performance_results": [],
        }

    def test_render_inline_html(self, client: TestClient) -> None:
        r = client.post("/reports/html", json={"report": self._minimal_report_dict()})
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Test" in r.text

    def test_render_to_file(self, client: TestClient, tmp_path) -> None:
        output = str(tmp_path / "out.html")
        r = client.post(
            "/reports/html",
            json={"report": self._minimal_report_dict(), "output_path": output},
        )
        assert r.status_code == 200
        assert r.headers.get("x-output-path") == output
        assert Path(output).exists()

    def test_invalid_report_400(self, client: TestClient) -> None:
        # functional_results with invalid status → reconstruction falls back
        # (dict_to_report is lenient). Test truly invalid JSON structure:
        r = client.post("/reports/html", json={"report": "not-a-dict"})
        # Pydantic validates req.report as dict → 422 before our handler
        assert r.status_code in (400, 422)
