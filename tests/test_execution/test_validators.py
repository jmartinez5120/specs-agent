"""Unit tests for validators."""

from specs_agent.execution.validators import (
    validate_body_contains,
    validate_header_present,
    validate_header_value,
    validate_response_time,
    validate_schema,
    validate_status_code,
)


class TestStatusCodeValidator:
    def test_pass(self):
        r = validate_status_code(200, 200)
        assert r.passed is True

    def test_fail(self):
        r = validate_status_code(404, 200)
        assert r.passed is False
        assert "404" in r.message

    def test_server_error(self):
        r = validate_status_code(500, 200)
        assert r.passed is False


class TestSchemaValidator:
    def test_valid_object(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        r = validate_schema({"id": 1}, schema)
        assert r.passed is True

    def test_invalid_type(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
        r = validate_schema({"id": "not_an_int"}, schema)
        assert r.passed is False

    def test_unresolved_ref_skipped(self):
        schema = {"$ref": "#/components/schemas/Missing"}
        r = validate_schema({"anything": True}, schema)
        assert r.passed is True
        assert "skipped" in r.message.lower() or "skipped" in r.actual.lower()

    def test_empty_schema_skipped(self):
        r = validate_schema({"data": 1}, {})
        assert r.passed is True

    def test_array_schema(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        r = validate_schema([1, 2, 3], schema)
        assert r.passed is True

    def test_array_schema_invalid(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        r = validate_schema([1, "two", 3], schema)
        assert r.passed is False


class TestHeaderValidators:
    def test_header_present(self):
        r = validate_header_present({"Content-Type": "application/json"}, "content-type")
        assert r.passed is True

    def test_header_missing(self):
        r = validate_header_present({"Content-Type": "application/json"}, "x-custom")
        assert r.passed is False

    def test_header_value_match(self):
        r = validate_header_value({"Content-Type": "application/json"}, "content-type", "application/json")
        assert r.passed is True

    def test_header_value_mismatch(self):
        r = validate_header_value({"Content-Type": "text/html"}, "Content-Type", "application/json")
        assert r.passed is False


class TestResponseTimeValidator:
    def test_within_threshold(self):
        r = validate_response_time(100.0, 500.0)
        assert r.passed is True

    def test_exceeds_threshold(self):
        r = validate_response_time(600.0, 500.0)
        assert r.passed is False
        assert "600" in r.message

    def test_exact_threshold(self):
        r = validate_response_time(500.0, 500.0)
        assert r.passed is True


class TestBodyContainsValidator:
    def test_contains(self):
        r = validate_body_contains({"message": "hello world"}, "hello")
        assert r.passed is True

    def test_not_contains(self):
        r = validate_body_contains({"message": "hello"}, "goodbye")
        assert r.passed is False

    def test_contains_in_string(self):
        r = validate_body_contains("plain text response", "plain")
        assert r.passed is True
