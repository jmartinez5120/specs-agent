"""Unit tests for specs_agent.history.storage — save/list/load roundtrip."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from specs_agent.history import storage as hstore
from specs_agent.models.results import (
    AssertionResult,
    PerformanceMetrics,
    Report,
    TestResult,
    TestStatus,
)


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _make_test_result(
    name: str = "GET /things → 200",
    status: TestStatus = TestStatus.PASSED,
    status_code: int = 200,
) -> TestResult:
    return TestResult(
        test_case_id="tc-1",
        test_case_name=name,
        endpoint="GET /things",
        method="GET",
        status=status,
        status_code=status_code,
        response_time_ms=42.5,
        error_message="",
        assertion_results=[
            AssertionResult(
                assertion_type="status_code",
                expected=200,
                actual=status_code,
                passed=status == TestStatus.PASSED,
                message="ok",
            )
        ],
    )


def _make_perf_metric(
    endpoint: str = "/things", method: str = "GET",
) -> PerformanceMetrics:
    return PerformanceMetrics(
        endpoint=endpoint,
        method=method,
        total_requests=100,
        successful_requests=98,
        failed_requests=2,
        avg_latency_ms=12.3,
        p50_latency_ms=10.0,
        p95_latency_ms=25.0,
        p99_latency_ms=40.0,
        min_latency_ms=2.0,
        max_latency_ms=55.0,
        requests_per_second=50.0,
        error_rate_pct=2.0,
        sla_p95_ms=30.0,
        sla_p99_ms=50.0,
        sla_throughput_rps=40.0,
        sla_timeout_ms=60.0,
    )


def _make_report(
    spec_title: str = "Petstore",
    base_url: str = "http://localhost:8080",
    with_perf: bool = True,
) -> Report:
    return Report(
        plan_name="Petstore Test Plan",
        base_url=base_url,
        spec_title=spec_title,
        started_at="2026-04-15T10:00:00+00:00",
        finished_at="2026-04-15T10:00:05+00:00",
        duration_seconds=5.0,
        functional_results=[
            _make_test_result("GET /a → 200", TestStatus.PASSED),
            _make_test_result("GET /b → 404", TestStatus.FAILED, 500),
        ],
        performance_results=[_make_perf_metric()] if with_perf else [],
    )


@pytest.fixture
def patched_history_dir(tmp_path: Path, monkeypatch):
    """Redirect HISTORY_DIR to tmp for isolation."""
    monkeypatch.setattr(hstore, "HISTORY_DIR", tmp_path / "history")
    return tmp_path / "history"


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #


class TestSpecHash:
    def test_stable_hash_same_inputs(self) -> None:
        h1 = hstore._spec_hash("Petstore", "http://a")
        h2 = hstore._spec_hash("Petstore", "http://a")
        assert h1 == h2
        assert len(h1) == 12

    def test_different_inputs_differ(self) -> None:
        assert hstore._spec_hash("A", "http://x") != hstore._spec_hash("B", "http://x")
        assert hstore._spec_hash("A", "http://x") != hstore._spec_hash("A", "http://y")

    def test_spec_dir_includes_safe_name(self, patched_history_dir: Path) -> None:
        d = hstore._get_spec_dir("My Cool API!", "http://x")
        assert "my_cool_api!" in str(d).lower()


# ------------------------------------------------------------------ #
# save_run / list_runs / load_run
# ------------------------------------------------------------------ #


class TestSaveRun:
    def test_save_creates_file(self, patched_history_dir: Path) -> None:
        report = _make_report()
        path = hstore.save_run(report)
        assert Path(path).exists()
        data = json.loads(Path(path).read_text())
        assert data["plan_name"] == "Petstore Test Plan"
        assert len(data["functional_results"]) == 2
        assert len(data["performance_results"]) == 1

    def test_save_creates_index(self, patched_history_dir: Path) -> None:
        report = _make_report()
        hstore.save_run(report)

        spec_dir = hstore._get_spec_dir(report.spec_title, report.base_url)
        index_path = spec_dir / "index.json"
        assert index_path.exists()

        index = json.loads(index_path.read_text())
        assert index["spec_title"] == "Petstore"
        assert len(index["runs"]) == 1
        run = index["runs"][0]
        assert run["total"] == 2
        assert run["passed"] == 1
        assert run["failed"] == 1
        assert run["perf_requests"] == 100
        assert run["perf_p95_ms"] == 25.0

    def test_multiple_runs_prepended_newest_first(self, patched_history_dir: Path) -> None:
        r1 = _make_report()
        r1.started_at = "2026-04-15T10:00:00+00:00"
        r2 = _make_report()
        r2.started_at = "2026-04-15T11:00:00+00:00"

        hstore.save_run(r1)
        hstore.save_run(r2)

        runs = hstore.list_runs(r1.spec_title, r1.base_url)
        assert len(runs) == 2
        assert runs[0]["timestamp"] == "2026-04-15T11:00:00+00:00"
        assert runs[1]["timestamp"] == "2026-04-15T10:00:00+00:00"

    def test_index_capped_at_50(self, patched_history_dir: Path) -> None:
        report = _make_report()
        for i in range(55):
            report.started_at = f"2026-04-15T{i:02d}:00:00+00:00" if i < 24 else f"2026-04-16T{i-24:02d}:00:00+00:00"
            hstore.save_run(report)

        runs = hstore.list_runs(report.spec_title, report.base_url, limit=100)
        assert len(runs) == 50

    def test_save_with_no_performance(self, patched_history_dir: Path) -> None:
        report = _make_report(with_perf=False)
        hstore.save_run(report)
        runs = hstore.list_runs(report.spec_title, report.base_url)
        assert runs[0]["perf_requests"] == 0
        assert runs[0]["perf_avg_ms"] == 0


class TestListRuns:
    def test_empty_when_no_history(self, patched_history_dir: Path) -> None:
        assert hstore.list_runs("Unknown", "http://nowhere") == []

    def test_limit_applies(self, patched_history_dir: Path) -> None:
        report = _make_report()
        for i in range(5):
            report.started_at = f"2026-04-15T1{i}:00:00+00:00"
            hstore.save_run(report)
        assert len(hstore.list_runs(report.spec_title, report.base_url, limit=3)) == 3

    def test_corrupt_index_returns_empty(self, patched_history_dir: Path) -> None:
        report = _make_report()
        hstore.save_run(report)
        spec_dir = hstore._get_spec_dir(report.spec_title, report.base_url)
        (spec_dir / "index.json").write_text("not-json{")
        assert hstore.list_runs(report.spec_title, report.base_url) == []


class TestLoadRun:
    def test_roundtrip(self, patched_history_dir: Path) -> None:
        report = _make_report()
        hstore.save_run(report)
        runs = hstore.list_runs(report.spec_title, report.base_url)
        filename = runs[0]["filename"]

        loaded = hstore.load_run(report.spec_title, report.base_url, filename)
        assert loaded is not None
        assert loaded.plan_name == report.plan_name
        assert loaded.total_tests == 2
        assert loaded.passed_tests == 1
        assert loaded.failed_tests == 1

        # Perf SLAs survive round-trip
        pm = loaded.performance_results[0]
        assert pm.sla_p95_ms == 30.0
        assert pm.sla_p99_ms == 50.0
        assert pm.sla_throughput_rps == 40.0
        assert pm.sla_timeout_ms == 60.0

        # Assertion results round-trip
        fr = loaded.functional_results[0]
        assert fr.assertion_results[0].assertion_type == "status_code"
        assert fr.assertion_results[0].passed is True

    def test_missing_file_returns_none(self, patched_history_dir: Path) -> None:
        assert hstore.load_run("X", "http://x", "missing.json") is None

    def test_corrupt_file_returns_none(self, patched_history_dir: Path) -> None:
        report = _make_report()
        hstore.save_run(report)
        runs = hstore.list_runs(report.spec_title, report.base_url)
        filename = runs[0]["filename"]

        spec_dir = hstore._get_spec_dir(report.spec_title, report.base_url)
        (spec_dir / filename).write_text("{broken")

        assert hstore.load_run(report.spec_title, report.base_url, filename) is None


class TestDictRoundtrip:
    def test_roundtrip_preserves_status_enum(self) -> None:
        report = _make_report()
        data = hstore._report_to_dict(report)
        back = hstore._dict_to_report(data)
        assert back.functional_results[0].status == TestStatus.PASSED
        assert back.functional_results[1].status == TestStatus.FAILED

    def test_empty_report_roundtrip(self) -> None:
        empty = Report(
            plan_name="", base_url="", spec_title="",
            started_at="", finished_at="", duration_seconds=0,
        )
        data = hstore._report_to_dict(empty)
        back = hstore._dict_to_report(data)
        assert back.functional_results == []
        assert back.performance_results == []
