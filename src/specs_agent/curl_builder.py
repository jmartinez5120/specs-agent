"""Generate cURL commands from test cases."""

from __future__ import annotations

import json
import shlex

from specs_agent.models.plan import TestCase
from specs_agent.templating.variables import resolve_value


def build_curl(test_case: TestCase, base_url: str, auth_type: str = "none", auth_value: str = "") -> str:
    """Build a cURL command string from a TestCase.

    Template variables are resolved to real values.
    """
    # Resolve template variables
    path_params = resolve_value(dict(test_case.path_params))
    query_params = resolve_value(dict(test_case.query_params))
    headers = resolve_value(dict(test_case.headers))
    body = resolve_value(test_case.body) if test_case.body else None

    # Build URL
    path = test_case.endpoint_path
    for k, v in path_params.items():
        path = path.replace(f"{{{k}}}", str(v))
    url = f"{base_url.rstrip('/')}{path}"

    # Add query params
    if query_params:
        qs = "&".join(f"{k}={v}" for k, v in query_params.items())
        url = f"{url}?{qs}"

    parts = ["curl"]

    # Method
    if test_case.method != "GET":
        parts.append(f"-X {test_case.method}")

    # URL
    parts.append(shlex.quote(url))

    # Auth
    if auth_type == "bearer" and auth_value:
        parts.append(f"-H {shlex.quote(f'Authorization: Bearer {auth_value}')}")
    elif auth_type == "api_key" and auth_value:
        parts.append(f"-H {shlex.quote(f'Authorization: {auth_value}')}")
    elif auth_type == "basic" and auth_value:
        parts.append(f"-u {shlex.quote(auth_value)}")

    # Headers
    for k, v in headers.items():
        parts.append(f"-H {shlex.quote(f'{k}: {v}')}")

    # Body
    if body is not None:
        if isinstance(body, (dict, list)):
            parts.append(f"-H {shlex.quote('Content-Type: application/json')}")
            parts.append(f"-d {shlex.quote(json.dumps(body))}")
        else:
            parts.append(f"-d {shlex.quote(str(body))}")

    return " \\\n  ".join(parts)
