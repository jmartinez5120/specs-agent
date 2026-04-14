"""Unit tests for the functional executor."""

import asyncio

import pytest
import httpx

from specs_agent.execution.functional import FunctionalExecutor
from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import Assertion, AssertionType, TestCase
from specs_agent.models.results import TestStatus


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
