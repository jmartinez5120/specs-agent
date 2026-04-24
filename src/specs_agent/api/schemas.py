"""Pydantic DTOs for the HTTP API.

Request schemas validate client input. Response schemas mirror the engine's
dataclasses so the API contract is identical to the engine contract. We
keep these as thin Pydantic models rather than reusing the dataclasses
directly so validation errors surface at the API boundary rather than
leaking into the engine.

All request schemas that wrap engine dataclasses use Pydantic's `model_config`
with `from_attributes=True` so they accept either dict input (from JSON) or
dataclass instances (from internal code paths).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ======================================================================
# Request schemas — client → API
# ======================================================================


class LoadSpecRequest(BaseModel):
    source: str = Field(..., description="URL or file path to load the spec from")
    save: bool = Field(True, description="Persist the spec to storage. Set False for preview-only loads.")


# --- Plan / TestCase schemas (used in requests AND responses) ---


class AssertionDTO(BaseModel):
    type: str
    expected: Any = None
    description: str = ""


class TestCaseDTO(BaseModel):
    id: str = ""
    endpoint_path: str = ""
    method: str = "GET"
    name: str = ""
    description: str = ""
    enabled: bool = True
    path_params: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    assertions: list[AssertionDTO] = Field(default_factory=list)
    depends_on: str | None = None
    needs_input: bool = False
    test_type: str = "happy"
    ai_fields: list[str] = Field(default_factory=list)
    ai_generated: bool = False
    ai_category: str = ""
    local_variables: dict[str, Any] = Field(default_factory=dict)


class TestPlanDTO(BaseModel):
    name: str
    spec_title: str
    base_url: str
    created_at: str = ""
    test_cases: list[TestCaseDTO] = Field(default_factory=list)
    global_headers: dict[str, str] = Field(default_factory=dict)
    auth_type: str = "none"
    auth_value: str = ""
    performance_slas: dict[str, dict] = Field(default_factory=dict)
    global_variables: dict[str, Any] = Field(default_factory=dict)


class SpecPayload(BaseModel):
    """Minimal spec payload — the parsed spec dict.

    We pass `raw_spec` (the resolved OpenAPI dict) and let the engine
    re-extract. This avoids duplicating all ParsedSpec fields in Pydantic.
    """

    raw_spec: dict
    source: str = ""


class GeneratePlanRequest(BaseModel):
    spec: SpecPayload


class MergePlansRequest(BaseModel):
    fresh: TestPlanDTO
    saved: TestPlanDTO


class SavePlanRequest(BaseModel):
    plan: TestPlanDTO


# --- Config schemas ---


class AuthPresetDTO(BaseModel):
    name: str = ""
    type: str = "bearer"
    header: str = ""
    value: str = ""


class RecentSpecDTO(BaseModel):
    path: str = ""
    url: str = ""
    title: str = ""
    last_opened: str = ""


class AppConfigDTO(BaseModel):
    version: int = 1
    base_url: str = ""
    timeout_seconds: float = 30.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    perf_concurrent_users: int = 10
    perf_duration_seconds: int = 30
    perf_ramp_up_seconds: int = 5
    perf_latency_p95_threshold_ms: float = 2000.0
    auth_presets: list[AuthPresetDTO] = Field(default_factory=list)
    saved_auth_type: str = "none"
    saved_auth_value: str = ""
    saved_auth_header: str = "Authorization"
    saved_token_fetch: dict = Field(default_factory=dict)
    recent_specs: list[RecentSpecDTO] = Field(default_factory=list)
    reports_output_dir: str = "~/.specs-agent/reports"
    reports_format: str = "html"
    reports_open_after: bool = True
    theme: str = "dark"
    # AI scenario generation
    ai_enabled: bool = False
    ai_model_size: str = "medium"
    ai_model_path: str = ""
    ai_n_ctx: int = 2048
    ai_n_gpu_layers: int = 0
    ai_cache_dir: str = "~/.specs-agent/ai-cache"
    ai_backend: str = "auto"
    ai_http_base_url: str = ""
    ai_http_model: str = ""
    ai_http_api_key: str = ""
    # Provider abstraction (canonical going forward)
    ai_provider: str = "local_gguf"
    ai_anthropic_api_key: str = ""
    ai_anthropic_model: str = "claude-haiku-4-5"
    ai_openai_api_key: str = ""
    ai_openai_model: str = "gpt-4o-mini"
    ai_openai_base_url: str = ""


# --- Execution config ---


class RampStageDTO(BaseModel):
    users: int = 10
    duration_seconds: int = 30


class PerformanceConfigDTO(BaseModel):
    enabled: bool = False
    concurrent_users: int = 10
    duration_seconds: int = 30
    ramp_up_seconds: int = 0
    requests_per_second: float = 0.0
    target_tps: float = 0.0
    latency_p50_threshold_ms: float = 500.0
    latency_p95_threshold_ms: float = 2000.0
    latency_p99_threshold_ms: float = 5000.0
    error_rate_threshold_pct: float = 1.0
    target_endpoints: list[str] = Field(default_factory=list)
    stages: list[RampStageDTO] = Field(default_factory=list)


class TokenFetchConfigDTO(BaseModel):
    token_url: str = ""
    method: str = "POST"
    headers: str = ""
    integration_id_field: str = "client_id"
    integration_id_value: str = ""
    scope: str = ""
    extra_body: str = ""
    token_response_path: str = "access_token"
    response_has_bearer_prefix: bool = False


class TestRunConfigDTO(BaseModel):
    base_url: str = ""
    timeout_seconds: float = 30.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    retry_count: int = 0
    delay_between_ms: int = 0
    auth_type: str = "none"
    auth_value: str = ""
    auth_header: str = "Authorization"
    performance: PerformanceConfigDTO = Field(default_factory=PerformanceConfigDTO)
    token_fetch: TokenFetchConfigDTO | None = None


class ExecuteRequest(BaseModel):
    """Sent as the first WebSocket message to start a test run."""

    plan: TestPlanDTO
    config: TestRunConfigDTO


# --- History ---


class HistoryListQuery(BaseModel):
    spec_title: str
    base_url: str
    limit: int = 20


# --- Report ---


class RenderReportRequest(BaseModel):
    report: dict  # A serialized Report (free-form to avoid duplicating the schema)
    output_path: str = ""  # If empty, returns inline HTML
