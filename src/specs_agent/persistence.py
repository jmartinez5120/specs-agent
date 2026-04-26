"""Save and load test plans to/from YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan


def save_plan(plan: TestPlan, path: str) -> str:
    """Serialize a TestPlan to a YAML file.

    Returns the output path.
    """
    data = {
        "name": plan.name,
        "spec_title": plan.spec_title,
        "base_url": plan.base_url,
        "created_at": plan.created_at,
        "auth_type": plan.auth_type,
        "auth_value": plan.auth_value,
        "global_headers": plan.global_headers,
        "global_variables": dict(getattr(plan, "global_variables", {}) or {}),
        "test_cases": [_case_to_dict(tc) for tc in plan.test_cases],
    }
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    return str(out)


def load_plan(path: str) -> TestPlan:
    """Deserialize a TestPlan from a YAML file."""
    text = Path(path).expanduser().read_text()
    data = yaml.safe_load(text)
    return _plan_from_dict(data)


def _case_to_dict(tc: TestCase) -> dict:
    return {
        "id": tc.id,
        "endpoint_path": tc.endpoint_path,
        "method": tc.method,
        "name": tc.name,
        "description": tc.description,
        "enabled": tc.enabled,
        "path_params": tc.path_params,
        "query_params": tc.query_params,
        "headers": tc.headers,
        "body": tc.body,
        "needs_input": tc.needs_input,
        "test_type": tc.test_type,
        "depends_on": tc.depends_on,
        "ai_fields": tc.ai_fields,
        "ai_generated": tc.ai_generated,
        "ai_category": tc.ai_category,
        "local_variables": dict(getattr(tc, "local_variables", {}) or {}),
        "assertions": [
            {"type": a.type.value, "expected": a.expected, "description": a.description}
            for a in tc.assertions
        ],
    }


def _plan_from_dict(data: dict) -> TestPlan:
    test_cases = [_case_from_dict(tc) for tc in data.get("test_cases", [])]
    return TestPlan(
        name=data.get("name", "Loaded Plan"),
        spec_title=data.get("spec_title", ""),
        base_url=data.get("base_url", ""),
        created_at=data.get("created_at", ""),
        auth_type=data.get("auth_type", "none"),
        auth_value=data.get("auth_value", ""),
        global_headers=data.get("global_headers", {}),
        global_variables=data.get("global_variables", {}) or {},
        test_cases=test_cases,
    )


def _case_from_dict(data: dict) -> TestCase:
    assertions = []
    for a in data.get("assertions", []):
        try:
            atype = AssertionType(a.get("type", "status_code"))
        except ValueError:
            atype = AssertionType.STATUS_CODE
        assertions.append(Assertion(
            type=atype,
            expected=a.get("expected"),
            description=a.get("description", ""),
        ))

    return TestCase(
        id=data.get("id", ""),
        endpoint_path=data.get("endpoint_path", ""),
        method=data.get("method", "GET"),
        name=data.get("name", ""),
        description=data.get("description", ""),
        enabled=data.get("enabled", True),
        path_params=data.get("path_params", {}),
        query_params=data.get("query_params", {}),
        headers=data.get("headers", {}),
        body=data.get("body"),
        needs_input=data.get("needs_input", False),
        test_type=data.get("test_type", "happy"),
        depends_on=data.get("depends_on"),
        assertions=assertions,
        ai_fields=data.get("ai_fields", []),
        ai_generated=data.get("ai_generated", False),
        ai_category=data.get("ai_category", ""),
        local_variables=data.get("local_variables", {}) or {},
    )
