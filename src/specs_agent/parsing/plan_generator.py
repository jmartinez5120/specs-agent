"""Auto-generate test plans from parsed OpenAPI specs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan
from specs_agent.models.spec import Endpoint, HttpMethod, Parameter, ParsedSpec


def generate_plan(spec: ParsedSpec, base_url: str | None = None) -> TestPlan:
    """Generate a TestPlan from a ParsedSpec.

    Rules:
    - One TestCase per endpoint + documented response status code
    - Success (2xx): assert status code + response schema if defined
    - Error (4xx/5xx): assert status code only
    - GET: no body, populate required params with placeholders
    - POST/PUT/PATCH: generate minimal body from request_body_schema
    - Mark cases with missing required params as needs_input
    """
    url = base_url or spec.base_url
    plan = TestPlan(
        name=f"{spec.title} Test Plan",
        spec_title=spec.title,
        base_url=url,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    for endpoint in spec.endpoints:
        cases = _generate_cases_for_endpoint(endpoint)
        plan.test_cases.extend(cases)

        # Capture x-performance SLAs
        if endpoint.performance_sla:
            key = f"{endpoint.method.value} {endpoint.path}"
            sla = endpoint.performance_sla
            plan.performance_slas[key] = {
                "p95_ms": sla.latency_p95_ms,
                "p99_ms": sla.latency_p99_ms,
                "throughput_rps": sla.throughput_rps,
                "timeout_ms": sla.timeout_ms,
            }

    return plan


def _generate_cases_for_endpoint(endpoint: Endpoint) -> list[TestCase]:
    cases: list[TestCase] = []

    # ── Happy path: one test per documented response ─────────────────
    for resp in endpoint.responses:
        is_success = 200 <= resp.status_code < 300
        name = f"{endpoint.method.value} {endpoint.path} → {resp.status_code}"

        assertions = [
            Assertion(
                type=AssertionType.STATUS_CODE,
                expected=resp.status_code,
                description=f"Expect status {resp.status_code}",
            )
        ]

        if is_success and resp.schema:
            assertions.append(
                Assertion(
                    type=AssertionType.RESPONSE_SCHEMA,
                    expected=resp.schema,
                    description="Validate response body schema",
                )
            )

        path_params, needs_input = _build_path_params(endpoint.parameters)
        query_params = _build_query_params(endpoint.parameters)
        # Always include body for methods that require it — servers often
        # reject with 400 before checking resource existence (404)
        body = _build_request_body(endpoint)

        cases.append(
            TestCase(
                endpoint_path=endpoint.path,
                method=endpoint.method.value,
                name=name,
                description=resp.description or f"Test {endpoint.display_name} → {resp.status_code}",
                enabled=is_success,
                path_params=path_params,
                query_params=query_params,
                body=body,
                assertions=assertions,
                needs_input=needs_input,
            )
        )

    # If no responses documented, create a basic smoke test
    if not endpoint.responses:
        path_params, needs_input = _build_path_params(endpoint.parameters)
        cases.append(
            TestCase(
                endpoint_path=endpoint.path,
                method=endpoint.method.value,
                name=f"{endpoint.method.value} {endpoint.path} → smoke test",
                description=f"Smoke test for {endpoint.display_name}",
                enabled=True,
                path_params=path_params,
                query_params=_build_query_params(endpoint.parameters),
                body=_build_request_body(endpoint),
                assertions=[
                    Assertion(
                        type=AssertionType.STATUS_CODE,
                        expected=200,
                        description="Expect success",
                    )
                ],
                needs_input=needs_input,
            )
        )

    # ── Sad path: negative test cases ────────────────────────────────
    cases.extend(_generate_negative_cases(endpoint))

    return cases


def _generate_negative_cases(endpoint: Endpoint) -> list[TestCase]:
    """Generate negative/sad-path test cases.

    Uses documented error responses from the spec when available.
    When the spec documents NO error responses, generates best-practice
    negative cases based on the endpoint structure (params, body, method).
    """
    cases: list[TestCase] = []
    method = endpoint.method.value
    path = endpoint.path
    path_params_list = [p for p in endpoint.parameters if p.location.value == "path"]

    # Collect documented error codes from the spec
    documented_errors: dict[int, str] = {}
    for resp in endpoint.responses:
        if resp.status_code >= 400:
            documented_errors[resp.status_code] = resp.description

    # If the spec has no documented errors, infer likely ones based on endpoint structure
    if not documented_errors:
        documented_errors = _infer_error_responses(endpoint)

    # For each documented error, generate an appropriate test case
    # (The happy-path loop already created disabled cases for these,
    #  but those have no triggering data. Here we craft data to trigger them.)

    if 404 in documented_errors and path_params_list:
        # 404: Send non-existent ID to trigger not-found
        bad_params = {}
        for p in path_params_list:
            if p.schema_type in ("integer", "int64", "int32"):
                bad_params[p.name] = "999999999"
            else:
                bad_params[p.name] = "nonexistent_id_000"
        cases.append(
            TestCase(
                endpoint_path=path,
                method=method,
                name=f"{method} {path} → 404 not found (trigger)",
                description=f"Sad path: {documented_errors[404]}",
                enabled=False,
                test_type="sad",
                path_params=bad_params,
                assertions=[
                    Assertion(
                        type=AssertionType.STATUS_CODE,
                        expected=404,
                        description=f"Spec: {documented_errors[404]}",
                    )
                ],
            )
        )

    if 400 in documented_errors:
        path_params_dict = _build_path_params_dict(endpoint.parameters)

        # 400: Empty body (for POST/PUT/PATCH)
        if method in ("POST", "PUT", "PATCH") and endpoint.request_body_schema:
            cases.append(
                TestCase(
                    endpoint_path=path,
                    method=method,
                    name=f"{method} {path} → 400 empty body (trigger)",
                    description=f"Sad path: {documented_errors[400]}",
                    enabled=False,
                    test_type="sad",
                    path_params=path_params_dict,
                    body={},
                    assertions=[
                        Assertion(
                            type=AssertionType.STATUS_CODE,
                            expected=400,
                            description=f"Spec: {documented_errors[400]}",
                        )
                    ],
                )
            )

        # 400: Missing required fields
        if method in ("POST", "PUT", "PATCH") and endpoint.request_body_schema:
            schema = endpoint.request_body_schema
            required_fields = schema.get("required", [])
            properties = schema.get("properties", {})

            for field in required_fields[:3]:
                partial_body = {}
                for prop_name, prop_schema in properties.items():
                    if prop_name == field:
                        continue
                    partial_body[prop_name] = _generate_sample_from_schema(prop_schema)

                cases.append(
                    TestCase(
                        endpoint_path=path,
                        method=method,
                        name=f"{method} {path} → 400 missing {field} (trigger)",
                        description=f"Sad path: required field '{field}' omitted — {documented_errors[400]}",
                        enabled=False,
                    test_type="sad",
                        path_params=path_params_dict,
                        body=partial_body,
                        assertions=[
                            Assertion(
                                type=AssertionType.STATUS_CODE,
                                expected=400,
                                description=f"Expect 400 when '{field}' missing",
                            )
                        ],
                    )
                )

        # 400: Invalid param type
        for p in path_params_list:
            if p.schema_type in ("integer", "int64", "int32", "number"):
                bad_type_params = _build_path_params_dict(endpoint.parameters)
                bad_type_params[p.name] = "not_a_number"
                cases.append(
                    TestCase(
                        endpoint_path=path,
                        method=method,
                        name=f"{method} {path} → 400 invalid {p.name} (trigger)",
                        description=f"Sad path: {p.name} expects {p.schema_type} — {documented_errors[400]}",
                        enabled=False,
                    test_type="sad",
                        path_params=bad_type_params,
                        assertions=[
                            Assertion(
                                type=AssertionType.STATUS_CODE,
                                expected=400,
                                description=f"Spec: {documented_errors[400]}",
                            )
                        ],
                    )
                )

    if 401 in documented_errors:
        # 401: No auth header
        path_params_dict = _build_path_params_dict(endpoint.parameters)
        cases.append(
            TestCase(
                endpoint_path=path,
                method=method,
                name=f"{method} {path} → 401 unauthorized (trigger)",
                description=f"Sad path: {documented_errors[401]}",
                enabled=False,
                test_type="sad",
                path_params=path_params_dict,
                headers={"Authorization": ""},  # Empty auth
                assertions=[
                    Assertion(
                        type=AssertionType.STATUS_CODE,
                        expected=401,
                        description=f"Spec: {documented_errors[401]}",
                    )
                ],
            )
        )

    if 403 in documented_errors:
        path_params_dict = _build_path_params_dict(endpoint.parameters)
        cases.append(
            TestCase(
                endpoint_path=path,
                method=method,
                name=f"{method} {path} → 403 forbidden (trigger)",
                description=f"Sad path: {documented_errors[403]}",
                enabled=False,
                test_type="sad",
                path_params=path_params_dict,
                headers={"Authorization": "Bearer invalid_token_000"},
                assertions=[
                    Assertion(
                        type=AssertionType.STATUS_CODE,
                        expected=403,
                        description=f"Spec: {documented_errors[403]}",
                    )
                ],
            )
        )

    if 409 in documented_errors:
        # 409: Conflict — try creating a duplicate
        path_params_dict = _build_path_params_dict(endpoint.parameters)
        body = _build_request_body(endpoint)
        cases.append(
            TestCase(
                endpoint_path=path,
                method=method,
                name=f"{method} {path} → 409 conflict (trigger)",
                description=f"Sad path: {documented_errors[409]}",
                enabled=False,
                test_type="sad",
                path_params=path_params_dict,
                body=body,
                assertions=[
                    Assertion(
                        type=AssertionType.STATUS_CODE,
                        expected=409,
                        description=f"Spec: {documented_errors[409]}",
                    )
                ],
            )
        )

    if 415 in documented_errors:
        path_params_dict = _build_path_params_dict(endpoint.parameters)
        cases.append(
            TestCase(
                endpoint_path=path,
                method=method,
                name=f"{method} {path} → 415 wrong content type (trigger)",
                description=f"Sad path: {documented_errors[415]}",
                enabled=False,
                test_type="sad",
                path_params=path_params_dict,
                headers={"Content-Type": "text/plain"},
                body="not json",
                assertions=[
                    Assertion(
                        type=AssertionType.STATUS_CODE,
                        expected=415,
                        description=f"Spec: {documented_errors[415]}",
                    )
                ],
            )
        )

    if 429 in documented_errors:
        path_params_dict = _build_path_params_dict(endpoint.parameters)
        cases.append(
            TestCase(
                endpoint_path=path,
                method=method,
                name=f"{method} {path} → 429 rate limited (trigger)",
                description=f"Sad path: {documented_errors[429]}",
                enabled=False,
                test_type="sad",
                path_params=path_params_dict,
                assertions=[
                    Assertion(
                        type=AssertionType.STATUS_CODE,
                        expected=429,
                        description=f"Spec: {documented_errors[429]}",
                    )
                ],
            )
        )

    # Any other documented error codes not specifically handled above
    handled = {400, 401, 403, 404, 409, 415, 429}
    for code, desc in documented_errors.items():
        if code not in handled:
            path_params_dict = _build_path_params_dict(endpoint.parameters)
            cases.append(
                TestCase(
                    endpoint_path=path,
                    method=method,
                    name=f"{method} {path} → {code} (spec-documented)",
                    description=f"Sad path: {desc}",
                    enabled=False,
                    test_type="sad",
                    path_params=path_params_dict,
                    assertions=[
                        Assertion(
                            type=AssertionType.STATUS_CODE,
                            expected=code,
                            description=f"Spec: {desc}",
                        )
                    ],
                )
            )

    return cases


def _infer_error_responses(endpoint: Endpoint) -> dict[int, str]:
    """Infer likely error responses based on endpoint structure when spec doesn't document them."""
    errors: dict[int, str] = {}
    method = endpoint.method.value
    has_path_params = any(p.location.value == "path" for p in endpoint.parameters)
    has_body = method in ("POST", "PUT", "PATCH") and endpoint.request_body_schema

    # Endpoints with path params likely return 404
    if has_path_params:
        errors[404] = "Resource not found (inferred)"

    # Endpoints with request body likely return 400
    if has_body:
        errors[400] = "Invalid request body (inferred)"

    return errors


