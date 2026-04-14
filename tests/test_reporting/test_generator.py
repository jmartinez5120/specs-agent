"""Tests for report generation."""

from pathlib import Path

from specs_agent.models.results import (
    AssertionResult,
    PerformanceMetrics,
    Report,
    TestResult,
    TestStatus,
)
from specs_agent.reporting.generator import generate_html_report


def _make_report() -> Report:
    return Report(
        plan_name="Petstore Test Plan",
        base_url="https://petstore.example.com/v1",
        spec_title="Petstore",
        started_at="2026-04-09T00:00:00+00:00",
        finished_at="2026-04-09T00:00:05+00:00",
        duration_seconds=5.0,
        functional_results=[
            TestResult(
                test_case_id="tc1",
                test_case_name="GET /pets -> 200",
                endpoint="GET /pets",
                method="GET",
                status=TestStatus.PASSED,
                status_code=200,
                response_time_ms=150.0,
                assertion_results=[
                    AssertionResult("status_code", 200, 200, True),
                ],
            ),
            TestResult(
                test_case_id="tc2",
                test_case_name="GET /pets/{petId} -> 200",
                endpoint="GET /pets/{petId}",
                method="GET",
                status=TestStatus.FAILED,
                status_code=404,
                response_time_ms=120.0,
                assertion_results=[
                    AssertionResult("status_code", 200, 404, False, "Expected 200, got 404"),
                ],
            ),
            TestResult(
                test_case_id="tc3",
                test_case_name="POST /pets -> 201",
                endpoint="POST /pets",
                method="POST",
                status=TestStatus.ERROR,
                error_message="Connection refused",
            ),
        ],
        performance_results=[
            PerformanceMetrics(
                endpoint="/pets",
                method="GET",
                total_requests=100,
                successful_requests=95,
                failed_requests=5,
                avg_latency_ms=150.0,
                p50_latency_ms=120.0,
                p95_latency_ms=350.0,
                p99_latency_ms=500.0,
                min_latency_ms=50.0,
                max_latency_ms=600.0,
                requests_per_second=20.0,
                error_rate_pct=5.0,
            ),
        ],
    )


class TestHTMLReport:
    def test_generates_file(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "report.html")
        result = generate_html_report(report, path)
        assert Path(result).exists()

    def test_html_contains_plan_name(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "report.html")
        generate_html_report(report, path)
        html = Path(path).read_text()
        assert "Petstore Test Plan" in html

    def test_html_contains_results(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "report.html")
        generate_html_report(report, path)
        html = Path(path).read_text()
        assert "PASSED" in html
        assert "FAILED" in html
        assert "ERROR" in html

    def test_html_contains_endpoints(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "report.html")
        generate_html_report(report, path)
        html = Path(path).read_text()
        assert "GET /pets" in html
        assert "POST /pets" in html

    def test_html_contains_performance(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "report.html")
        generate_html_report(report, path)
        html = Path(path).read_text()
        assert "Performance" in html
        assert "p50" in html.lower() or "P50" in html or "120" in html

    def test_html_contains_pass_rate(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "report.html")
        generate_html_report(report, path)
        html = Path(path).read_text()
        assert "33%" in html  # 1/3 passed

    def test_creates_parent_dirs(self, tmp_path):
        report = _make_report()
        path = str(tmp_path / "nested" / "dir" / "report.html")
        result = generate_html_report(report, path)
        assert Path(result).exists()
