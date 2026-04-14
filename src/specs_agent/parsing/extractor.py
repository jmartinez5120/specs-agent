"""Extract structured data from raw OpenAPI/Swagger spec dicts."""

from __future__ import annotations

from specs_agent.models.spec import (
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    ParsedSpec,
    PerformanceSLA,
    ResponseSpec,
    ServerInfo,
)

_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def extract_spec(raw: dict, source_url: str = "") -> ParsedSpec:
    """Convert a raw OpenAPI dict into a ParsedSpec model.

    Handles both Swagger 2.0 and OpenAPI 3.x.

    Args:
        raw: The raw spec dict.
        source_url: The URL the spec was loaded from (used to resolve relative server URLs).
    """
    is_v2 = "swagger" in raw
    spec_version = raw.get("swagger", raw.get("openapi", "3.0"))

    info = raw.get("info", {})
    title = info.get("title", "Untitled API")
    version = info.get("version", "0.0.0")
    description = info.get("description", "")

    servers = _extract_servers(raw, is_v2, source_url)
    endpoints = _extract_endpoints(raw, is_v2)
    tags = _extract_tags(raw)

    return ParsedSpec(
        title=title,
        version=version,
        description=description,
        spec_version=str(spec_version),
        servers=servers,
        endpoints=endpoints,
        tags=tags,
        raw_spec=raw,
    )