def _build_path_params_dict(parameters: list[Parameter]) -> dict[str, str]:
    """Build path params dict without the needs_input tracking."""
    params: dict[str, str] = {}
    for p in parameters:
        if p.location.value != "path":
            continue
        if p.example is not None:
            params[p.name] = str(p.example)
        elif p.default is not None:
            params[p.name] = str(p.default)
        elif p.enum_values:
            params[p.name] = p.enum_values[0]
        else:
            params[p.name] = _smart_placeholder(p.name, p.schema_type)
    return params


def _build_path_params(parameters: list[Parameter]) -> tuple[dict[str, str], bool]:
    """Build path parameter values. Returns (params_dict, needs_input).

    needs_input is False when all params have examples, defaults, enums,
    or valid faker template variables. It's only True when we can't generate
    any reasonable value.
    """
    params: dict[str, str] = {}
    needs_input = False

    for p in parameters:
        if p.location.value != "path":
            continue
        if p.example is not None:
            params[p.name] = str(p.example)
        elif p.default is not None:
            params[p.name] = str(p.default)
        elif p.enum_values:
            params[p.name] = p.enum_values[0]
        else:
            # Smart placeholder uses a faker function — this resolves at runtime
            params[p.name] = _smart_placeholder(p.name, p.schema_type)
            # Faker functions are auto-resolved, so no user input needed

    return params, needs_input


