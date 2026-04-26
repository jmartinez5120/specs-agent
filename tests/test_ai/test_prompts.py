"""Unit tests for prompt construction and response parsing."""

from __future__ import annotations

import json

import pytest

from specs_agent.ai.prompts import (
    SYSTEM_PROMPT,
    build_batch_prompt,
    build_single_prompt,
    parse_batch_response,
    parse_single_response,
    _extract_json,
)


# ------------------------------------------------------------------ #
# Prompt construction
# ------------------------------------------------------------------ #


class TestBuildBatchPrompt:
    def test_basic_structure(self) -> None:
        fields = [
            {"name": "status", "type": "string", "enum": ["A", "B"], "description": "The status"},
            {"name": "notes", "type": "string", "description": "Notes field"},
        ]
        prompt = build_batch_prompt(fields, "PUT", "/missions/{id}/status", "Update mission")
        assert "PUT /missions/{id}/status" in prompt
        assert "Update mission" in prompt
        assert '"status"' in prompt
        assert '"notes"' in prompt
        assert '["A", "B"]' in prompt  # enum rendered
        assert "ONLY" in prompt  # instruction

    def test_no_description(self) -> None:
        fields = [{"name": "x", "type": "integer"}]
        prompt = build_batch_prompt(fields, "GET", "/foo")
        assert "Description:" not in prompt
        assert "GET /foo" in prompt

    def test_field_with_format(self) -> None:
        fields = [{"name": "email", "type": "string", "format": "email", "description": ""}]
        prompt = build_batch_prompt(fields, "POST", "/users")
        assert "format: email" in prompt

    def test_output_shape_matches_fields(self) -> None:
        fields = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        prompt = build_batch_prompt(fields, "POST", "/x")
        assert '"a": <value>' in prompt
        assert '"b": <value>' in prompt
        assert '"c": <value>' in prompt


class TestBuildSinglePrompt:
    def test_includes_all_context(self) -> None:
        prompt = build_single_prompt(
            name="callsign",
            schema_type="string",
            description="Aircraft callsign (ICAO format)",
            endpoint_method="POST",
            endpoint_path="/flights",
            endpoint_description="Register a new flight",
        )
        assert "callsign" in prompt
        assert "Aircraft callsign" in prompt
        assert "POST /flights" in prompt
        assert "Register a new flight" in prompt

    def test_with_enum(self) -> None:
        prompt = build_single_prompt(
            name="size", schema_type="string", enum=["S", "M", "L"],
        )
        assert '["S", "M", "L"]' in prompt


class TestSystemPrompt:
    def test_not_empty(self) -> None:
        assert len(SYSTEM_PROMPT) > 20
        assert "JSON" in SYSTEM_PROMPT


# ------------------------------------------------------------------ #
# Response parsing
# ------------------------------------------------------------------ #


class TestParseBatchResponse:
    def test_clean_json(self) -> None:
        raw = '{"status": "IN_FLIGHT", "notes": "Orbit confirmed"}'
        result = parse_batch_response(raw, ["status", "notes"])
        assert result == {"status": "IN_FLIGHT", "notes": "Orbit confirmed"}

    def test_fenced_json(self) -> None:
        raw = '```json\n{"a": 1, "b": "two"}\n```'
        result = parse_batch_response(raw, ["a", "b"])
        assert result == {"a": 1, "b": "two"}

    def test_with_preamble(self) -> None:
        raw = 'Here is the output:\n\n{"x": "hello"}\n\nHope that helps!'
        result = parse_batch_response(raw, ["x"])
        assert result == {"x": "hello"}

    def test_filters_unrequested_fields(self) -> None:
        raw = '{"asked": 1, "extra_hallucinated": 2}'
        result = parse_batch_response(raw, ["asked"])
        assert result == {"asked": 1}

    def test_empty_on_garbage(self) -> None:
        assert parse_batch_response("not json at all", ["a"]) == {}

    def test_empty_on_non_object(self) -> None:
        assert parse_batch_response("[1, 2, 3]", ["a"]) == {}

    def test_empty_string(self) -> None:
        assert parse_batch_response("", ["a"]) == {}


class TestParseSingleResponse:
    def test_string(self) -> None:
        assert parse_single_response("hello world", "string") == "hello world"

    def test_string_strips_quotes(self) -> None:
        assert parse_single_response('"quoted"', "string") == "quoted"

    def test_integer(self) -> None:
        assert parse_single_response("42", "integer") == 42

    def test_integer_from_float_string(self) -> None:
        assert parse_single_response("42.0", "integer") == 42

    def test_integer_garbage(self) -> None:
        assert parse_single_response("not-a-number", "integer") is None

    def test_number(self) -> None:
        assert parse_single_response("3.14", "number") == 3.14

    def test_boolean_true(self) -> None:
        for v in ("true", "True", "TRUE", "1", "yes"):
            assert parse_single_response(v, "boolean") is True

    def test_boolean_false(self) -> None:
        for v in ("false", "False", "0", "no"):
            assert parse_single_response(v, "boolean") is False

    def test_boolean_garbage(self) -> None:
        assert parse_single_response("maybe", "boolean") is None

    def test_array(self) -> None:
        assert parse_single_response('[1, 2, 3]', "array") == [1, 2, 3]

    def test_object(self) -> None:
        assert parse_single_response('{"k": "v"}', "object") == {"k": "v"}

    def test_fenced_object(self) -> None:
        assert parse_single_response('```json\n{"k": 1}\n```', "object") == {"k": 1}

    def test_empty_returns_none(self) -> None:
        assert parse_single_response("", "string") is None
        assert parse_single_response("   ", "integer") is None


class TestExtractJson:
    def test_clean(self) -> None:
        assert _extract_json('{"a": 1}') == '{"a": 1}'

    def test_fenced(self) -> None:
        assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_surrounded(self) -> None:
        assert _extract_json('blah\n{"a": 1}\nblah') == '{"a": 1}'

    def test_no_json(self) -> None:
        assert _extract_json("no json here") == ""
