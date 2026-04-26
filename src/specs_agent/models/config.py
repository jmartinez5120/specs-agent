"""Execution configuration models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RampStage:
    """A single ramp-up stage: run at `users` concurrency for `duration_seconds`."""
    users: int = 10
    duration_seconds: int = 30


@dataclass
class PerformanceConfig:
    enabled: bool = False
    concurrent_users: int = 10
    duration_seconds: int = 30
    ramp_up_seconds: int = 0
    requests_per_second: float = 0.0  # 0 = unlimited (legacy, per-worker)
    target_tps: float = 0.0  # 0 = unlimited — overall target transactions/sec
    latency_p50_threshold_ms: float = 500.0
    latency_p95_threshold_ms: float = 2000.0
    latency_p99_threshold_ms: float = 5000.0
    error_rate_threshold_pct: float = 1.0
    target_endpoints: list[str] = field(default_factory=list)  # empty = all
    # Staged ramp-up: if non-empty, overrides concurrent_users + duration_seconds
    stages: list[RampStage] = field(default_factory=list)

    @property
    def total_duration(self) -> int:
        """Total duration across all stages (or single duration)."""
        if self.stages:
            return sum(s.duration_seconds for s in self.stages)
        return self.duration_seconds

    @property
    def max_users(self) -> int:
        """Peak concurrency across all stages."""
        if self.stages:
            return max(s.users for s in self.stages)
        return self.concurrent_users


@dataclass
class TokenFetchConfig:
    """Configuration for fetching a bearer token from an auth endpoint
    before (or during) a test run. When set, the executor calls the token
    URL and injects the result as the Authorization header — refreshing
    automatically as the token expires."""
    token_url: str = ""
    method: str = "POST"  # POST or GET
    headers: str = ""  # JSON object of extra headers
    integration_id_field: str = "client_id"
    integration_id_value: str = ""
    scope: str = ""  # space-separated
    extra_body: str = ""  # JSON blob merged with integration_id + scope
    token_response_path: str = "access_token"
    response_has_bearer_prefix: bool = False


@dataclass
class TestRunConfig:
    base_url: str = ""
    timeout_seconds: float = 30.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    retry_count: int = 0
    delay_between_ms: int = 0
    auth_type: str = "none"  # none, bearer, api_key, basic
    auth_value: str = ""
    auth_header: str = "Authorization"
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    token_fetch: TokenFetchConfig | None = None
