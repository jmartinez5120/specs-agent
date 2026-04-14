"""Test runner -- orchestrates functional and performance test execution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import TestPlan
from specs_agent.models.results import PerformanceMetrics, Report, TestResult, TestStatus
from specs_agent.execution.functional import FunctionalExecutor
from specs_agent.execution.performance import PerformanceExecutor


class TestRunner:
    """Orchestrates a full test run: functional then optional performance."""

    def __init__(self, plan: TestPlan, config: TestRunConfig) -> None:
        self.plan = plan
        self.config = config
        if not self.config.base_url:
            self.config.base_url = plan.base_url
        self._cancel = asyncio.Event()

    def cancel(self) -> None:
        self._cancel.set()

    async def run(
        self,
        on_result: Callable[[TestResult], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_perf_update: Callable[[dict], None] | None = None,
        on_phase: Callable[[str], None] | None = None,
    ) -> Report:
        """Execute all enabled test cases.

        Args:
            on_result: Called after each functional test completes.
            on_progress: Called with (completed, total) counts.
            on_perf_update: Called periodically with live perf stats dict.
            on_phase: Called when phase changes ("functional", "performance", "complete").
        """
        started_at = datetime.now(timezone.utc)
        enabled = self.plan.enabled_cases
        total = len(enabled)
        functional_results: list[TestResult] = []

        # --- Functional phase ---
        if on_phase:
            on_phase("functional")

        executor = FunctionalExecutor(self.config)
        for i, test_case in enumerate(enabled):
            if self._cancel.is_set():
                functional_results.append(TestResult(
                    test_case_id=test_case.id,
                    test_case_name=test_case.name,
                    endpoint=f"{test_case.method} {test_case.endpoint_path}",
                    method=test_case.method,
                    status=TestStatus.SKIPPED,
                    error_message="Cancelled",
                ))
                continue

            result = await executor.execute(test_case)
            functional_results.append(result)

            if on_result:
                on_result(result)
            if on_progress:
                on_progress(i + 1, total)

            if self.config.delay_between_ms > 0 and i < total - 1:
                await asyncio.sleep(self.config.delay_between_ms / 1000)

        # --- Performance phase ---
        performance_results: list[PerformanceMetrics] = []
        if self.config.performance.enabled and not self._cancel.is_set():
            if on_phase:
                on_phase("performance")

            perf_cases = [
                tc for tc in enabled
                if not self.config.performance.target_endpoints
                or tc.endpoint_path in self.config.performance.target_endpoints
            ]
            if perf_cases:
                perf_executor = PerformanceExecutor(self.config)
                performance_results = await perf_executor.run(
                    perf_cases,
                    on_progress=on_perf_update,
                )
                # Attach SLAs from spec
                for pm in performance_results:
                    key = f"{pm.method} {pm.endpoint}"
                    sla = self.plan.performance_slas.get(key)
                    if sla:
                        pm.sla_p95_ms = sla.get("p95_ms")
                        pm.sla_p99_ms = sla.get("p99_ms")
                        pm.sla_throughput_rps = sla.get("throughput_rps")
                        pm.sla_timeout_ms = sla.get("timeout_ms")

        if on_phase:
            on_phase("complete")

        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()

        return Report(
            plan_name=self.plan.name,
            base_url=self.config.base_url,
            spec_title=self.plan.spec_title,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_seconds=duration,
            functional_results=functional_results,
            performance_results=performance_results,
        )
