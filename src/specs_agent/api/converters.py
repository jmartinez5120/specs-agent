"""Converters between Pydantic DTOs and engine dataclasses.

These live outside the engine and the schemas module so both can remain
independent of each other. The engine doesn't know about Pydantic; the
schemas don't know about engine dataclasses.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from specs_agent.api import schemas as s
from specs_agent.config import AppConfig, AuthPreset, RecentSpec
from specs_agent.models.config import (
    PerformanceConfig,
    RampStage,
    TestRunConfig,
)
from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan


# ---------------------------------------------------------------------- #
# Engine → DTO (serialization)
# ---------------------------------------------------------------------- #


def plan_to_dto(plan: TestPlan) -> s.TestPlanDTO:
    from specs_agent.net import rewrite_for_display
    return s.TestPlanDTO(
        name=plan.name,
        spec_title=plan.spec_title,
        base_url=rewrite_for_display(plan.base_url),
        created_at=plan.created_at,
        test_cases=[testcase_to_dto(tc) for tc in plan.test_cases],
        global_headers=plan.global_headers,
        auth_type=plan.auth_type,
        auth_value=plan.auth_value,
        performance_slas=plan.performance_slas,
        global_variables=dict(getattr(plan, "global_variables", {}) or {}),
    )


def testcase_to_dto(tc: TestCase) -> s.TestCaseDTO:
    return s.TestCaseDTO(
        id=tc.id,
        endpoint_path=tc.endpoint_path,
        method=tc.method,
        name=tc.name,
        description=tc.description,
        enabled=tc.enabled,
        path_params=tc.path_params,
        query_params=tc.query_params,
        headers=tc.headers,
        body=tc.body,
        assertions=[s.AssertionDTO(
            type=a.type.value if hasattr(a.type, "value") else str(a.type),
            expected=a.expected,
            description=a.description,
        ) for a in tc.assertions],
        depends_on=tc.depends_on,
        needs_input=tc.needs_input,
        test_type=tc.test_type,
        ai_fields=tc.ai_fields,
        ai_generated=tc.ai_generated,
        ai_category=tc.ai_category,
        local_variables=dict(getattr(tc, "local_variables", {}) or {}),
    )


def mask_secret(value: str) -> str:
    """Mask an API key for safe display.

    Empty → empty. Short (≤8) → fixed mask. Otherwise: prefix + *** + last 4.
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    # Preserve a recognizable prefix (e.g. "sk-ant-", "sk-") if present.
    head = value[:6] if value.startswith("sk-") else value[:3]
    return f"{head}***{value[-4:]}"


def config_to_dto(cfg: AppConfig) -> s.AppConfigDTO:
    return s.AppConfigDTO(
        version=cfg.version,
        base_url=cfg.base_url,
        timeout_seconds=cfg.timeout_seconds,
        follow_redirects=cfg.follow_redirects,
        verify_ssl=cfg.verify_ssl,
        perf_concurrent_users=cfg.perf_concurrent_users,
        perf_duration_seconds=cfg.perf_duration_seconds,
        perf_ramp_up_seconds=cfg.perf_ramp_up_seconds,
        perf_latency_p95_threshold_ms=cfg.perf_latency_p95_threshold_ms,
        auth_presets=[s.AuthPresetDTO(**asdict(a)) for a in cfg.auth_presets],
        saved_auth_type=cfg.saved_auth_type,
        saved_auth_value=cfg.saved_auth_value,
        saved_auth_header=cfg.saved_auth_header,
        saved_token_fetch=dict(cfg.saved_token_fetch or {}),
        recent_specs=[s.RecentSpecDTO(**asdict(r)) for r in cfg.recent_specs],
        reports_output_dir=cfg.reports_output_dir,
        reports_format=cfg.reports_format,
        reports_open_after=cfg.reports_open_after,
        theme=cfg.theme,
        ai_enabled=cfg.ai_enabled,
        ai_model_size=cfg.ai_model_size,
        ai_model_path=cfg.ai_model_path,
        ai_n_ctx=cfg.ai_n_ctx,
        ai_n_gpu_layers=cfg.ai_n_gpu_layers,
        ai_cache_dir=cfg.ai_cache_dir,
        ai_backend=cfg.ai_backend,
        ai_http_base_url=cfg.ai_http_base_url,
        ai_http_model=cfg.ai_http_model,
        ai_http_api_key=mask_secret(cfg.ai_http_api_key),
        ai_provider=cfg.ai_provider,
        ai_anthropic_api_key=mask_secret(cfg.ai_anthropic_api_key),
        ai_anthropic_model=cfg.ai_anthropic_model,
        ai_openai_api_key=mask_secret(cfg.ai_openai_api_key),
        ai_openai_model=cfg.ai_openai_model,
        ai_openai_base_url=cfg.ai_openai_base_url,
    )


_API_KEY_FIELDS = (
    "ai_http_api_key",
    "ai_anthropic_api_key",
    "ai_openai_api_key",
)


def merge_config_preserving_secrets(
    incoming: AppConfig, existing: AppConfig
) -> AppConfig:
    """For each api_key field: empty string in `incoming` means leave unchanged."""
    for field_name in _API_KEY_FIELDS:
        if not getattr(incoming, field_name, ""):
            setattr(incoming, field_name, getattr(existing, field_name, ""))
    return incoming


# ---------------------------------------------------------------------- #
# DTO → Engine (deserialization)
# ---------------------------------------------------------------------- #


