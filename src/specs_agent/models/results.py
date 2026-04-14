"""Test result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class AssertionResult:
    assertion_type: str
    expected: Any
    actual: Any
    passed: bool
    message: str = ""


@dataclass
class TestResult:
    test_case_id: str
    test_case_name: str
    endpoint: str
    method: str
    status: TestStatus
    status_code: int | None = None
    response_time_ms: float = 0.0
    response_body: Any = None
    assertion_results: list[AssertionResult] = field(default_factory=list)
    error_message: str = ""
    test_type: str = "happy"  # "happy" or "sad"
    # Request details
    request_url: str = ""
    request_headers: dict = field(default_factory=dict)
    request_body: Any = None
    # Response details
    response_headers: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == TestStatus.PASSED


@dataclass
class SLACheck:
    """Result of checking a metric against an SLA threshold."""
    metric: str
    threshold: float
    actual: float
    unit: str
    passed: bool

    @property
    def message(self) -> str:
        op = "<=" if "latency" in self.metric or "timeout" in self.metric else ">="
        status = "OK" if self.passed else "BREACH"
        return f"{status}: {self.metric} {self.actual:.0f}{self.unit} (SLA: {op} {self.threshold:.0f}{self.unit})"


@dataclass
class PerformanceMetrics:
    endpoint: str
    method: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    requests_per_second: float = 0.0
    peak_tps: float = 0.0
    error_rate_pct: float = 0.0
    # SLA from x-performance
    sla_p95_ms: float | None = None
    sla_p99_ms: float | None = None
    sla_throughput_rps: float | None = None
    sla_timeout_ms: float | None = None

    @property
    def sla_checks(self) -> list[SLACheck]:
        """Check actual metrics against SLA thresholds."""
        checks: list[SLACheck] = []
        if self.sla_p95_ms is not None:
            checks.append(SLACheck("p95_latency", self.sla_p95_ms, self.p95_latency_ms, "ms",
                                   self.p95_latency_ms <= self.sla_p95_ms))
        if self.sla_p99_ms is not None:
            checks.append(SLACheck("p99_latency", self.sla_p99_ms, self.p99_latency_ms, "ms",
                                   self.p99_latency_ms <= self.sla_p99_ms))
        if self.sla_throughput_rps is not None:
            checks.append(SLACheck("throughput", self.sla_throughput_rps, self.requests_per_second, "tps",
                                   self.requests_per_second >= self.sla_throughput_rps))
        if self.sla_timeout_ms is not None:
            checks.append(SLACheck("max_latency", self.sla_timeout_ms, self.max_latency_ms, "ms",
                                   self.max_latency_ms <= self.sla_timeout_ms))
        return checks

    @property
    def sla_passed(self) -> bool:
        checks = self.sla_checks
        return all(c.passed for c in checks) if checks else True

    @property
    def has_sla(self) -> bool:
        return any(v is not None for v in [self.sla_p95_ms, self.sla_p99_ms, self.sla_throughput_rps, self.sla_timeout_ms])


@dataclass
class Report:
    plan_name: str
    base_url: str
    spec_title: str
    started_at: str
    finished_at: str
    duration_seconds: float
    functional_results: list[TestResult] = field(default_factory=list)
    performance_results: list[PerformanceMetrics] = field(default_factory=list)

    @property
    def total_tests(self) -> int:
        return len(self.functional_results)

    @property
    def passed_tests(self) -> int:
        return sum(1 for r in self.functional_results if r.passed)

    @property
    def failed_tests(self) -> int:
        return sum(1 for r in self.functional_results if r.status == TestStatus.FAILED)

    @property
    def error_tests(self) -> int:
        return sum(1 for r in self.functional_results if r.status == TestStatus.ERROR)

    @property
    def pass_rate(self) -> float:
        return (self.passed_tests / self.total_tests * 100) if self.total_tests else 0.0