def _build_query_params(parameters: list[Parameter]) -> dict[str, str]:
    """Build query parameter values for required params only."""
    params: dict[str, str] = {}
    for p in parameters:
        if p.location.value != "query":
            continue
        if not p.required:
            continue
        if p.example is not None:
            params[p.name] = str(p.example)
        elif p.default is not None:
            params[p.name] = str(p.default)
        elif p.enum_values:
            params[p.name] = p.enum_values[0]
        else:
            params[p.name] = _smart_placeholder(p.name, p.schema_type)
    return params


def _smart_placeholder(param_name: str, schema_type: str) -> str:
    """Generate a smart template placeholder based on parameter name and type."""
    name = param_name.lower()

    # Match by name patterns
    if "id" in name or "uuid" in name or "guid" in name:
        return "{{$guid}}"
    if "email" in name:
        return "{{$randomEmail}}"
    if "name" in name and "user" in name:
        return "{{$randomUserName}}"
    if "first" in name and "name" in name:
        return "{{$randomFirstName}}"
    if "last" in name and "name" in name:
        return "{{$randomLastName}}"
    if "name" in name:
        return "{{$randomName}}"
    if "phone" in name:
        return "{{$randomPhone}}"
    if "url" in name or "uri" in name:
        return "{{$randomUrl}}"
    if "ip" in name:
        return "{{$randomIP}}"
    if "city" in name:
        return "{{$randomCity}}"
    if "country" in name:
        return "{{$randomCountry}}"
    if "zip" in name or "postal" in name:
        return "{{$randomZip}}"
    if "address" in name or "street" in name:
        return "{{$randomStreet}}"
    if "company" in name or "org" in name:
        return "{{$randomCompany}}"
    if "date" in name:
        return "{{$randomDate}}"
    if "time" in name:
        return "{{$isoTimestamp}}"

    # Fall back by schema type
    if schema_type == "integer":
        return "{{$randomInt}}"
    if schema_type == "number":
        return "{{$randomFloat}}"
    if schema_type == "boolean":
        return "{{$randomBoolean}}"

    return "{{$randomWord}}"


