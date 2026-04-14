"""End-to-end live test against http://localhost:8080 OpenAPI definition vv0.

Runs the full pipeline: load spec → extract → generate plan → execute functional
tests → execute performance tests → validate results.

Skip with: pytest -m "not live"
"""

import asyncio
import pytest

from specs_agent.parsing.loader import load_spec
from specs_agent.parsing.extractor import extract_spec
from specs_agent.parsing.plan_generator import generate_plan
from specs_agent.execution.functional import FunctionalExecutor
from specs_agent.execution.performance import PerformanceExecutor
from specs_agent.execution.runner import TestRunner
from specs_agent.models.config import PerformanceConfig, TestRunConfig
from specs_agent.models.results import TestStatus


BASE_URL = "http://localhost:8080"
SPEC_URL = f"{BASE_URL}/v3/api-docs"


@pytest.fixture(scope="module")
def spec():
    raw = load_spec(SPEC_URL)
    return extract_spec(raw, source_url=SPEC_URL)


@pytest.fixture(scope="module")
def plan(spec):
    return generate_plan(spec)


@pytest.fixture
def run_config():
    return TestRunConfig(
        base_url=BASE_URL,
        timeout_seconds=10.0,
        follow_redirects=True,
        verify_ssl=False,
    )


# ── Spec Parsing ────────────────────────────────────────────────────

class TestSpecParsing:
    def test_spec_loads(self, spec):
        assert spec.title == "OpenAPI definition"
        assert spec.version == "v0"

    def test_endpoints_extracted(self, spec):
        assert len(spec.endpoints) == 10
        methods = {f"{ep.method.value} {ep.path}" for ep in spec.endpoints}
        assert "PUT /api/missions/{id}/status" in methods
        assert "GET /api/missions" in methods
        assert "POST /api/missions" in methods
        assert "DELETE /api/missions/{id}" in methods

    def test_performance_sla_parsed(self, spec):
        put_status = [ep for ep in spec.endpoints if ep.path == "/api/missions/{id}/status"][0]
        assert put_status.performance_sla is not None
        assert put_status.performance_sla.latency_p99_ms == 180.0
        assert put_status.performance_sla.throughput_rps == 800.0

    def test_request_body_schema(self, spec):
        put_status = [ep for ep in spec.endpoints if ep.path == "/api/missions/{id}/status"][0]
        assert put_status.request_body_schema is not None
        props = put_status.request_body_schema.get("properties", {})
        assert "status" in props
        assert "enum" in props["status"]

    def test_tags_present(self, spec):
        assert len(spec.tags) >= 2


# ── Plan Generation ─────────────────────────────────────────────────

class TestPlanGeneration:
    def test_plan_created(self, plan):
        assert plan.name == "OpenAPI definition Test Plan"
        assert len(plan.test_cases) > 0

    def test_happy_path_cases_have_body(self, plan):
        """PUT/POST/PATCH happy path cases must include request body."""
        for tc in plan.test_cases:
            if tc.method in ("PUT", "POST", "PATCH") and "→ 2" in tc.name:
                assert tc.body is not None, f"Happy path {tc.name} missing request body"

    def test_all_cases_with_body_methods_have_body(self, plan):
        """Even non-2xx PUT/POST/PATCH should have body (server rejects without it)."""
        for tc in plan.test_cases:
            if tc.method in ("PUT", "POST", "PATCH") and tc.test_type == "happy":
                # Happy path for documented responses should have body
                if "trigger" not in tc.name:
                    assert tc.body is not None, f"{tc.name} missing body"

    def test_put_status_body_has_status_field(self, plan):
        """PUT /api/missions/{id}/status → 200 should have status in body."""
        case = next(
            (tc for tc in plan.test_cases
             if tc.name == "PUT /api/missions/{id}/status → 200"),
            None,
        )
        assert case is not None, "Missing happy path for PUT status"
        assert case.body is not None, "Body is None"
        assert "status" in case.body, f"Body missing 'status' field: {case.body}"

    def test_sad_path_cases_exist(self, plan):
        sad = [tc for tc in plan.test_cases if tc.test_type == "sad"]
        assert len(sad) > 0, "No sad path test cases generated"

    def test_sad_path_404_triggers_have_bad_id(self, plan):
        for tc in plan.test_cases:
            if "404 not found (trigger)" in tc.name:
                assert tc.test_type == "sad"
                # Should have a nonexistent ID
                if tc.path_params:
                    id_val = tc.path_params.get("id", "")
                    assert "nonexistent" in id_val or "999" in id_val

    def test_performance_slas_captured(self, plan):
        assert len(plan.performance_slas) > 0
        assert "PUT /api/missions/{id}/status" in plan.performance_slas


