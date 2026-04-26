"""Unit tests for the test runner."""

import asyncio
from unittest.mock import patch

import httpx
import pytest

from specs_agent.execution.runner import TestRunner
from specs_agent.models.config import PerformanceConfig, TestRunConfig
from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan
from specs_agent.models.results import TestStatus


def _patch_functional_mock(handler):
    orig = httpx.AsyncClient
    def wrapped(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        kw.pop("verify", None)
        return orig(*a, **kw)
    return patch("specs_agent.execution.functional.httpx.AsyncClient", side_effect=wrapped)


def _patch_performance_mock(handler):
    orig = httpx.AsyncClient
    def wrapped(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        kw.pop("verify", None)
        return orig(*a, **kw)
    return patch("specs_agent.execution.performance.httpx.AsyncClient", side_effect=wrapped)


def _make_plan(cases=None) -> TestPlan:
    return TestPlan(
        name="Test Plan",
        spec_title="API",
        base_url="http://localhost:19999",
        test_cases=cases or [],
    )


def _make_case(enabled=True, **kwargs) -> TestCase:
    defaults = dict(
        endpoint_path="/test",
        method="GET",
        name="test",
        enabled=enabled,
        assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200)],
    )
    defaults.update(kwargs)
    return TestCase(**defaults)


class TestRunnerBasic:
    @pytest.mark.asyncio
    async def test_empty_plan(self):
        plan = _make_plan([])
        config = TestRunConfig()
        runner = TestRunner(plan, config)
        report = await runner.run()
        assert report.total_tests == 0
        assert report.plan_name == "Test Plan"

    @pytest.mark.asyncio
    async def test_disabled_cases_skipped(self):
        plan = _make_plan([
            _make_case(enabled=True),
            _make_case(enabled=False),
        ])
        config = TestRunConfig()
        runner = TestRunner(plan, config)
        report = await runner.run()
        # Only 1 enabled case should be executed
        assert report.total_tests == 1

    @pytest.mark.asyncio
    async def test_connection_errors_reported(self):
        plan = _make_plan([_make_case()])
        config = TestRunConfig(base_url="http://localhost:19999")
        runner = TestRunner(plan, config)
        report = await runner.run()
        assert report.total_tests == 1
        assert report.functional_results[0].status == TestStatus.ERROR

    @pytest.mark.asyncio
    async def test_callback_called(self):
        plan = _make_plan([_make_case()])
        config = TestRunConfig(base_url="http://localhost:19999")
        runner = TestRunner(plan, config)
        results_received = []
        report = await runner.run(on_result=lambda r: results_received.append(r))
        assert len(results_received) == 1

    @pytest.mark.asyncio
    async def test_cancel(self):
        cases = [_make_case(name=f"case_{i}") for i in range(5)]
        plan = _make_plan(cases)
        config = TestRunConfig(base_url="http://localhost:19999")
        runner = TestRunner(plan, config)

        count = 0
        def on_result(r):
            nonlocal count
            count += 1
            if count >= 2:
                runner.cancel()

        report = await runner.run(on_result=on_result)
        # Some should be skipped due to cancel
        skipped = [r for r in report.functional_results if r.status == TestStatus.SKIPPED]
        assert len(skipped) > 0

    @pytest.mark.asyncio
    async def test_report_metadata(self):
        plan = _make_plan([_make_case()])
        config = TestRunConfig(base_url="http://localhost:19999")
        runner = TestRunner(plan, config)
        report = await runner.run()
        assert report.spec_title == "API"
        assert report.base_url == "http://localhost:19999"
        assert report.started_at != ""
        assert report.finished_at != ""
        assert report.duration_seconds >= 0


