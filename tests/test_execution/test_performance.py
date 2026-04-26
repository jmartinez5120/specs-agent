"""Unit tests for specs_agent.execution.performance.

Covers:
- `_TokenBucket` rate limiter
- HDR histogram helpers (_new_histogram, _record_latency, _percentile_ms, _mean_ms, _min_ms, _max_ms)
- `PerformanceExecutor.get_live_stats` before/during a run
- `PerformanceExecutor.run` against a mocked `httpx` transport (simple mode)
- Endpoint deduplication — one PerformanceMetrics per unique (method, path)
- Empty test-case list
- Cancellation
- Staged ramp-up orchestration

Uses `httpx.MockTransport` to avoid needing a live HTTP server.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import httpx
import pytest

from specs_agent.execution import performance as perf_mod
from specs_agent.execution.performance import (
    PerformanceExecutor,
    _TokenBucket,
    _mean_ms,
    _max_ms,
    _min_ms,
    _new_histogram,
    _percentile_ms,
    _record_latency,
)
from specs_agent.models.config import PerformanceConfig, RampStage, TestRunConfig
from specs_agent.models.plan import Assertion, AssertionType, TestCase


# ------------------------------------------------------------------ #
# _TokenBucket
# ------------------------------------------------------------------ #


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_unlimited_rate_is_free(self) -> None:
        b = _TokenBucket(0)
        start = time.monotonic()
        for _ in range(100):
            await b.acquire()
        assert time.monotonic() - start < 0.1  # free-flowing

    @pytest.mark.asyncio
    async def test_rate_limits_acquires(self) -> None:
        b = _TokenBucket(50)  # 50 tokens/sec — 20ms per token
        start = time.monotonic()
        for _ in range(10):
            await b.acquire()
        # Should take ~ (10-burst)/50 seconds but bucket starts full at 50
        # so first burst is free. Just check it doesn't blow up.
        assert time.monotonic() - start < 1.0

    @pytest.mark.asyncio
    async def test_acquire_waits_when_empty(self) -> None:
        b = _TokenBucket(10)  # 10/s
        b._tokens = 0  # manually drain
        start = time.monotonic()
        await b.acquire()
        elapsed = time.monotonic() - start
        # Should wait approximately 0.1s (1 token at 10/s)
        assert 0.05 < elapsed < 0.3

    def test_update_rate(self) -> None:
        b = _TokenBucket(10)
        assert b._rate == 10
        b.update_rate(100)
        assert b._rate == 100
        assert b._max_tokens == 100


# ------------------------------------------------------------------ #
# HDR histogram helpers
# ------------------------------------------------------------------ #


class TestHistogramHelpers:
    def test_new_histogram_empty(self) -> None:
        h = _new_histogram()
        assert h.total_count == 0

    def test_record_and_read_percentiles(self) -> None:
        h = _new_histogram()
        for ms in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            _record_latency(h, ms)
        assert h.total_count == 10
        # Within HDR precision (3 digits)
        assert 40 <= _percentile_ms(h, 50) <= 60
        assert _percentile_ms(h, 99) >= 90

    def test_mean_min_max(self) -> None:
        h = _new_histogram()
        for ms in [10, 20, 30]:
            _record_latency(h, ms)
        assert 18 <= _mean_ms(h) <= 22
        assert 9 <= _min_ms(h) <= 11
        assert 28 <= _max_ms(h) <= 32

    def test_empty_histogram_returns_zero(self) -> None:
        h = _new_histogram()
        assert _percentile_ms(h, 95) == 0.0
        assert _mean_ms(h) == 0.0
        assert _min_ms(h) == 0.0
        assert _max_ms(h) == 0.0


# ------------------------------------------------------------------ #
# PerformanceExecutor — with MockTransport
# ------------------------------------------------------------------ #


def _make_cases(*paths: str) -> list[TestCase]:
    return [
        TestCase(
            endpoint_path=p,
            method="GET",
            name=f"GET {p}",
            assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200)],
        )
        for p in paths
    ]


def _make_config(
    duration: int = 1,
    users: int = 2,
    target_tps: float = 200.0,
    stages: list[RampStage] | None = None,
) -> TestRunConfig:
    """Build a perf config. Default target_tps=200 — non-zero so workers yield
    control back to the event loop between requests (critical when using a
    MockTransport that resolves instantly; otherwise the worker never awaits
    anything real and starves the test task)."""
    pc = PerformanceConfig(
        enabled=True,
        concurrent_users=users,
        duration_seconds=duration,
        ramp_up_seconds=0,
        target_tps=target_tps,
        stages=stages or [],
    )
    return TestRunConfig(base_url="http://mock", performance=pc, timeout_seconds=5.0)


def _patch_client_with_mock(mock_handler):
    """Patch httpx.AsyncClient so every instance uses MockTransport."""
    orig = httpx.AsyncClient

    def wrapped(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        kwargs.pop("verify", None)  # MockTransport doesn't use it
        return orig(*args, **kwargs)

    return patch("specs_agent.execution.performance.httpx.AsyncClient", side_effect=wrapped)


class TestPerformanceExecutor:
    @pytest.mark.asyncio
    async def test_empty_test_cases_returns_empty(self) -> None:
        ex = PerformanceExecutor(_make_config())
        results = await ex.run([])
        assert results == []

    @pytest.mark.asyncio
    async def test_simple_run_produces_metrics(self) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"ok": True})

        cases = _make_cases("/things")
        config = _make_config(duration=1, users=2)

        with _patch_client_with_mock(handler):
            ex = PerformanceExecutor(config)
            results = await ex.run(cases)

        assert len(results) == 1
        m = results[0]
        assert m.endpoint == "/things"
        assert m.method == "GET"
        assert m.total_requests > 0
        assert m.successful_requests == m.total_requests
        assert m.failed_requests == 0
        assert m.avg_latency_ms >= 0
        assert m.requests_per_second > 0
        assert calls["n"] == m.total_requests

    @pytest.mark.asyncio
    async def test_dedupe_by_method_and_endpoint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        # Two test cases with same method+path (e.g., happy + sad) — one metric expected
        cases = _make_cases("/things", "/things")
        config = _make_config(duration=1, users=1)

        with _patch_client_with_mock(handler):
            results = await PerformanceExecutor(config).run(cases)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_distinct_endpoints_distinct_metrics(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        cases = _make_cases("/a", "/b", "/c")
        config = _make_config(duration=1, users=2)

        with _patch_client_with_mock(handler):
            results = await PerformanceExecutor(config).run(cases)

        assert {m.endpoint for m in results} == {"/a", "/b", "/c"}

    @pytest.mark.asyncio
    async def test_errors_tracked(self) -> None:
        """All-failure path: failed_requests matches total, histogram stays empty."""
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        cases = _make_cases("/broken")
        config = _make_config(duration=1, users=1)

        with _patch_client_with_mock(handler):
            results = await PerformanceExecutor(config).run(cases)

        assert len(results) == 1
        m = results[0]
        # All requests failed — total counts error bumps, histogram is empty.
        assert m.total_requests > 0
        assert m.failed_requests == m.total_requests
        assert m.successful_requests == 0
        assert m.avg_latency_ms == 0.0  # no successful samples recorded

    @pytest.mark.asyncio
    async def test_progress_callback_invoked(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        updates: list[dict] = []

        cases = _make_cases("/x")
        config = _make_config(duration=1, users=1)

        with _patch_client_with_mock(handler):
            ex = PerformanceExecutor(config)
            await ex.run(cases, on_progress=lambda s: updates.append(s))

        assert updates, "on_progress should have been called at least once"
        last = updates[-1]
        assert "total_requests" in last
        assert "avg_tps" in last
        assert "p95_latency" in last

    @pytest.mark.asyncio
    async def test_cancel_stops_run(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        cases = _make_cases("/x")
        # Long duration, but cancelled early
        config = _make_config(duration=10, users=1)

        with _patch_client_with_mock(handler):
            ex = PerformanceExecutor(config)

            async def run_and_cancel():
                task = asyncio.create_task(ex.run(cases))
                await asyncio.sleep(0.1)
                ex.cancel()
                return await task

            start = time.monotonic()
            results = await asyncio.wait_for(run_and_cancel(), timeout=8.0)
            elapsed = time.monotonic() - start

        assert elapsed < 5.0  # cancelled well before 10s
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_bearer_auth_header_sent(self) -> None:
        seen_headers: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(dict(request.headers))
            return httpx.Response(200)

        config = _make_config(duration=1, users=1)
        config.auth_type = "bearer"
        config.auth_value = "t0k3n"

        with _patch_client_with_mock(handler):
            await PerformanceExecutor(config).run(_make_cases("/x"))

        assert seen_headers
        assert any(h.get("authorization") == "Bearer t0k3n" for h in seen_headers)

    @pytest.mark.asyncio
    async def test_live_stats_before_run(self) -> None:
        ex = PerformanceExecutor(_make_config())
        stats = ex.get_live_stats()
        assert stats["total_requests"] == 0
        assert stats["total_errors"] == 0
        assert stats["error_rate"] == 0
        assert stats["elapsed_seconds"] == 0

    @pytest.mark.asyncio
    async def test_path_param_substitution(self) -> None:
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            return httpx.Response(200)

        case = TestCase(
            endpoint_path="/users/{id}",
            method="GET",
            name="user",
            path_params={"id": "42"},
        )
        config = _make_config(duration=1, users=1)

        with _patch_client_with_mock(handler):
            await PerformanceExecutor(config).run([case])

        assert urls
        assert all("/users/42" in u for u in urls)


# ------------------------------------------------------------------ #
# Staged ramp-up
# ------------------------------------------------------------------ #


class TestStagedRampUp:
    @pytest.mark.asyncio
    async def test_staged_run_produces_metrics(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        config = _make_config(
            stages=[
                RampStage(users=2, duration_seconds=1),
                RampStage(users=4, duration_seconds=1),
                RampStage(users=1, duration_seconds=1),  # scale DOWN path
            ],
        )

        cases = _make_cases("/staged")

        with _patch_client_with_mock(handler):
            results = await PerformanceExecutor(config).run(cases)

        assert len(results) == 1
        assert results[0].total_requests > 0