# ── Functional Execution ────────────────────────────────────────────

class TestFunctionalExecution:
    @pytest.mark.asyncio
    async def test_get_missions_passes(self, plan, run_config):
        """GET /api/missions → 200 should pass."""
        case = next(
            tc for tc in plan.test_cases
            if tc.name == "GET /api/missions → 200"
        )
        executor = FunctionalExecutor(run_config)
        result = await executor.execute(case)

        assert result.status_code == 200, f"Expected 200, got {result.status_code}"
        assert result.status == TestStatus.PASSED
        assert result.response_time_ms > 0
        assert result.request_url != ""

    @pytest.mark.asyncio
    async def test_post_mission_creates(self, plan, run_config):
        """POST /api/missions → 201 should create a mission."""
        case = next(
            (tc for tc in plan.test_cases
             if tc.name == "POST /api/missions → 201"),
            None,
        )
        if not case:
            pytest.skip("No POST missions → 201 test case")
        executor = FunctionalExecutor(run_config)
        result = await executor.execute(case)

        assert result.status_code in (200, 201), f"Expected 201, got {result.status_code}: {result.response_body}"
        assert result.response_body is not None

    @pytest.mark.asyncio
    async def test_put_status_with_body(self, plan, run_config):
        """PUT /api/missions/{id}/status → 200 should send body with status field."""
        case = next(
            (tc for tc in plan.test_cases
             if tc.name == "PUT /api/missions/{id}/status → 200"),
            None,
        )
        if not case:
            pytest.skip("No PUT status → 200 test case")

        executor = FunctionalExecutor(run_config)
        result = await executor.execute(case)

        # The request should have included a body
        assert result.request_body is not None, "Request body was not sent"
        assert result.status_code != 400 or "missing" not in str(result.response_body).lower(), \
            f"Server rejected with missing body: {result.response_body}"

    @pytest.mark.asyncio
    async def test_get_launchpads(self, plan, run_config):
        case = next(
            tc for tc in plan.test_cases
            if tc.name == "GET /api/launchpads → 200"
        )
        executor = FunctionalExecutor(run_config)
        result = await executor.execute(case)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_astronauts(self, plan, run_config):
        case = next(
            tc for tc in plan.test_cases
            if tc.name == "GET /api/astronauts → 200"
        )
        executor = FunctionalExecutor(run_config)
        result = await executor.execute(case)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_sad_path_404_returns_404_or_400(self, plan, run_config):
        """404 trigger tests should get 404 (or 400 if server validates body first)."""
        cases_404 = [tc for tc in plan.test_cases if "404 not found (trigger)" in tc.name]
        assert len(cases_404) > 0

        executor = FunctionalExecutor(run_config)
        for case in cases_404[:3]:
            result = await executor.execute(case)
            assert result.status_code in (400, 404), \
                f"{case.name}: expected 404 or 400, got {result.status_code}"

    @pytest.mark.asyncio
    async def test_all_enabled_cases_execute(self, plan, run_config):
        """All enabled test cases should execute without errors."""
        enabled = [tc for tc in plan.test_cases if tc.enabled]
        executor = FunctionalExecutor(run_config)

        errors = []
        for tc in enabled:
            result = await executor.execute(tc)
            if result.status == TestStatus.ERROR:
                errors.append(f"{tc.name}: {result.error_message}")

        assert len(errors) == 0, f"Execution errors:\n" + "\n".join(errors)


