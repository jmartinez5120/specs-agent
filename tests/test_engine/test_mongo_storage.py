"""Unit tests for MongoStorage (via mongomock).

These tests exercise every method of the `Storage` protocol through the
MongoDB backend. `mongomock` gives us a fully in-process Mongo that talks
the pymongo API, so no real server is needed.
"""

from __future__ import annotations

from pathlib import Path

import mongomock
import pytest

from specs_agent.config import AppConfig, AuthPreset
from specs_agent.engine.mongo_storage import (
    MongoStorage,
    _doc_to_plan,
    _plan_to_doc,
    _doc_to_config,
    _config_to_doc,
)
from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan
from specs_agent.models.results import (
    AssertionResult,
    PerformanceMetrics,
    Report,
    TestResult,
    TestStatus,
)


FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def storage() -> MongoStorage:
    """Fresh mongomock-backed storage for each test."""
    client = mongomock.MongoClient()
    return MongoStorage(database=client["test_db"])


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _make_plan(spec_title: str = "Petstore", **overrides) -> TestPlan:
    defaults = dict(
        name=f"{spec_title} Test Plan",
        spec_title=spec_title,
        base_url="http://localhost:8080",
        auth_type="bearer",
        auth_value="tok",
        global_headers={"X-Foo": "bar"},
        test_cases=[
            TestCase(
                id="tc1",
                endpoint_path="/pets/{id}",
                method="GET",
                name="GET /pets/1 → 200",
                path_params={"id": "1"},
                enabled=True,
                assertions=[
                    Assertion(type=AssertionType.STATUS_CODE, expected=200),
                    Assertion(type=AssertionType.RESPONSE_CONTAINS, expected="name"),
                ],
            ),
            TestCase(
                id="tc2",
                endpoint_path="/pets",
                method="POST",
                name="POST /pets → 201",
                body={"name": "rex"},
                enabled=False,
                test_type="happy",
                assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=201)],
            ),
        ],
    )
    defaults.update(overrides)
    return TestPlan(**defaults)


def _make_report(spec_title: str = "Petstore") -> Report:
    return Report(
        plan_name=f"{spec_title} Test Plan",
        base_url="http://localhost:8080",
        spec_title=spec_title,
        started_at="2026-04-15T10:00:00+00:00",
        finished_at="2026-04-15T10:00:05+00:00",
        duration_seconds=5.0,
        functional_results=[
            TestResult(
                test_case_id="tc1",
                test_case_name="GET /pets/1 → 200",
                endpoint="GET /pets/1",
                method="GET",
                status=TestStatus.PASSED,
                status_code=200,
                response_time_ms=42.0,
                assertion_results=[
                    AssertionResult("status_code", 200, 200, True, "ok"),
                ],
            ),
            TestResult(
                test_case_id="tc2",
                test_case_name="POST /pets → 201",
                endpoint="POST /pets",
                method="POST",
                status=TestStatus.FAILED,
                status_code=500,
                response_time_ms=110.0,
            ),
        ],
        performance_results=[
            PerformanceMetrics(
                endpoint="/pets",
                method="GET",
                total_requests=100,
                successful_requests=97,
                failed_requests=3,
                avg_latency_ms=15.0,
                p50_latency_ms=12.0,
                p95_latency_ms=30.0,
                p99_latency_ms=50.0,
                requests_per_second=40.0,
                error_rate_pct=3.0,
                sla_p95_ms=40.0,
                sla_p99_ms=80.0,
            ),
        ],
    )


# ====================================================================== #
# Config
# ====================================================================== #


class TestMongoConfig:
    def test_load_empty_returns_defaults(self, storage: MongoStorage) -> None:
        cfg = storage.load_config()
        assert isinstance(cfg, AppConfig)
        assert cfg.version == 1

    def test_save_and_load_roundtrip(self, storage: MongoStorage) -> None:
        cfg = AppConfig(
            base_url="https://api.example",
            timeout_seconds=42.0,
            theme="light",
            auth_presets=[
                AuthPreset(name="prod", type="bearer", header="Authorization", value="xx"),
                AuthPreset(name="staging", type="api_key", header="X-Key", value="yy"),
            ],
        )
        storage.save_config(cfg)

        loaded = storage.load_config()
        assert loaded.base_url == "https://api.example"
        assert loaded.timeout_seconds == 42.0
        assert loaded.theme == "light"
        assert len(loaded.auth_presets) == 2
        assert loaded.auth_presets[0].name == "prod"
        assert loaded.auth_presets[1].header == "X-Key"

    def test_save_is_idempotent(self, storage: MongoStorage) -> None:
        cfg = AppConfig(base_url="http://a")
        storage.save_config(cfg)
        storage.save_config(cfg)
        storage.save_config(cfg)

        # Only a single config doc should ever exist
        assert storage.configs.count_documents({}) == 1

    def test_config_update_overwrites(self, storage: MongoStorage) -> None:
        storage.save_config(AppConfig(base_url="v1"))
        storage.save_config(AppConfig(base_url="v2"))

        assert storage.load_config().base_url == "v2"


