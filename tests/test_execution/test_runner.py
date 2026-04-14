"""Unit tests for the test runner."""

import asyncio

import pytest

from specs_agent.execution.runner import TestRunner
from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan
from specs_agent.models.results import TestStatus


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