# ── Full Runner ─────────────────────────────────────────────────────

class TestFullRunner:
    @pytest.mark.asyncio
    async def test_runner_functional_only(self, plan, run_config):
        """Full runner with functional tests only."""
        runner = TestRunner(plan, run_config)
        results_collected = []

        report = await runner.run(
            on_result=lambda r: results_collected.append(r),
        )

        assert report is not None
        assert report.total_tests > 0
        assert report.total_tests == len(results_collected)
        # At least some should pass (GET endpoints)
        assert report.passed_tests > 0, f"No tests passed out of {report.total_tests}"

    @pytest.mark.asyncio
    async def test_runner_with_performance(self, plan):
        """Full runner with performance tests."""
        config = TestRunConfig(
            base_url=BASE_URL,
            timeout_seconds=10.0,
            verify_ssl=False,
            performance=PerformanceConfig(
                enabled=True,
                concurrent_users=3,
                duration_seconds=5,
                ramp_up_seconds=0,
                target_tps=0,
            ),
        )
        runner = TestRunner(plan, config)
        perf_stats = []

        report = await runner.run(
            on_perf_update=lambda s: perf_stats.append(s),
        )

        assert report is not None
        assert len(report.performance_results) > 0

        # Check perf metrics
        for pm in report.performance_results:
            assert pm.total_requests > 0, f"{pm.method} {pm.endpoint}: no requests"
            assert pm.avg_latency_ms > 0
            assert pm.p50_latency_ms > 0
            assert pm.p99_latency_ms >= pm.p50_latency_ms
            assert pm.requests_per_second > 0

        # Check live stats were reported
        assert len(perf_stats) > 0
        last_stat = perf_stats[-1]
        assert "window_tps" in last_stat
        assert "peak_tps" in last_stat
        assert last_stat["total_requests"] > 0


# ── Performance Executor Directly ───────────────────────────────────

class TestPerformanceExecutor:
    @pytest.mark.asyncio
    async def test_perf_with_tps_limit(self, plan):
        """Performance executor with TPS limit."""
        config = TestRunConfig(
            base_url=BASE_URL,
            timeout_seconds=10.0,
            verify_ssl=False,
            performance=PerformanceConfig(
                enabled=True,
                concurrent_users=2,
                duration_seconds=3,
                target_tps=10,
            ),
        )
        happy_gets = [tc for tc in plan.test_cases
                      if tc.enabled and tc.method == "GET" and "→ 200" in tc.name]

        executor = PerformanceExecutor(config)
        results = await executor.run(happy_gets[:2])

        total_reqs = sum(r.total_requests for r in results)
        # With 10 TPS limit over 3 seconds, should be roughly 30 requests
        assert total_reqs > 0
        assert total_reqs < 100, f"TPS limit not working: {total_reqs} requests in 3s"

    @pytest.mark.asyncio
    async def test_perf_no_duplicate_endpoints(self, plan):
        """Performance results should have one entry per unique endpoint."""
        config = TestRunConfig(
            base_url=BASE_URL,
            timeout_seconds=10.0,
            verify_ssl=False,
            performance=PerformanceConfig(
                enabled=True,
                concurrent_users=2,
                duration_seconds=2,
            ),
        )
        # Use all enabled cases (many share the same endpoint)
        enabled = [tc for tc in plan.test_cases if tc.enabled]

        executor = PerformanceExecutor(config)
        results = await executor.run(enabled)

        # Check no duplicates
        keys = [f"{r.method} {r.endpoint}" for r in results]
        assert len(keys) == len(set(keys)), f"Duplicate endpoints in results: {keys}"