# ====================================================================== #
# Plans
# ====================================================================== #


class TestMongoPlans:
    def test_save_returns_mongo_uri(self, storage: MongoStorage) -> None:
        plan = _make_plan()
        uri = storage.save_plan(plan)
        assert uri.startswith("mongo://")
        assert "plans" in uri

    def test_save_and_load(self, storage: MongoStorage) -> None:
        plan = _make_plan()
        storage.save_plan(plan)

        loaded = storage.load_plan_for_spec("Petstore")
        assert loaded is not None
        assert loaded.name == plan.name
        assert loaded.auth_type == "bearer"
        assert loaded.auth_value == "tok"
        assert len(loaded.test_cases) == 2

    def test_load_missing_returns_none(self, storage: MongoStorage) -> None:
        assert storage.load_plan_for_spec("Never Saved") is None

    def test_save_overwrites_same_spec(self, storage: MongoStorage) -> None:
        p1 = _make_plan(auth_value="v1")
        p2 = _make_plan(auth_value="v2")
        storage.save_plan(p1)
        storage.save_plan(p2)

        # Only one plan doc per spec
        assert storage.plans.count_documents({}) == 1
        loaded = storage.load_plan_for_spec("Petstore")
        assert loaded.auth_value == "v2"

    def test_test_cases_roundtrip_fully(self, storage: MongoStorage) -> None:
        plan = _make_plan()
        storage.save_plan(plan)
        loaded = storage.load_plan_for_spec("Petstore")

        tc1 = loaded.test_cases[0]
        assert tc1.endpoint_path == "/pets/{id}"
        assert tc1.method == "GET"
        assert tc1.path_params == {"id": "1"}
        assert tc1.enabled is True
        assert len(tc1.assertions) == 2
        assert tc1.assertions[0].type == AssertionType.STATUS_CODE
        assert tc1.assertions[0].expected == 200
        assert tc1.assertions[1].type == AssertionType.RESPONSE_CONTAINS

        tc2 = loaded.test_cases[1]
        assert tc2.method == "POST"
        assert tc2.body == {"name": "rex"}
        assert tc2.enabled is False

    def test_archive_plan_inserts_new_doc(self, storage: MongoStorage) -> None:
        plan = _make_plan()
        uri1 = storage.archive_plan(plan)
        uri2 = storage.archive_plan(plan)

        assert uri1 != uri2  # different insertion ids
        assert storage.plan_archives.count_documents({}) == 2

    def test_multi_spec_isolation(self, storage: MongoStorage) -> None:
        p_a = _make_plan(spec_title="SpecA", auth_value="A")
        p_b = _make_plan(spec_title="SpecB", auth_value="B")
        storage.save_plan(p_a)
        storage.save_plan(p_b)

        assert storage.load_plan_for_spec("SpecA").auth_value == "A"
        assert storage.load_plan_for_spec("SpecB").auth_value == "B"


# ====================================================================== #
# History
# ====================================================================== #


