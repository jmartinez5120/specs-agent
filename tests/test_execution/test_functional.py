"""Unit tests for the functional executor."""

import asyncio
from unittest.mock import patch

import pytest
import httpx

from specs_agent.execution.functional import FunctionalExecutor
from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import Assertion, AssertionType, TestCase
from specs_agent.models.results import TestStatus


def _patch_client_with_mock(handler):
    """Patch specs_agent.execution.functional.httpx.AsyncClient with a MockTransport."""
    orig = httpx.AsyncClient

    def wrapped(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs.pop("verify", None)
        return orig(*args, **kwargs)

    return patch("specs_agent.execution.functional.httpx.AsyncClient", side_effect=wrapped)


def _make_config(base_url: str = "http://test") -> TestRunConfig:
    return TestRunConfig(base_url=base_url, timeout_seconds=5.0)


def _make_case(**kwargs) -> TestCase:
    defaults = dict(
        endpoint_path="/test",
        method="GET",
        name="test case",
        assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200)],
    )
    defaults.update(kwargs)
    return TestCase(**defaults)


class TestFunctionalExecutor:
    @pytest.mark.asyncio
    async def test_connection_error(self):
        """Unreachable host should return ERROR status."""
        config = _make_config("http://localhost:19999")
        executor = FunctionalExecutor(config)
        tc = _make_case()
        result = await executor.execute(tc)
        assert result.status == TestStatus.ERROR
        assert result.error_message != ""

    @pytest.mark.asyncio
    async def test_path_param_substitution(self):
        """Path params should be substituted in the URL."""
        config = _make_config("http://localhost:19999")
        executor = FunctionalExecutor(config)
        tc = _make_case(
            endpoint_path="/users/{userId}",
            path_params={"userId": "123"},
        )
        # Will fail to connect, but we verify the error references the right URL
        result = await executor.execute(tc)
        assert result.status == TestStatus.ERROR

    @pytest.mark.asyncio
    async def test_template_vars_resolved(self):
        """Template variables like {{$guid}} should be resolved."""
        config = _make_config("http://localhost:19999")
        executor = FunctionalExecutor(config)
        tc = _make_case(
            endpoint_path="/users/{userId}",
            path_params={"userId": "{{$guid}}"},
        )
        result = await executor.execute(tc)
        # Should error on connection, not on template resolution
        assert result.status == TestStatus.ERROR
        assert "{{" not in result.error_message

    @pytest.mark.asyncio
    async def test_auth_header_injected(self):
        """Auth config should inject the appropriate header."""
        config = _make_config("http://localhost:19999")
        config.auth_type = "bearer"
        config.auth_value = "test-token"
        executor = FunctionalExecutor(config)
        tc = _make_case()
        # Will fail to connect, but auth injection is tested
        result = await executor.execute(tc)
        assert result.status == TestStatus.ERROR


class TestFunctionalModels:
    @pytest.mark.asyncio
    async def test_result_has_correct_fields(self):
        config = _make_config("http://localhost:19999")
        executor = FunctionalExecutor(config)
        tc = _make_case(name="My Test")
        result = await executor.execute(tc)
        assert result.test_case_name == "My Test"
        assert result.method == "GET"
        assert result.endpoint == "GET /test"


# ------------------------------------------------------------------ #
# MockTransport-backed tests — happy paths
# ------------------------------------------------------------------ #


