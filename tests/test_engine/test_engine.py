"""Unit tests for the Engine facade and FileStorage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from specs_agent.config import AppConfig, AuthPreset
from specs_agent.engine import Engine, FileStorage
from specs_agent.engine.engine import _merge_body
from specs_agent.models.plan import TestPlan
from specs_agent.models.results import (
    AssertionResult,
    PerformanceMetrics,
    Report,
    TestResult,
    TestStatus,
)
from specs_agent.parsing.loader import SpecLoadError


FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def tmp_storage(tmp_path: Path) -> FileStorage:
    return FileStorage(root=tmp_path)


@pytest.fixture
def engine(tmp_storage: FileStorage) -> Engine:
    return Engine(storage=tmp_storage)


class TestSpecLoading:
    def test_load_file_spec(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        assert result.spec.title
        assert len(result.spec.endpoints) > 0
        assert result.source_type == "file"

    def test_load_v2_spec(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v2.yaml"))
        assert len(result.spec.endpoints) > 0

    def test_classify_source(self) -> None:
        assert Engine.classify_source("https://example.com/api.json") == "url"
        assert Engine.classify_source("http://a/b") == "url"
        assert Engine.classify_source("/tmp/spec.yaml") == "file"
        assert Engine.classify_source("/home/u/.specs-agent/pasted/x.yaml") == "clipboard"


class TestPlanGenerationAndMerge:
    def test_generate_plan(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        assert isinstance(plan, TestPlan)
        assert len(plan.test_cases) > 0

    def test_generate_or_merge_no_saved(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan, merge = engine.generate_or_merge_plan(result.spec)
        assert merge is None
        assert len(plan.test_cases) > 0

    def test_generate_or_merge_with_saved(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan1 = engine.generate_plan(result.spec)

        # Simulate user edits on first test case
        edited = plan1.test_cases[0]
        edited.path_params = {"petId": "USER_EDITED"}
        edited.enabled = False
        plan1.auth_type = "bearer"
        plan1.auth_value = "secret-token"

        # Save + reload via engine
        engine.save_plan(plan1)

        # Regenerate — should find saved and merge
        plan2, merge = engine.generate_or_merge_plan(result.spec)
        assert merge is not None
        assert merge.kept > 0
        assert merge.new == 0  # same spec, nothing new
        assert merge.removed == 0

        # User intel preserved
        first = next(tc for tc in plan2.test_cases if tc.name == edited.name)
        assert first.path_params == {"petId": "USER_EDITED"}
        assert first.enabled is False
        assert plan2.auth_type == "bearer"
        assert plan2.auth_value == "secret-token"


class TestMergeBody:
    def test_fresh_none(self) -> None:
        assert _merge_body(None, {"a": 1}) == {"a": 1}

    def test_saved_none(self) -> None:
        assert _merge_body({"a": 1}, None) == {"a": 1}

    def test_overlay_preserves_new_fields(self) -> None:
        fresh = {"name": "", "email": "", "new_required_field": 0}
        saved = {"name": "Alice", "email": "a@x.com"}
        merged = _merge_body(fresh, saved)
        assert merged["name"] == "Alice"
        assert merged["email"] == "a@x.com"
        assert merged["new_required_field"] == 0  # new field kept from fresh

    def test_nested_dicts(self) -> None:
        fresh = {"user": {"name": "", "age": 0, "city": ""}}
        saved = {"user": {"name": "Bob", "age": 30}}
        merged = _merge_body(fresh, saved)
        assert merged["user"]["name"] == "Bob"
        assert merged["user"]["age"] == 30
        assert merged["user"]["city"] == ""  # new nested field from fresh

    def test_user_added_custom_field_kept(self) -> None:
        fresh = {"a": 1}
        saved = {"a": 2, "custom": "user-added"}
        merged = _merge_body(fresh, saved)
        assert merged["a"] == 2
        assert merged["custom"] == "user-added"

    def test_non_dict_prefers_saved(self) -> None:
        assert _merge_body("fresh-string", "saved-string") == "saved-string"
        assert _merge_body([1, 2], [3, 4]) == [3, 4]


class TestSpecsDiffer:
    def test_none_old_always_differs(self, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        assert engine.specs_differ(None, result.spec) is True

    def test_identical_specs(self, engine: Engine) -> None:
        r1 = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        r2 = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        assert engine.specs_differ(r1.spec, r2.spec) is False

    def test_different_specs(self, engine: Engine) -> None:
        r1 = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        r2 = engine.load_spec_from_source(str(FIXTURES / "petstore_v2.yaml"))
        assert engine.specs_differ(r1.spec, r2.spec) is True


class TestFileStoragePlanPersistence:
    def test_save_and_load_roundtrip(self, tmp_storage: FileStorage, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        plan.auth_type = "api_key"
        plan.auth_value = "xyz"

        saved_path = tmp_storage.save_plan(plan)
        assert Path(saved_path).exists()

        loaded = tmp_storage.load_plan_for_spec(plan.spec_title)
        assert loaded is not None
        assert loaded.auth_type == "api_key"
        assert loaded.auth_value == "xyz"
        assert len(loaded.test_cases) == len(plan.test_cases)

    def test_load_missing_returns_none(self, tmp_storage: FileStorage) -> None:
        assert tmp_storage.load_plan_for_spec("NonExistent Spec") is None

    def test_archive_plan(self, tmp_storage: FileStorage, engine: Engine) -> None:
        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)

        archive_path = tmp_storage.archive_plan(plan)
        assert archive_path
        assert Path(archive_path).exists()
        assert "archive" in archive_path


# ------------------------------------------------------------------ #
# Config methods (delegation)
# ------------------------------------------------------------------ #


class TestEngineConfig:
    def test_load_config_returns_app_config(self, engine: Engine) -> None:
        cfg = engine.load_config()
        assert isinstance(cfg, AppConfig)

    def test_record_recent_spec_updates_list(self, engine: Engine, monkeypatch) -> None:
        saved: list[AppConfig] = []
        monkeypatch.setattr(engine.storage, "save_config", lambda c: saved.append(c))

        cfg = AppConfig()
        engine.record_recent_spec(cfg, "/tmp/a.yaml", "Spec A")
        engine.record_recent_spec(cfg, "https://x/b.yaml", "Spec B")

        assert len(saved) == 2
        assert len(cfg.recent_specs) == 2
        # Newest first
        assert cfg.recent_specs[0].title == "Spec B"
        assert cfg.recent_specs[1].title == "Spec A"

    def test_save_config_roundtrip(self, tmp_storage: FileStorage, engine: Engine, monkeypatch) -> None:
        """save_config → load_config round-trips through the real file path."""
        from specs_agent import config as cfg_mod

        monkeypatch.setattr(cfg_mod, "get_config_dir", lambda: tmp_storage.root)
        monkeypatch.setattr(
            cfg_mod,
            "get_config_path",
            lambda: tmp_storage.root / "config.yaml",
        )

        cfg = AppConfig()
        cfg.base_url = "https://example.test"
        cfg.timeout_seconds = 42.0
        cfg.auth_presets = [AuthPreset(name="prod", type="bearer", header="Authorization", value="t")]
        engine.save_config(cfg)

        loaded = engine.load_config()
        assert loaded.base_url == "https://example.test"
        assert loaded.timeout_seconds == 42.0
        assert len(loaded.auth_presets) == 1
        assert loaded.auth_presets[0].name == "prod"


# ------------------------------------------------------------------ #
# History methods (delegation)
# ------------------------------------------------------------------ #


def _make_simple_report(spec_title: str = "Petstore") -> Report:
    return Report(
        plan_name=f"{spec_title} Test Plan",
        base_url="http://localhost:8080",
        spec_title=spec_title,
        started_at="2026-04-15T10:00:00+00:00",
        finished_at="2026-04-15T10:00:01+00:00",
        duration_seconds=1.0,
        functional_results=[
            TestResult(
                test_case_id="x",
                test_case_name="GET / → 200",
                endpoint="GET /",
                method="GET",
                status=TestStatus.PASSED,
                status_code=200,
                response_time_ms=10.0,
                assertion_results=[
                    AssertionResult(
                        assertion_type="status_code",
                        expected=200,
                        actual=200,
                        passed=True,
                    )
                ],
            )
        ],
        performance_results=[],
    )


class TestEngineHistory:
    def test_save_run_and_list(self, engine: Engine, monkeypatch, tmp_path: Path) -> None:
        from specs_agent.history import storage as hstore

        monkeypatch.setattr(hstore, "HISTORY_DIR", tmp_path / "hist")

        report = _make_simple_report()
        path = engine.save_run_to_history(report)
        assert Path(path).exists()

        runs = engine.list_history(report.spec_title, report.base_url)
        assert len(runs) == 1
        assert runs[0]["passed"] == 1

    def test_load_history_run(self, engine: Engine, monkeypatch, tmp_path: Path) -> None:
        from specs_agent.history import storage as hstore

        monkeypatch.setattr(hstore, "HISTORY_DIR", tmp_path / "hist")

        report = _make_simple_report()
        engine.save_run_to_history(report)
        runs = engine.list_history(report.spec_title, report.base_url)
        loaded = engine.load_history_run(report.spec_title, report.base_url, runs[0]["filename"])
        assert loaded is not None
        assert loaded.plan_name == report.plan_name

    def test_list_history_empty(self, engine: Engine, monkeypatch, tmp_path: Path) -> None:
        from specs_agent.history import storage as hstore

        monkeypatch.setattr(hstore, "HISTORY_DIR", tmp_path / "hist")
        assert engine.list_history("Nothing", "http://x") == []


# ------------------------------------------------------------------ #
# Error paths
# ------------------------------------------------------------------ #


class TestEngineErrorPaths:
    def test_load_spec_missing_file_raises(self, engine: Engine) -> None:
        with pytest.raises(SpecLoadError):
            engine.load_spec_from_source("/nonexistent/path/spec.yaml")

    def test_load_saved_plan_missing(self, engine: Engine) -> None:
        assert engine.load_saved_plan("Never Saved") is None

    def test_archive_plan_no_crash_on_failure(
        self, tmp_storage: FileStorage, engine: Engine, monkeypatch
    ) -> None:
        """If the underlying save_plan raises, archive returns '' (best-effort)."""
        from specs_agent import persistence

        def boom(plan, path):
            raise OSError("disk full")

        monkeypatch.setattr(
            "specs_agent.engine.storage.save_plan",
            boom,
        )

        result = engine.load_spec_from_source(str(FIXTURES / "petstore_v3.json"))
        plan = engine.generate_plan(result.spec)
        assert engine.archive_plan(plan) == ""


# ------------------------------------------------------------------ #
# FileStorage with custom root
# ------------------------------------------------------------------ #


class TestFileStorageCustomRoot:
    def test_default_root(self) -> None:
        fs = FileStorage()
        assert fs.root == Path.home() / ".specs-agent"

    def test_custom_root(self, tmp_path: Path) -> None:
        fs = FileStorage(root=tmp_path / "custom")
        assert fs.root == tmp_path / "custom"
        assert fs._plans_dir == tmp_path / "custom" / "plans"

    def test_plan_path_sanitizes_name(self, tmp_path: Path) -> None:
        fs = FileStorage(root=tmp_path)
        path = fs._plan_path("My Cool Plan!!")
        assert "my_cool" in str(path).lower()
        assert str(path).endswith(".yaml")