class TestMongoHistory:
    def test_empty_returns_empty_list(self, storage: MongoStorage) -> None:
        assert storage.list_runs("Petstore", "http://x") == []

    def test_save_run_creates_docs(self, storage: MongoStorage) -> None:
        report = _make_report()
        uri = storage.save_run(report)

        assert uri.startswith("mongo://")
        assert storage.history.count_documents({}) == 1
        assert storage.history_index.count_documents({}) == 1

    def test_list_runs_returns_summary(self, storage: MongoStorage) -> None:
        report = _make_report()
        storage.save_run(report)

        runs = storage.list_runs(report.spec_title, report.base_url)
        assert len(runs) == 1
        r = runs[0]
        assert r["total"] == 2
        assert r["passed"] == 1
        assert r["failed"] == 1
        assert r["perf_requests"] == 100
        assert r["perf_p95_ms"] == 30.0

    def test_list_runs_newest_first_capped(self, storage: MongoStorage) -> None:
        report = _make_report()
        for i in range(55):
            report.started_at = f"2026-04-15T{i:02d}:00:00+00:00" if i < 24 else f"2026-04-16T{i-24:02d}:00:00+00:00"
            storage.save_run(report)

        runs = storage.list_runs(report.spec_title, report.base_url, limit=100)
        # Capped at 50 — mirrors file backend
        assert len(runs) == 50

    def test_list_runs_respects_limit(self, storage: MongoStorage) -> None:
        report = _make_report()
        for i in range(10):
            report.started_at = f"2026-04-15T{i:02d}:00:00+00:00"
            storage.save_run(report)

        assert len(storage.list_runs(report.spec_title, report.base_url, limit=3)) == 3

    def test_load_run_roundtrip(self, storage: MongoStorage) -> None:
        report = _make_report()
        storage.save_run(report)

        runs = storage.list_runs(report.spec_title, report.base_url)
        filename = runs[0]["filename"]

        loaded = storage.load_run(report.spec_title, report.base_url, filename)
        assert loaded is not None
        assert loaded.plan_name == report.plan_name
        assert loaded.total_tests == 2
        assert loaded.passed_tests == 1

        # Assertion results round-trip
        fr = loaded.functional_results[0]
        assert fr.assertion_results[0].assertion_type == "status_code"
        assert fr.assertion_results[0].passed is True

        # Perf SLAs round-trip
        pm = loaded.performance_results[0]
        assert pm.sla_p95_ms == 40.0
        assert pm.sla_p99_ms == 80.0

    def test_load_missing_run_returns_none(self, storage: MongoStorage) -> None:
        assert storage.load_run("X", "http://y", "missing.json") is None

    def test_two_specs_dont_collide_in_history(self, storage: MongoStorage) -> None:
        r_a = _make_report(spec_title="SpecA")
        r_b = _make_report(spec_title="SpecB")
        storage.save_run(r_a)
        storage.save_run(r_b)

        assert len(storage.list_runs("SpecA", r_a.base_url)) == 1
        assert len(storage.list_runs("SpecB", r_b.base_url)) == 1
        assert storage.history.count_documents({}) == 2


# ====================================================================== #
# Serializer helpers (direct unit tests)
# ====================================================================== #


class TestPlanDocSerializers:
    def test_plan_doc_roundtrip(self) -> None:
        plan = _make_plan()
        doc = _plan_to_doc(plan)
        back = _doc_to_plan(doc)
        assert back.name == plan.name
        assert back.auth_type == plan.auth_type
        assert len(back.test_cases) == len(plan.test_cases)

    def test_config_doc_roundtrip(self) -> None:
        cfg = AppConfig(base_url="http://x", theme="light", verify_ssl=False)
        doc = _config_to_doc(cfg)
        back = _doc_to_config(doc)
        assert back.base_url == "http://x"
        assert back.theme == "light"
        assert back.verify_ssl is False

    def test_invalid_assertion_type_falls_back(self) -> None:
        doc = {
            "name": "p", "spec_title": "s", "base_url": "",
            "test_cases": [{
                "id": "x", "endpoint_path": "/",
                "assertions": [{"type": "not_a_real_type", "expected": 1}],
            }],
        }
        back = _doc_to_plan(doc)
        # Falls back to STATUS_CODE instead of crashing
        assert back.test_cases[0].assertions[0].type == AssertionType.STATUS_CODE


# ====================================================================== #
# Factory (env-var driven)
# ====================================================================== #


class TestStorageFactory:
    def test_default_is_filestorage(self, monkeypatch) -> None:
        from specs_agent.engine import build_storage_from_env
        from specs_agent.engine.storage import FileStorage

        monkeypatch.delenv("SPECS_AGENT_STORAGE", raising=False)
        assert isinstance(build_storage_from_env(), FileStorage)

    def test_explicit_file(self, monkeypatch) -> None:
        from specs_agent.engine import build_storage_from_env
        from specs_agent.engine.storage import FileStorage

        monkeypatch.setenv("SPECS_AGENT_STORAGE", "file")
        assert isinstance(build_storage_from_env(), FileStorage)

    def test_file_respects_data_dir(self, monkeypatch, tmp_path: Path) -> None:
        from specs_agent.engine import build_storage_from_env

        monkeypatch.setenv("SPECS_AGENT_STORAGE", "file")
        monkeypatch.setenv("SPECS_AGENT_DATA_DIR", str(tmp_path))
        storage = build_storage_from_env()
        assert storage.root == tmp_path

    def test_mongo_selection(self, monkeypatch) -> None:
        """Mongo branch imports lazily — we don't connect, just assert the class."""
        from specs_agent.engine import build_storage_from_env
        from specs_agent.engine.mongo_storage import MongoStorage

        monkeypatch.setenv("SPECS_AGENT_STORAGE", "mongo")
        # MongoClient defers connection, so this is safe even without a running server
        storage = build_storage_from_env()
        assert isinstance(storage, MongoStorage)