def _build_request_body(endpoint: Endpoint) -> Any | None:
    """Generate a minimal request body from the schema."""
    if endpoint.method in (HttpMethod.GET, HttpMethod.DELETE, HttpMethod.HEAD, HttpMethod.OPTIONS):
        return None
    schema = endpoint.request_body_schema
    if not schema:
        return None
    return _generate_sample_from_schema(schema)


def _generate_sample_from_schema(schema: dict) -> Any:
    """Generate a minimal sample value from a JSON schema."""
    schema_type = schema.get("type", "object")

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        obj: dict[str, Any] = {}
        for prop_name, prop_schema in properties.items():
            # Include required fields and a few optional ones
            if prop_name in required or len(obj) < 3:
                obj[prop_name] = _generate_sample_from_schema(prop_schema)
        return obj

    if schema_type == "array":
        items = schema.get("items", {})
        return [_generate_sample_from_schema(items)]

    if schema_type == "string":
        enum = schema.get("enum")
        if enum:
            return enum[0]
        fmt = schema.get("format", "")
        if fmt == "email":
            return "{{$randomEmail}}"
        if fmt == "date":
            return "{{$randomDate}}"
        if fmt == "date-time":
            return "{{$isoTimestamp}}"
        if fmt == "uri" or fmt == "url":
            return "{{$randomUrl}}"
        if fmt == "uuid":
            return "{{$guid}}"
        if fmt == "ipv4":
            return "{{$randomIP}}"
        if fmt == "ipv6":
            return "{{$randomIPv6}}"
        return "{{$randomWord}}"

    if schema_type == "integer":
        return schema.get("default", "{{$randomInt}}")

    if schema_type == "number":
        return schema.get("default", "{{$randomFloat}}")

    if schema_type == "boolean":
        return schema.get("default", "{{$randomBoolean}}")

    return None
