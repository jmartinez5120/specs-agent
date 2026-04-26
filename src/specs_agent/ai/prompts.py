"""Prompt templates and response parsing for the AI scenario generator.

The core strategy is **batch prompting per endpoint**: collect all fields
that need AI generation for a single endpoint's request body, build one
prompt, get one JSON response back, parse it into individual field values.

This keeps LLM calls to ~1 per endpoint instead of ~1 per field.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ------------------------------------------------------------------ #
# System prompt (stays constant across all calls)
# ------------------------------------------------------------------ #

SYSTEM_PROMPT = (
    "You are a test data generator for REST API testing. "
    "Generate realistic, contextually appropriate values for API request fields. "
    "Output ONLY valid JSON — no explanation, no markdown fences, no extra text."
)


# ------------------------------------------------------------------ #
# Batch prompt builder
# ------------------------------------------------------------------ #


def build_batch_prompt(
    fields: list[dict[str, Any]],
    endpoint_method: str,
    endpoint_path: str,
    endpoint_description: str = "",
) -> str:
    """Build a single prompt that requests values for multiple fields.

    Args:
        fields: List of dicts, each with keys:
            - name: property name
            - type: JSON schema type
            - description: property description (may be empty)
            - enum: list of allowed values (may be empty/None)
            - format: JSON schema format (may be empty/None)
        endpoint_method: HTTP method (GET, POST, etc.)
        endpoint_path: URL path template
        endpoint_description: endpoint summary or description
    """
    lines = [
        "Generate realistic test values for these API request body fields.",
        "Output ONLY a JSON object mapping field names to values.",
        "",
        f"Endpoint: {endpoint_method} {endpoint_path}",
    ]
    if endpoint_description:
        lines.append(f"Description: {endpoint_description}")
    lines.append("")
    lines.append("Fields:")

    for f in fields:
        parts = [f'- "{f["name"]}" ({f.get("type", "string")}']
        if f.get("enum"):
            parts.append(f', enum: {json.dumps(f["enum"])}')
        parts.append(")")
        if f.get("description"):
            parts.append(f': {f["description"]}')
        if f.get("format"):
            parts.append(f' [format: {f["format"]}]')
        lines.append("".join(parts))

    # Show the expected output shape
    field_names = [f["name"] for f in fields]
    placeholder = ", ".join(f'"{n}": <value>' for n in field_names)
    lines.append("")
    lines.append(f"Output: {{{placeholder}}}")

    return "\n".join(lines)


def build_single_prompt(
    name: str,
    schema_type: str,
    description: str = "",
    enum: list[str] | None = None,
    fmt: str = "",
    endpoint_method: str = "",
    endpoint_path: str = "",
    endpoint_description: str = "",
) -> str:
    """Build a prompt for a single field (fallback when batch isn't needed)."""
    lines = [
        "Generate a realistic test value for this API field.",
        "Output ONLY the raw value — no quotes (unless it's a string), no explanation.",
        "",
    ]
    if endpoint_method:
        lines.append(f"Endpoint: {endpoint_method} {endpoint_path}")
    if endpoint_description:
        lines.append(f"Description: {endpoint_description}")
    lines.append(f"Field name: {name}")
    lines.append(f"Field type: {schema_type}")
    if description:
        lines.append(f"Field description: {description}")
    if enum:
        lines.append(f"Allowed values: {json.dumps(enum)}")
    if fmt:
        lines.append(f"Format: {fmt}")
    lines.append("")
    lines.append("Output:")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Response parsing
# ------------------------------------------------------------------ #


def parse_batch_response(
    raw: str,
    field_names: list[str],
) -> dict[str, Any]:
    """Parse a batch JSON response from the LLM.

    Tries to extract a JSON object from the response. Falls back to
    returning an empty dict if parsing fails.

    Args:
        raw: Raw LLM output (may contain markdown fences, extra text)
        field_names: Expected field names (for validation)

    Returns:
        Dict mapping field names to generated values. Missing fields
        are omitted (caller should fall back to Faker for those).
    """
    cleaned = _extract_json(raw)
    if not cleaned:
        return {}

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    # Only return fields we actually asked for
    return {k: v for k, v in data.items() if k in field_names}


def parse_single_response(raw: str, expected_type: str) -> Any:
    """Parse a single-value response from the LLM.

    Args:
        raw: Raw LLM output
        expected_type: JSON schema type ("string", "integer", "number", "boolean", "array", "object")

    Returns:
        The parsed value, or None if unparseable.
    """
    text = raw.strip()
    # Strip markdown fences
    text = re.sub(r"^```\w*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    if not text:
        return None

    if expected_type == "integer":
        try:
            return int(float(text))
        except (ValueError, TypeError):
            return None

    if expected_type == "number":
        try:
            return float(text)
        except (ValueError, TypeError):
            return None

    if expected_type == "boolean":
        if text.lower() in ("true", "1", "yes"):
            return True
        if text.lower() in ("false", "0", "no"):
            return False
        return None

    if expected_type in ("array", "object"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    # Default: string
    # Strip surrounding quotes if present
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text


# ------------------------------------------------------------------ #
# Scenario generation — propose additional test cases for an endpoint
# ------------------------------------------------------------------ #

SCENARIO_SYSTEM_PROMPT = (
    "You are an expert API test engineer. Given an API endpoint definition, "
    "propose additional test scenarios that a rule-based generator would miss. "
    "Focus on edge cases, boundary conditions, security, and domain logic.\n"
    "\n"
    "CRITICAL RULES for the `body` field in your output:\n"
    "- `body` is the REQUEST body sent BY the client. It is NOT the response.\n"
    "- GET, DELETE, HEAD, and OPTIONS endpoints MUST have `body: null`.\n"
    "- Never put error messages, status strings, or server responses in `body`.\n"
    "- For POST/PUT/PATCH, `body` must match the Request body schema shown in the prompt.\n"
    "\n"
    "Output ONLY valid JSON — no explanation, no markdown fences."
)


def build_scenario_prompt(
    endpoint_method: str,
    endpoint_path: str,
    endpoint_description: str,
    parameters: list[dict],
    body_schema: dict | None,
    documented_responses: list[int],
) -> str:
    """Build a prompt that asks the LLM to propose extra test scenarios."""
    method_u = endpoint_method.upper()
    body_allowed = method_u in ("POST", "PUT", "PATCH")
    lines = [
        "Propose 3-6 additional test scenarios for this API endpoint.",
        "These should cover edge cases, boundary conditions, security, "
        "invalid inputs, and domain-specific logic that standard happy/sad "
        "path tests miss.",
        "",
        f"Endpoint: {endpoint_method} {endpoint_path}",
    ]
    if not body_allowed:
        lines.append(
            f"NOTE: {method_u} requests have no request body. "
            "Every scenario MUST set `body` to null."
        )
    if endpoint_description:
        lines.append(f"Description: {endpoint_description}")

    if parameters:
        lines.append("")
        lines.append("Parameters:")
        for p in parameters[:10]:  # limit to avoid prompt overflow
            lines.append(f'  - {p.get("name", "?")} ({p.get("location", "?")}, '
                         f'{p.get("schema_type", "string")})'
                         f'{": " + p.get("description", "") if p.get("description") else ""}')

    if body_schema and body_schema.get("properties"):
        lines.append("")
        lines.append("Request body fields:")
        for name, prop in list(body_schema["properties"].items())[:15]:
            ptype = prop.get("type", "string")
            desc = prop.get("description", "")
            enum = prop.get("enum", [])
            line = f'  - "{name}" ({ptype})'
            if enum:
                line += f" enum: {json.dumps(enum[:5])}"
            if desc:
                line += f" — {desc[:80]}"
            lines.append(line)

    lines.append("")
    lines.append(f"Already tested response codes: {documented_responses}")
    lines.append("")
    lines.append(
        'Output a JSON array of scenario objects:\n'
        '[\n'
        '  {\n'
        '    "name": "Short scenario name",\n'
        '    "description": "What this tests and why",\n'
        '    "category": "edge_case|boundary|security|invalid_input|domain|performance",\n'
        '    "expected_status": 400,\n'
        '    "body": {"field": "value"} or null,\n'
        '    "path_params": {"id": "value"} or {},\n'
        '    "query_params": {"key": "value"} or {}\n'
        '  }\n'
        ']'
    )
    return "\n".join(lines)


def parse_scenario_response(raw: str) -> list[dict]:
    """Parse the LLM's scenario proposals from raw output."""
    cleaned = _extract_json_array(raw)
    if not cleaned:
        return []
    cleaned = _sanitize_llm_json(cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # Recover by keeping well-formed prefix objects.
        recovered = _recover_partial_json_array(cleaned)
        if recovered:
            try:
                data = json.loads(recovered)
            except json.JSONDecodeError:
                data = _parse_objects_individually(cleaned)
        else:
            data = _parse_objects_individually(cleaned)
    if not isinstance(data, list):
        return []
    # Validate each scenario has minimum required fields
    valid = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if not item.get("name"):
            continue
        valid.append({
            "name": str(item.get("name", "")),
            "description": str(item.get("description", "")),
            "category": str(item.get("category", "edge_case")),
            "expected_status": int(item.get("expected_status", 400)) if item.get("expected_status") else 400,
            "body": item.get("body"),
            "path_params": item.get("path_params") or {},
            "query_params": item.get("query_params") or {},
        })
    return valid


def _extract_json_array(text: str) -> str:
    """Try to pull a JSON array from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?\s*```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        return text
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        return match.group(0)
    return ""


def _sanitize_llm_json(text: str) -> str:
    """Clean up common LLM JSON artifacts that break json.loads.

    - Literal ellipsis inside arrays/objects (`[1, 2, ..., 10]`, `..., ...`)
    - Trailing commas before `]` or `}`
    """
    # Drop `..., ` and `, ...` sequences that aren't real values.
    text = re.sub(r",\s*\.{3}\s*,", ",", text)
    text = re.sub(r",\s*\.{3}\s*(?=[\]}])", "", text)
    text = re.sub(r"(?<=[\[{])\s*\.{3}\s*,", "", text)
    # Bare `...` still inside an array → replace with null so the array is valid.
    text = re.sub(r"(?<=[,\[])\s*\.{3}\s*(?=[,\]])", " null", text)
    # Trailing commas before closers.
    text = re.sub(r",\s*(?=[}\]])", "", text)
    return text


def _parse_objects_individually(text: str) -> list[dict]:
    """Walk a JSON-ish array and json.loads each top-level `{...}` in turn.

    LLMs occasionally slip Python expressions into one scenario's fields
    (e.g. `"id": "A" + "x" * 5000`). A whole-array parse fails on the first
    bad item; parsing object-by-object lets the remaining valid scenarios
    survive. Invalid objects are silently dropped — the caller expects a
    best-effort list.
    """
    if not text:
        return []
    inner = text.strip()
    if inner.startswith("["):
        inner = inner[1:]
    if inner.endswith("]"):
        inner = inner[:-1]

    out: list[dict] = []
    depth = 0
    in_str = False
    esc = False
    start: int | None = None
    for i, ch in enumerate(inner):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = inner[start:i + 1]
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict):
                        out.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None
    return out


def _recover_partial_json_array(text: str) -> str:
    """If a JSON array is malformed mid-item, keep only the well-formed prefix.

    Walks the string once, tracking bracket/brace depth and string state; records
    the byte offset after each complete top-level object; re-wraps the prefix
    into `[...]` if anything usable remains.
    """
    if not text or not text.startswith("["):
        return ""
    depth = 0
    in_str = False
    esc = False
    last_complete: int = -1
    # Start after the opening `[`.
    for i, ch in enumerate(text[1:], start=1):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0 and ch == "}":
                last_complete = i  # inclusive index of closing brace
            if depth < 0:
                break
    if last_complete < 0:
        return ""
    return "[" + text[1:last_complete + 1] + "]"


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _extract_json(text: str) -> str:
    """Try to pull a JSON object out of LLM output that may have fences/text."""
    text = text.strip()

    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?\s*```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # Try the whole thing first
    if text.startswith("{") and text.endswith("}"):
        return text

    # Try to find a JSON object in the text
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        return match.group(0)

    return ""