def dto_to_plan(dto: s.TestPlanDTO) -> TestPlan:
    return TestPlan(
        name=dto.name,
        spec_title=dto.spec_title,
        base_url=dto.base_url,
        created_at=dto.created_at,
        test_cases=[dto_to_testcase(tc) for tc in dto.test_cases],
        global_headers=dict(dto.global_headers),
        auth_type=dto.auth_type,
        auth_value=dto.auth_value,
        performance_slas=dict(dto.performance_slas),
        global_variables=dict(getattr(dto, "global_variables", {}) or {}),
    )


def dto_to_testcase(dto: s.TestCaseDTO) -> TestCase:
    return TestCase(
        id=dto.id or _new_id(),
        endpoint_path=dto.endpoint_path,
        method=dto.method,
        name=dto.name,
        description=dto.description,
        enabled=dto.enabled,
        path_params=dict(dto.path_params),
        query_params=dict(dto.query_params),
        headers=dict(dto.headers),
        body=dto.body,
        assertions=[_dto_to_assertion(a) for a in dto.assertions],
        depends_on=dto.depends_on,
        needs_input=dto.needs_input,
        test_type=dto.test_type,
        ai_fields=list(dto.ai_fields),
        ai_generated=dto.ai_generated,
        ai_category=dto.ai_category,
        local_variables=dict(getattr(dto, "local_variables", {}) or {}),
    )


def _dto_to_assertion(dto: s.AssertionDTO) -> Assertion:
    try:
        atype = AssertionType(dto.type)
    except ValueError:
        atype = AssertionType.STATUS_CODE
    return Assertion(type=atype, expected=dto.expected, description=dto.description)


def dto_to_config(dto: s.AppConfigDTO) -> AppConfig:
    return AppConfig(
        version=dto.version,
        base_url=dto.base_url,
        timeout_seconds=dto.timeout_seconds,
        follow_redirects=dto.follow_redirects,
        verify_ssl=dto.verify_ssl,
        perf_concurrent_users=dto.perf_concurrent_users,
        perf_duration_seconds=dto.perf_duration_seconds,
        perf_ramp_up_seconds=dto.perf_ramp_up_seconds,
        perf_latency_p95_threshold_ms=dto.perf_latency_p95_threshold_ms,
        auth_presets=[AuthPreset(**a.model_dump()) for a in dto.auth_presets],
        saved_auth_type=dto.saved_auth_type,
        saved_auth_value=dto.saved_auth_value,
        saved_auth_header=dto.saved_auth_header,
        saved_token_fetch=dict(dto.saved_token_fetch or {}),
        recent_specs=[RecentSpec(**r.model_dump()) for r in dto.recent_specs],
        reports_output_dir=dto.reports_output_dir,
        reports_format=dto.reports_format,
        reports_open_after=dto.reports_open_after,
        theme=dto.theme,
        ai_enabled=dto.ai_enabled,
        ai_model_size=dto.ai_model_size,
        ai_model_path=dto.ai_model_path,
        ai_n_ctx=dto.ai_n_ctx,
        ai_n_gpu_layers=dto.ai_n_gpu_layers,
        ai_cache_dir=dto.ai_cache_dir,
        ai_backend=dto.ai_backend,
        ai_http_base_url=dto.ai_http_base_url,
        ai_http_model=dto.ai_http_model,
        ai_http_api_key=dto.ai_http_api_key,
        ai_provider=dto.ai_provider,
        ai_anthropic_api_key=dto.ai_anthropic_api_key,
        ai_anthropic_model=dto.ai_anthropic_model,
        ai_openai_api_key=dto.ai_openai_api_key,
        ai_openai_model=dto.ai_openai_model,
        ai_openai_base_url=dto.ai_openai_base_url,
    )


def dto_to_run_config(dto: s.TestRunConfigDTO) -> TestRunConfig:
    from specs_agent.models.config import TokenFetchConfig
    tf = None
    if dto.token_fetch and dto.token_fetch.token_url:
        tf = TokenFetchConfig(
            token_url=dto.token_fetch.token_url,
            method=dto.token_fetch.method,
            headers=dto.token_fetch.headers,
            integration_id_field=dto.token_fetch.integration_id_field,
            integration_id_value=dto.token_fetch.integration_id_value,
            scope=dto.token_fetch.scope,
            extra_body=dto.token_fetch.extra_body,
            token_response_path=dto.token_fetch.token_response_path,
            response_has_bearer_prefix=dto.token_fetch.response_has_bearer_prefix,
        )
    return TestRunConfig(
        base_url=dto.base_url,
        timeout_seconds=dto.timeout_seconds,
        follow_redirects=dto.follow_redirects,
        verify_ssl=dto.verify_ssl,
        retry_count=dto.retry_count,
        delay_between_ms=dto.delay_between_ms,
        auth_type=dto.auth_type,
        auth_value=dto.auth_value,
        auth_header=dto.auth_header,
        token_fetch=tf,
        performance=PerformanceConfig(
            enabled=dto.performance.enabled,
            concurrent_users=dto.performance.concurrent_users,
            duration_seconds=dto.performance.duration_seconds,
            ramp_up_seconds=dto.performance.ramp_up_seconds,
            requests_per_second=dto.performance.requests_per_second,
            target_tps=dto.performance.target_tps,
            latency_p50_threshold_ms=dto.performance.latency_p50_threshold_ms,
            latency_p95_threshold_ms=dto.performance.latency_p95_threshold_ms,
            latency_p99_threshold_ms=dto.performance.latency_p99_threshold_ms,
            error_rate_threshold_pct=dto.performance.error_rate_threshold_pct,
            target_endpoints=list(dto.performance.target_endpoints),
            stages=[RampStage(users=st.users, duration_seconds=st.duration_seconds)
                    for st in dto.performance.stages],
        ),
    )


def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:8]