def _extract_servers(raw: dict, is_v2: bool, source_url: str = "") -> list[ServerInfo]:
    if is_v2:
        host = raw.get("host", "localhost")
        base_path = raw.get("basePath", "")
        schemes = raw.get("schemes", ["https"])
        scheme = schemes[0] if schemes else "https"
        return [ServerInfo(url=f"{scheme}://{host}{base_path}")]
    else:
        servers = raw.get("servers", [])
        result = []
        for s in servers:
            url = s.get("url", "")
            # Resolve relative URLs using the source URL
            if url and not url.startswith(("http://", "https://")) and source_url:
                from urllib.parse import urlparse
                parsed = urlparse(source_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                url = f"{origin}{url}"
            result.append(ServerInfo(url=url, description=s.get("description", "")))
        return result


def _extract_tags(raw: dict) -> list[str]:
    tag_objects = raw.get("tags", [])
    tag_names = [t.get("name", "") for t in tag_objects if t.get("name")]
    # Also collect tags from endpoints
    paths = raw.get("paths", {})
    for path_item in paths.values():
        for method in _METHODS:
            op = path_item.get(method)
            if op and isinstance(op, dict):
                for tag in op.get("tags", []):
                    if tag not in tag_names:
                        tag_names.append(tag)
    return tag_names


def _infer_tag_from_path(path: str) -> str:
    """Derive a tag from the URL path when none is provided.

    Examples:
        /v1/checkout/sessions/{id}  → checkout
        /pets/{petId}               → pets
        /v2/billing/meters          → billing
        /health                     → health
    """
    segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
    # Skip version prefixes like v1, v2, v3
    if segments and len(segments[0]) <= 3 and segments[0].lstrip("v").isdigit():
        segments = segments[1:]
    if segments:
        return segments[0]
    return "default"


def _parse_duration_ms(value: str | int | float) -> float | None:
    """Parse a duration string like '200ms', '2s', '1.5s' into milliseconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    try:
        if s.endswith("ms"):
            return float(s[:-2])
        if s.endswith("s"):
            return float(s[:-1]) * 1000
        return float(s)
    except ValueError:
        return None


def _parse_rps(value: str | int | float) -> float | None:
    """Parse a throughput value like '1000 rps', '500' into float."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower().replace("rps", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _extract_performance_sla(operation: dict) -> PerformanceSLA | None:
    """Extract x-performance SLA from an operation.

    Supports multiple formats:
      - Dict:   {"latency_p95": "200ms", "latency_p99": "500ms", "throughput": "1000 rps", "timeout": "2s"}
      - String: "p99: 50ms"
      - String: "p95: 200ms, p99: 500ms, throughput: 1000 rps"
    """
    perf = operation.get("x-performance")
    if not perf:
        return None

    # String format — parse key: value pairs
    if isinstance(perf, str):
        return _parse_perf_string(perf)

    # Dict format
    if isinstance(perf, dict):
        return PerformanceSLA(
            latency_p95_ms=_parse_duration_ms(perf.get("latency_p95") or perf.get("p95")),
            latency_p99_ms=_parse_duration_ms(perf.get("latency_p99") or perf.get("p99")),
            throughput_rps=_parse_rps(perf.get("throughput") or perf.get("tps") or perf.get("rps")),
            timeout_ms=_parse_duration_ms(perf.get("timeout")),
        )

    return None


def _parse_perf_string(text: str) -> PerformanceSLA | None:
    """Parse a performance SLA string like 'p99: 50ms' or 'p95: 200ms, p99: 500ms'."""
    sla = PerformanceSLA()
    has_value = False

    # Split on comma or semicolon for multiple values
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    for part in parts:
        if ":" not in part:
            continue
        key, _, val = part.partition(":")
        key = key.strip().lower()
        val = val.strip()

        if key in ("p95", "latency_p95"):
            sla.latency_p95_ms = _parse_duration_ms(val)
            has_value = True
        elif key in ("p99", "latency_p99"):
            sla.latency_p99_ms = _parse_duration_ms(val)
            has_value = True
        elif key in ("throughput", "rps", "tps"):
            sla.throughput_rps = _parse_rps(val)
            has_value = True
        elif key in ("timeout", "max_latency"):
            sla.timeout_ms = _parse_duration_ms(val)
            has_value = True

    return sla if has_value else None


def _extract_endpoints(raw: dict, is_v2: bool) -> list[Endpoint]:
    endpoints: list[Endpoint] = []
    paths = raw.get("paths", {})

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        # Path-level parameters (shared by all methods)
        path_level_params = path_item.get("parameters", [])

        for method_str in _METHODS:
            operation = path_item.get(method_str)
            if not operation or not isinstance(operation, dict):
                continue

            method = HttpMethod(method_str.upper())

            # Merge path-level params with operation-level
            op_params = operation.get("parameters", [])
            merged_params = _merge_parameters(path_level_params, op_params)
            parameters = _extract_parameters(merged_params, is_v2)

            request_body = _extract_request_body(operation, parameters, is_v2)
            responses = _extract_responses(operation.get("responses", {}), is_v2)

            tags = operation.get("tags", [])
            if not tags:
                tags = [_infer_tag_from_path(path)]

            perf_sla = _extract_performance_sla(operation)

            endpoints.append(
                Endpoint(
                    path=path,
                    method=method,
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary", ""),
                    description=operation.get("description", ""),
                    tags=tags,
                    parameters=parameters,
                    request_body_schema=request_body,
                    responses=responses,
                    security=operation.get("security", []),
                    performance_sla=perf_sla,
                )
            )
    return endpoints


def _merge_parameters(
    path_params: list[dict], op_params: list[dict]
) -> list[dict]:
    """Merge path-level and operation-level parameters.
    Operation params override path params with the same name+in.
    """
    merged: dict[str, dict] = {}
    for p in path_params:
        key = f"{p.get('name')}:{p.get('in')}"
        merged[key] = p
    for p in op_params:
        key = f"{p.get('name')}:{p.get('in')}"
        merged[key] = p
    return list(merged.values())


def _extract_parameters(raw_params: list[dict], is_v2: bool) -> list[Parameter]:
    params: list[Parameter] = []
    for raw in raw_params:
        location_str = raw.get("in", "query")
        # Skip body params in v2 — handled separately as request body
        if is_v2 and location_str == "body":
            continue

        try:
            location = ParameterLocation(location_str)
        except ValueError:
            location = ParameterLocation.QUERY

        if is_v2:
            schema_type = raw.get("type", "string")
            default = raw.get("default")
            example = raw.get("x-example")
            enum_values = raw.get("enum", [])
        else:
            schema = raw.get("schema", {})
            schema_type = schema.get("type", "string")
            default = schema.get("default")
            example = raw.get("example", schema.get("example"))
            enum_values = schema.get("enum", [])

        params.append(
            Parameter(
                name=raw.get("name", ""),
                location=location,
                required=raw.get("required", False),
                schema_type=schema_type,
                description=raw.get("description", ""),
                default=default,
                example=example,
                enum_values=enum_values or [],
            )
        )
    return params


def _extract_request_body(
    operation: dict, parameters: list[Parameter], is_v2: bool
) -> dict | None:
    """Extract request body schema."""
    if is_v2:
        # In Swagger 2.0, body is a parameter with "in": "body"
        for p in operation.get("parameters", []):
            if p.get("in") == "body":
                return p.get("schema")
        return None
    else:
        rb = operation.get("requestBody")
        if not rb:
            return None
        content = rb.get("content", {})
        # Prefer application/json
        json_content = content.get("application/json", {})
        if json_content:
            return json_content.get("schema")
        # Fall back to first content type
        for ct_data in content.values():
            return ct_data.get("schema")
        return None


def _extract_responses(raw_responses: dict, is_v2: bool) -> list[ResponseSpec]:
    responses: list[ResponseSpec] = []
    for code_str, resp_data in raw_responses.items():
        if code_str == "default":
            continue
        try:
            code = int(code_str)
        except ValueError:
            continue

        description = resp_data.get("description", "")

        if is_v2:
            schema = resp_data.get("schema")
        else:
            content = resp_data.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema") if json_content else None

        responses.append(
            ResponseSpec(status_code=code, description=description, schema=schema)
        )
    return responses