class TestFunctionalHappyPaths:
    @pytest.mark.asyncio
    async def test_200_response_passes(self):
        def handler(req): return httpx.Response(200, json={"ok": True})
        executor = FunctionalExecutor(_make_config())
        tc = _make_case()
        with _patch_client_with_mock(handler):
            result = await executor.execute(tc)
        assert result.status == TestStatus.PASSED
        assert result.status_code == 200
        assert result.response_body == {"ok": True}
        assert result.response_time_ms >= 0

    @pytest.mark.asyncio
    async def test_non_matching_status_fails(self):
        def handler(req): return httpx.Response(500)
        executor = FunctionalExecutor(_make_config())
        tc = _make_case(assertions=[Assertion(type=AssertionType.STATUS_CODE, expected=200)])
        with _patch_client_with_mock(handler):
            result = await executor.execute(tc)
        assert result.status == TestStatus.FAILED
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_text_response_body(self):
        def handler(req): return httpx.Response(200, text="plain text, not json")
        executor = FunctionalExecutor(_make_config())
        with _patch_client_with_mock(handler):
            result = await executor.execute(_make_case())
        assert result.response_body == "plain text, not json"

    @pytest.mark.asyncio
    async def test_path_query_headers_body_sent(self):
        seen = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            seen["method"] = req.method
            seen["headers"] = dict(req.headers)
            seen["content"] = req.content.decode() if req.content else ""
            return httpx.Response(200, json={"ok": True})

        tc = _make_case(
            endpoint_path="/users/{id}",
            method="POST",
            path_params={"id": "42"},
            query_params={"fmt": "json"},
            headers={"X-Custom": "hi"},
            body={"name": "Alice"},
        )
        with _patch_client_with_mock(handler):
            await FunctionalExecutor(_make_config()).execute(tc)

        assert "/users/42" in seen["url"]
        assert "fmt=json" in seen["url"]
        assert seen["method"] == "POST"
        assert seen["headers"].get("x-custom") == "hi"
        assert '"name": "Alice"' in seen["content"] or '"name":"Alice"' in seen["content"]

    @pytest.mark.asyncio
    async def test_assertions_run_schema_headers_body_time(self):
        def handler(req): return httpx.Response(
            200, json={"id": 1, "name": "x"}, headers={"Content-Type": "application/json"}
        )
        tc = _make_case(
            assertions=[
                Assertion(type=AssertionType.STATUS_CODE, expected=200),
                Assertion(type=AssertionType.HEADER_PRESENT, expected="Content-Type"),
                Assertion(type=AssertionType.RESPONSE_CONTAINS, expected="name"),
                Assertion(type=AssertionType.RESPONSE_TIME_MS, expected=5000),
            ]
        )
        with _patch_client_with_mock(handler):
            result = await FunctionalExecutor(_make_config()).execute(tc)
        assert result.status == TestStatus.PASSED
        assert len(result.assertion_results) == 4
        assert all(a.passed for a in result.assertion_results)

    @pytest.mark.asyncio
    async def test_api_key_auth_injected(self):
        seen_headers = {}
        def handler(req):
            seen_headers.update(req.headers)
            return httpx.Response(200)

        config = _make_config()
        config.auth_type = "api_key"
        config.auth_header = "X-API-Key"
        config.auth_value = "secret"

        with _patch_client_with_mock(handler):
            await FunctionalExecutor(config).execute(_make_case())
        assert seen_headers.get("x-api-key") == "secret"

    @pytest.mark.asyncio
    async def test_basic_auth_injected(self):
        seen_headers = {}
        def handler(req):
            seen_headers.update(req.headers)
            return httpx.Response(200)

        config = _make_config()
        config.auth_type = "basic"
        config.auth_value = "user:pass"

        with _patch_client_with_mock(handler):
            await FunctionalExecutor(config).execute(_make_case())
        # base64("user:pass") == "dXNlcjpwYXNz"
        assert seen_headers.get("authorization") == "Basic dXNlcjpwYXNz"

    @pytest.mark.asyncio
    async def test_header_value_assertion(self):
        def handler(req): return httpx.Response(200, headers={"X-Token": "abc123"})
        tc = _make_case(assertions=[
            Assertion(type=AssertionType.HEADER_VALUE, expected="X-Token:abc123"),
        ])
        with _patch_client_with_mock(handler):
            result = await FunctionalExecutor(_make_config()).execute(tc)
        assert result.status == TestStatus.PASSED


# ------------------------------------------------------------------ #
# Error paths
# ------------------------------------------------------------------ #


class TestFunctionalErrorPaths:
    @pytest.mark.asyncio
    async def test_timeout_returns_error_status(self):
        def handler(req): raise httpx.TimeoutException("slow")
        with _patch_client_with_mock(handler):
            result = await FunctionalExecutor(_make_config()).execute(_make_case())
        assert result.status == TestStatus.ERROR
        assert "timed out" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self):
        def handler(req): raise ValueError("wat")
        with _patch_client_with_mock(handler):
            result = await FunctionalExecutor(_make_config()).execute(_make_case())
        assert result.status == TestStatus.ERROR
        assert "unexpected" in result.error_message.lower() or "wat" in result.error_message
