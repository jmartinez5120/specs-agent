"""Functional test executor -- sends HTTP requests and validates responses."""

from __future__ import annotations

import time
from typing import Any

import httpx

from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import AssertionType, TestCase
from specs_agent.models.results import AssertionResult, TestResult, TestStatus
from specs_agent.execution.validators import (
    validate_body_contains,
    validate_header_present,
    validate_header_value,
    validate_response_time,
    validate_schema,
    validate_status_code,
)
from specs_agent.templating.variables import resolve_value


class FunctionalExecutor:
    """Executes individual test cases via httpx."""

    def __init__(self, config: TestRunConfig) -> None:
        self.config = config

    async def execute(self, test_case: TestCase) -> TestResult:
        """Execute a single test case and return the result."""
        base_url = self.config.base_url.rstrip("/")

        # Resolve template variables in all dynamic fields
        path_params = resolve_value(dict(test_case.path_params))
        query_params = resolve_value(dict(test_case.query_params))
        headers = resolve_value(dict(test_case.headers))
        body = resolve_value(test_case.body) if test_case.body else None

        # Build URL with path params
        path = test_case.endpoint_path
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))
        url = f"{base_url}{path}"

        # Merge headers
        all_headers = dict(headers)
        self._inject_auth(all_headers)

        # Execute request
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self.config.timeout_seconds,
                follow_redirects=self.config.follow_redirects,
                verify=self.config.verify_ssl,
            ) as client:
                response = await client.request(
                    method=test_case.method,
                    url=url,
                    params=query_params or None,
                    headers=all_headers or None,
                    json=body if body and isinstance(body, (dict, list)) else None,
                    content=str(body).encode() if body and not isinstance(body, (dict, list)) else None,
                )
            elapsed_ms = (time.monotonic() - start) * 1000

            # Parse response body
            try:
                resp_body = response.json()
            except Exception:
                resp_body = response.text

            # Run assertions
            assertion_results = self._run_assertions(
                test_case, response.status_code, elapsed_ms,
                dict(response.headers), resp_body,
            )
            all_passed = all(ar.passed for ar in assertion_results)

            return TestResult(
                test_case_id=test_case.id,
                test_case_name=test_case.name,
                endpoint=f"{test_case.method} {test_case.endpoint_path}",
                method=test_case.method,
                status=TestStatus.PASSED if all_passed else TestStatus.FAILED,
                test_type=test_case.test_type,
                status_code=response.status_code,
                response_time_ms=elapsed_ms,
                response_body=resp_body,
                assertion_results=assertion_results,
                request_url=url,
                request_headers=dict(all_headers),
                request_body=body,
                response_headers=dict(response.headers),
            )

        except httpx.TimeoutException:
            elapsed_ms = (time.monotonic() - start) * 1000
            return TestResult(
                test_case_id=test_case.id,
                test_case_name=test_case.name,
                endpoint=f"{test_case.method} {test_case.endpoint_path}",
                method=test_case.method,
                status=TestStatus.ERROR,
                test_type=test_case.test_type,
                response_time_ms=elapsed_ms,
                error_message=f"Request timed out after {self.config.timeout_seconds}s",
            )
        except httpx.ConnectError as exc:
            return TestResult(
                test_case_id=test_case.id,
                test_case_name=test_case.name,
                endpoint=f"{test_case.method} {test_case.endpoint_path}",
                method=test_case.method,
                status=TestStatus.ERROR,
                test_type=test_case.test_type,
                error_message=f"Connection failed: {exc}",
            )
        except Exception as exc:
            return TestResult(
                test_case_id=test_case.id,
                test_case_name=test_case.name,
                endpoint=f"{test_case.method} {test_case.endpoint_path}",
                method=test_case.method,
                status=TestStatus.ERROR,
                test_type=test_case.test_type,
                error_message=f"Unexpected error: {exc}",
            )

    def _inject_auth(self, headers: dict) -> None:
        if self.config.auth_type == "bearer" and self.config.auth_value:
            headers[self.config.auth_header] = f"Bearer {self.config.auth_value}"
        elif self.config.auth_type == "api_key" and self.config.auth_value:
            headers[self.config.auth_header] = self.config.auth_value
        elif self.config.auth_type == "basic" and self.config.auth_value:
            import base64
            headers[self.config.auth_header] = f"Basic {base64.b64encode(self.config.auth_value.encode()).decode()}"

    def _run_assertions(
        self,
        test_case: TestCase,
        status_code: int,
        elapsed_ms: float,
        headers: dict,
        body: Any,
    ) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        for assertion in test_case.assertions:
            match assertion.type:
                case AssertionType.STATUS_CODE:
                    results.append(validate_status_code(status_code, assertion.expected))
                case AssertionType.RESPONSE_SCHEMA:
                    results.append(validate_schema(body, assertion.expected))
                case AssertionType.RESPONSE_CONTAINS:
                    results.append(validate_body_contains(body, assertion.expected))
                case AssertionType.HEADER_PRESENT:
                    results.append(validate_header_present(headers, assertion.expected))
                case AssertionType.HEADER_VALUE:
                    name, _, value = str(assertion.expected).partition(":")
                    results.append(validate_header_value(headers, name.strip(), value.strip()))
                case AssertionType.RESPONSE_TIME_MS:
                    results.append(validate_response_time(elapsed_ms, assertion.expected))
        return results
