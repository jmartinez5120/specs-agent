"""Functional test executor -- sends HTTP requests and validates responses."""

from __future__ import annotations

import time
from typing import Any

import httpx

from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import AssertionType, TestCase
from specs_agent.models.results import AssertionResult, TestResult, TestStatus
from specs_agent.execution.token_fetch import TokenFetchError, TokenFetcher
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

    def __init__(self, config: TestRunConfig, token_fetcher: TokenFetcher | None = None) -> None:
        self.config = config
        self._token_fetcher = token_fetcher
        if token_fetcher is None and config.token_fetch and config.token_fetch.token_url:
            self._token_fetcher = TokenFetcher(
                config.token_fetch,
                verify_ssl=config.verify_ssl,
                timeout_s=config.timeout_seconds,
            )

    async def execute(
        self,
        test_case: TestCase,
        global_variables: dict[str, Any] | None = None,
    ) -> TestResult:
        """Execute a single test case and return the result.

        `global_variables` is the plan's plan-wide user variables. They are
        merged with the test case's `local_variables` (local wins on key
        conflict) and passed to the templating resolver.
        """
        from specs_agent.net import rewrite_localhost_for_docker
        base_url = rewrite_localhost_for_docker(self.config.base_url).rstrip("/")

        # Merge plan-wide + per-case user variables (local overrides global).
        user_vars: dict[str, Any] = {}
        if global_variables:
            user_vars.update(global_variables)
        if getattr(test_case, "local_variables", None):
            user_vars.update(test_case.local_variables)

        # Resolve template variables in all dynamic fields
        path_params = resolve_value(dict(test_case.path_params), user_vars)
        query_params = resolve_value(dict(test_case.query_params), user_vars)
        headers = resolve_value(dict(test_case.headers), user_vars)
        body = resolve_value(test_case.body, user_vars) if test_case.body else None

        # Build URL with path params
        path = test_case.endpoint_path
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))
        url = f"{base_url}{path}"

        # Merge headers (await token fetch if configured)
        all_headers = dict(headers)
        try:
            await self._inject_auth(all_headers)
        except TokenFetchError as exc:
            return TestResult(
                test_case_id=test_case.id,
                test_case_name=test_case.name,
                endpoint=f"{test_case.method} {test_case.endpoint_path}",
                method=test_case.method,
                status=TestStatus.ERROR,
                test_type=test_case.test_type,
                error_message=f"Auth token fetch failed: {exc}",
            )

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

    async def _inject_auth(self, headers: dict) -> None:
        # Runtime-fetched bearer token takes precedence over a static auth_value.
        if self._token_fetcher is not None:
            token = await self._token_fetcher.get_token()
            header_name = self.config.auth_header or "Authorization"
            headers[header_name] = f"Bearer {token}"
            return
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