class TestRunnerMocked:
    @pytest.mark.asyncio
    async def test_happy_path_all_pass(self):
        def handler(req): return httpx.Response(200, json={"ok": True})
        plan = _make_plan([
            _make_case(name="case 1"),
            _make_case(name="case 2"),
            _make_case(name="case 3"),
        ])
        config = TestRunConfig(base_url="http://mock")
        with _patch_functional_mock(handler):
            report = await TestRunner(plan, config).run()

        assert report.total_tests == 3
        assert report.passed_tests == 3
        assert report.failed_tests == 0
        assert report.pass_rate == 100.0

    @pytest.mark.asyncio
    async def test_mixed_results(self):
        calls = {"n": 0}
        def handler(req):
            calls["n"] += 1
            code = 200 if calls["n"] % 2 else 500
            return httpx.Response(code)
        plan = _make_plan([_make_case(name=f"c{i}") for i in range(4)])
        with _patch_functional_mock(handler):
            report = await TestRunner(plan, TestRunConfig(base_url="http://mock")).run()
        assert report.total_tests == 4
        assert report.passed_tests == 2
        assert report.failed_tests == 2

    @pytest.mark.asyncio
    async def test_on_progress_and_phase_callbacks(self):
        def handler(req): return httpx.Response(200)
        plan = _make_plan([_make_case(name=f"c{i}") for i in range(3)])
        progress = []
        phases = []
        with _patch_functional_mock(handler):
            await TestRunner(plan, TestRunConfig(base_url="http://mock")).run(
                on_progress=lambda i, t: progress.append((i, t)),
                on_phase=lambda p: phases.append(p),
            )
        assert progress == [(1, 3), (2, 3), (3, 3)]
        assert "functional" in phases
        assert "complete" in phases

    @pytest.mark.asyncio
    async def test_delay_between_tests_applied(self):
        import time

        def handler(req): return httpx.Response(200)
        plan = _make_plan([_make_case(name=f"c{i}") for i in range(3)])
        config = TestRunConfig(base_url="http://mock", delay_between_ms=100)

        with _patch_functional_mock(handler):
            start = time.monotonic()
            await TestRunner(plan, config).run()
            elapsed = time.monotonic() - start

        # 3 tests, 2 delays of 100ms = 200ms minimum
        assert elapsed >= 0.18  # allow some slack

    @pytest.mark.asyncio
    async def test_runner_uses_plan_base_url_when_config_has_none(self):
        def handler(req): return httpx.Response(200)
        plan = _make_plan([_make_case()])
        plan.base_url = "http://plan-url"
        config = TestRunConfig()  # no base_url

        with _patch_functional_mock(handler):
            runner = TestRunner(plan, config)
            assert config.base_url == "http://plan-url"  # copied in __init__

    @pytest.mark.asyncio
    async def test_performance_phase_runs_when_enabled(self):
        def handler(req): return httpx.Response(200)
        plan = _make_plan([_make_case()])
        plan.performance_slas = {
            "GET /test": {"p95_ms": 100, "p99_ms": 200, "throughput_rps": 50, "timeout_ms": 500}
        }

        config = TestRunConfig(base_url="http://mock")
        config.performance = PerformanceConfig(
            enabled=True, concurrent_users=1, duration_seconds=1,
            target_tps=100, ramp_up_seconds=0,
        )

        phases = []
        with _patch_functional_mock(handler), _patch_performance_mock(handler):
            report = await TestRunner(plan, config).run(on_phase=lambda p: phases.append(p))

        assert "performance" in phases
        assert len(report.performance_results) == 1
        pm = report.performance_results[0]
        # SLAs attached from plan
        assert pm.sla_p95_ms == 100
        assert pm.sla_p99_ms == 200
        assert pm.sla_throughput_rps == 50
        assert pm.sla_timeout_ms == 500

    @pytest.mark.asyncio
    async def test_performance_target_endpoints_filter(self):
        def handler(req): return httpx.Response(200)
        plan = _make_plan([
            _make_case(endpoint_path="/a", name="a"),
            _make_case(endpoint_path="/b", name="b"),
        ])
        config = TestRunConfig(base_url="http://mock")
        config.performance = PerformanceConfig(
            enabled=True, concurrent_users=1, duration_seconds=1,
            target_tps=50, ramp_up_seconds=0,
            target_endpoints=["/a"],  # only /a should get perf testing
        )

        with _patch_functional_mock(handler), _patch_performance_mock(handler):
            report = await TestRunner(plan, config).run()

        # Only /a should appear in perf results
        endpoints = {pm.endpoint for pm in report.performance_results}
        assert endpoints == {"/a"}
