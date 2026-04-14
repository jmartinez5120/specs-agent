"""Response validators for test assertions."""

from __future__ import annotations

from typing import Any

import jsonschema

from specs_agent.models.results import AssertionResult


def validate_status_code(actual: int, expected: int) -> AssertionResult:
    return AssertionResult(
        assertion_type="status_code",
        expected=expected,
        actual=actual,
        passed=actual == expected,
        message="" if actual == expected else f"Expected {expected}, got {actual}",
    )


def validate_schema(body: Any, schema: dict) -> AssertionResult:
    """Validate a response body against a JSON schema."""
    if not schema or "$ref" in schema:
        return AssertionResult(
            assertion_type="response_schema",
            expected="schema",
            actual="skipped",
            passed=True,
            message="Schema contains unresolved $ref, skipping validation",
        )
    try:
        jsonschema.validate(instance=body, schema=schema)
        return AssertionResult(
            assertion_type="response_schema",
            expected="valid",
            actual="valid",
            passed=True,
        )
    except jsonschema.ValidationError as exc:
        return AssertionResult(
            assertion_type="response_schema",
            expected="valid",
            actual=str(exc.message)[:200],
            passed=False,
            message=str(exc.message)[:200],
        )


def validate_header_present(headers: dict, name: str) -> AssertionResult:
    # Case-insensitive header check
    found = any(k.lower() == name.lower() for k in headers)
    return AssertionResult(
        assertion_type="header_present",
        expected=name,
        actual="present" if found else "missing",
        passed=found,
        message="" if found else f"Header '{name}' not found",
    )


def validate_header_value(headers: dict, name: str, expected: str) -> AssertionResult:
    actual = None
    for k, v in headers.items():
        if k.lower() == name.lower():
            actual = v
            break
    passed = actual == expected
    return AssertionResult(
        assertion_type="header_value",
        expected=f"{name}: {expected}",
        actual=f"{name}: {actual}" if actual else f"{name}: missing",
        passed=passed,
        message="" if passed else f"Expected '{expected}', got '{actual}'",
    )


def validate_response_time(actual_ms: float, threshold_ms: float) -> AssertionResult:
    passed = actual_ms <= threshold_ms
    return AssertionResult(
        assertion_type="response_time_ms",
        expected=f"<= {threshold_ms}ms",
        actual=f"{actual_ms:.1f}ms",
        passed=passed,
        message="" if passed else f"Response took {actual_ms:.1f}ms, threshold is {threshold_ms}ms",
    )


def validate_body_contains(body: Any, expected: str) -> AssertionResult:
    body_str = str(body)
    passed = expected in body_str
    return AssertionResult(
        assertion_type="response_contains",
        expected=expected,
        actual=body_str[:200] if not passed else "contains",
        passed=passed,
        message="" if passed else f"Response body does not contain '{expected}'",
    )
