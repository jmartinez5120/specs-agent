"""Performance test executor -- concurrent load generation.

Uses HDR histograms for accurate percentile tracking, token bucket rate
limiting, and staged ramp-up for realistic load profiles.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Callable

import httpx
from hdrh.histogram import HdrHistogram

from specs_agent.models.config import PerformanceConfig, TestRunConfig
from specs_agent.models.plan import TestCase
from specs_agent.models.results import PerformanceMetrics
from specs_agent.templating.variables import resolve_value


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------

class _TokenBucket:
    """Async token bucket for precise TPS control across all workers."""

    def __init__(self, rate: float) -> None:
        """rate: tokens per second (0 = unlimited)."""
        self._rate = rate
        self._tokens = 0.0
        self._max_tokens = rate  # burst size = 1 second of tokens
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._rate <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._max_tokens, self._tokens + elapsed * self._rate)
            self._last = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            # Wait for next token
            wait = (1.0 - self._tokens) / self._rate
            self._tokens = 0.0

        await asyncio.sleep(wait)

    def update_rate(self, rate: float) -> None:
        """Adjust the rate (useful during staged ramp-up)."""
        self._rate = rate
        self._max_tokens = rate


# ---------------------------------------------------------------------------
# HDR Histogram helpers
# ---------------------------------------------------------------------------

def _new_histogram() -> HdrHistogram:
    """Create an HDR histogram: 1µs to 60s range, 3 significant digits."""
    return HdrHistogram(1, 60_000_000, 3)  # values in µs


def _record_latency(hist: HdrHistogram, ms: float) -> None:
    """Record a latency value in microseconds."""
    hist.record_value(int(ms * 1000))


def _percentile_ms(hist: HdrHistogram, pct: float) -> float:
    """Read a percentile from the histogram, return ms."""
    if hist.total_count == 0:
        return 0.0
    return hist.get_value_at_percentile(pct) / 1000.0


def _mean_ms(hist: HdrHistogram) -> float:
    if hist.total_count == 0:
        return 0.0
    return hist.get_mean_value() / 1000.0


def _min_ms(hist: HdrHistogram) -> float:
    if hist.total_count == 0:
        return 0.0
    return hist.get_min_value() / 1000.0


def _max_ms(hist: HdrHistogram) -> float:
    if hist.total_count == 0:
        return 0.0
    return hist.get_max_value() / 1000.0


# ---------------------------------------------------------------------------
# Performance executor
# ---------------------------------------------------------------------------

class PerformanceExecutor:
    """Fires concurrent requests and collects latency samples."""

    def __init__(self, config: TestRunConfig) -> None:
        from specs_agent.execution.token_fetch import TokenFetcher
        self.config = config
        self.perf = config.performance
        self._cancel = asyncio.Event()
        self._token_fetcher: TokenFetcher | None = None
        if config.token_fetch and config.token_fetch.token_url:
            self._token_fetcher = TokenFetcher(
                config.token_fetch,
                verify_ssl=config.verify_ssl,
                timeout_s=config.timeout_seconds,
            )

        # Per-endpoint HDR histograms + counters
        self._histograms: dict[str, HdrHistogram] = {}
        self._global_histogram = _new_histogram()
        self._errors: dict[str, int] = {}
        self._total: dict[str, int] = {}
        self._start_time: float = 0

        # Token bucket for TPS control
        self._bucket = _TokenBucket(self.perf.target_tps)

        # TPS tracking — per-second snapshots
        self._prev_total: int = 0
        self._prev_snapshot_time: float = 0
        self._window_tps: float = 0.0
        self._peak_tps: float = 0.0

        # Active worker tracking for staged ramp-up
        self._active_workers: int = 0

    def cancel(self) -> None:
        self._cancel.set()

    def get_live_stats(self) -> dict[str, Any]:
        """Get current live stats for progress reporting."""
        total_reqs = sum(self._total.values())
        total_errs = sum(self._errors.values())
        gh = self._global_histogram

        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        total_duration = self.perf.total_duration

        # Window TPS — requests completed since last snapshot
        now = time.monotonic()
        window_dt = now - self._prev_snapshot_time if self._prev_snapshot_time else 0
        if window_dt >= 0.5:
            delta_reqs = total_reqs - self._prev_total
            self._window_tps = delta_reqs / window_dt
            self._prev_total = total_reqs
            self._prev_snapshot_time = now
            if self._window_tps > self._peak_tps:
                self._peak_tps = self._window_tps

        return {
            "total_requests": total_reqs,
            "total_errors": total_errs,
            "error_rate": (total_errs / total_reqs * 100) if total_reqs else 0,
            "elapsed_seconds": elapsed,
            "duration_seconds": total_duration,
            "avg_tps": total_reqs / elapsed if elapsed > 0 else 0,
            "window_tps": self._window_tps,
            "peak_tps": self._peak_tps,
            "target_tps": self.perf.target_tps,
            "active_workers": self._active_workers,
            "avg_latency": _mean_ms(gh),
            "p50_latency": _percentile_ms(gh, 50),
            "p95_latency": _percentile_ms(gh, 95),
            "p99_latency": _percentile_ms(gh, 99),
            "per_endpoint": {
                key: {
                    "total": self._total.get(key, 0),
                    "errors": self._errors.get(key, 0),
                    "latencies": self._histograms[key].total_count if key in self._histograms else 0,
                }
                for key in self._total
            },
        }

    async def run(
        self,
        test_cases: list[TestCase],
        on_progress: Callable[[dict], None] | None = None,
    ) -> list[PerformanceMetrics]:
        """Run performance tests against the given test cases."""
        if not test_cases:
            return []

        from specs_agent.net import rewrite_localhost_for_docker
        base_url = rewrite_localhost_for_docker(self.config.base_url).rstrip("/")
        self._start_time = time.monotonic()
        self._prev_snapshot_time = self._start_time
        self._prev_total = 0

        # Initialize tracking
        for tc in test_cases:
            key = f"{tc.method} {tc.endpoint_path}"
            self._histograms[key] = _new_histogram()
            self._errors[key] = 0
            self._total[key] = 0

        start_time = time.monotonic()
        tasks: list[asyncio.Task] = []

        if self.perf.stages:
            # Staged ramp-up — the orchestrator manages worker count over time
            orchestrator = asyncio.create_task(
                self._staged_orchestrator(base_url, test_cases, start_time)
            )
            tasks.append(orchestrator)
        else:
            # Simple mode — fixed concurrency with optional linear ramp-up
            end_time = start_time + self.perf.duration_seconds
            for i in range(self.perf.concurrent_users):
                delay = (i / max(self.perf.concurrent_users, 1)) * self.perf.ramp_up_seconds
                task = asyncio.create_task(
                    self._worker(base_url, test_cases, end_time, delay)
                )
                tasks.append(task)

        # Progress reporter — fires every second
        total_duration = self.perf.total_duration
        end_time_report = start_time + total_duration
        if on_progress:
            reporter = asyncio.create_task(
                self._report_progress(end_time_report, on_progress)
            )
            tasks.append(reporter)

        # Wait for all
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION,
        )
        for t in pending:
            t.cancel()

        # Final progress update
        if on_progress:
            on_progress(self.get_live_stats())

        elapsed = time.monotonic() - start_time

        # Final snapshot for peak tracking
        self.get_live_stats()
        peak = self._peak_tps

        # Build metrics — one per unique method+endpoint
        results: list[PerformanceMetrics] = []
        seen_keys: set[str] = set()
        for tc in test_cases:
            key = f"{tc.method} {tc.endpoint_path}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            hist = self._histograms.get(key)
            total = self._total.get(key, 0)
            errors = self._errors.get(key, 0)

            if not hist or hist.total_count == 0:
                results.append(PerformanceMetrics(
                    endpoint=tc.endpoint_path, method=tc.method,
                    total_requests=total, failed_requests=errors,
                ))
                continue

            results.append(PerformanceMetrics(
                endpoint=tc.endpoint_path,
                method=tc.method,
                total_requests=total,
                successful_requests=total - errors,
                failed_requests=errors,
                avg_latency_ms=_mean_ms(hist),
                p50_latency_ms=_percentile_ms(hist, 50),
                p95_latency_ms=_percentile_ms(hist, 95),
                p99_latency_ms=_percentile_ms(hist, 99),
                min_latency_ms=_min_ms(hist),
                max_latency_ms=_max_ms(hist),
                requests_per_second=total / elapsed if elapsed > 0 else 0,
                peak_tps=peak,
                error_rate_pct=(errors / total * 100) if total > 0 else 0,
            ))

        return results

    # ------------------------------------------------------------------
    # Staged ramp-up orchestrator
    # ------------------------------------------------------------------

    async def _staged_orchestrator(
        self, base_url: str, test_cases: list[TestCase], start_time: float,
    ) -> None:
        """Manage worker count through multiple stages."""
        worker_tasks: list[asyncio.Task] = []
        worker_stop_events: list[asyncio.Event] = []
        current_users = 0

        for stage in self.perf.stages:
            if self._cancel.is_set():
                break

            target_users = stage.users
            stage_end = time.monotonic() + stage.duration_seconds

            # Scale up
            while current_users < target_users:
                stop = asyncio.Event()
                worker_stop_events.append(stop)
                task = asyncio.create_task(
                    self._stoppable_worker(base_url, test_cases, stop)
                )
                worker_tasks.append(task)
                current_users += 1
                self._active_workers = current_users

            # Scale down
            while current_users > target_users and worker_stop_events:
                stop = worker_stop_events.pop()
                stop.set()
                current_users -= 1
                self._active_workers = current_users

            # Wait for this stage's duration
            while time.monotonic() < stage_end and not self._cancel.is_set():
                await asyncio.sleep(0.5)

        # Stop all remaining workers
        for stop in worker_stop_events:
            stop.set()

        # Wait for workers to finish
        if worker_tasks:
            await asyncio.gather(*worker_tasks, return_exceptions=True)

    async def _stoppable_worker(
        self,
        base_url: str,
        test_cases: list[TestCase],
        stop: asyncio.Event,
    ) -> None:
        """Worker that runs until its stop event is set."""
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            follow_redirects=self.config.follow_redirects,
            verify=self.config.verify_ssl,
        ) as client:
            while not stop.is_set() and not self._cancel.is_set():
                await self._do_request(client, base_url, test_cases)

    # ------------------------------------------------------------------
    # Core request logic
    # ------------------------------------------------------------------

    async def _worker(
        self,
        base_url: str,
        test_cases: list[TestCase],
        end_time: float,
        delay: float,
    ) -> None:
        if delay > 0:
            await asyncio.sleep(delay)

        self._active_workers += 1
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=self.config.follow_redirects,
                verify=self.config.verify_ssl,
            ) as client:
                while time.monotonic() < end_time and not self._cancel.is_set():
                    await self._do_request(client, base_url, test_cases)
        finally:
            self._active_workers -= 1

    async def _do_request(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        test_cases: list[TestCase],
    ) -> None:
        """Execute a single request, record latency, apply rate limiting."""
        # Rate limit via token bucket
        await self._bucket.acquire()

        tc = random.choice(test_cases)
        key = f"{tc.method} {tc.endpoint_path}"

        path_params = resolve_value(dict(tc.path_params))
        query_params = resolve_value(dict(tc.query_params))
        body = resolve_value(tc.body) if tc.body else None

        path = tc.endpoint_path
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))
        url = f"{base_url}{path}"

        headers: dict[str, str] = {}
        if self._token_fetcher is not None:
            try:
                token = await self._token_fetcher.get_token()
                headers[self.config.auth_header or "Authorization"] = f"Bearer {token}"
            except Exception:
                # Count as an error and skip the request; latency isn't meaningful.
                self._errors[key] = self._errors.get(key, 0) + 1
                self._total[key] = self._total.get(key, 0) + 1
                return
        elif self.config.auth_type == "bearer" and self.config.auth_value:
            headers[self.config.auth_header] = f"Bearer {self.config.auth_value}"

        self._total[key] = self._total.get(key, 0) + 1

        start = time.monotonic()
        try:
            response = await client.request(
                method=tc.method,
                url=url,
                params=query_params or None,
                headers=headers or None,
                json=body if body and isinstance(body, (dict, list)) else None,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            _record_latency(self._histograms.setdefault(key, _new_histogram()), elapsed_ms)
            _record_latency(self._global_histogram, elapsed_ms)
            if response.status_code >= 400:
                self._errors[key] = self._errors.get(key, 0) + 1
        except Exception:
            self._errors[key] = self._errors.get(key, 0) + 1

    # ------------------------------------------------------------------
    # Progress reporting
    # ------------------------------------------------------------------

    async def _report_progress(
        self, end_time: float, on_progress: Callable[[dict], None]
    ) -> None:
        """Report live stats every second until done."""
        while time.monotonic() < end_time and not self._cancel.is_set():
            await asyncio.sleep(1.0)
            on_progress(self.get_live_stats())
