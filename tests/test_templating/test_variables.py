"""Tests for the template variable system."""

import re
import uuid

from specs_agent.templating.variables import (
    list_variables,
    resolve_string,
    resolve_value,
)


class TestResolveString:
    def test_guid(self):
        result = resolve_string("{{$guid}}")
        # Should be a valid UUID
        uuid.UUID(result)

    def test_guid_dollar_sign_optional(self):
        result = resolve_string("{{guid}}")
        uuid.UUID(result)

    def test_random_email(self):
        result = resolve_string("{{$randomEmail}}")
        assert "@" in result

    def test_random_int(self):
        result = resolve_string("{{$randomInt}}")
        assert result.isdigit()

    def test_random_name(self):
        result = resolve_string("{{$randomName}}")
        assert len(result) > 0
        assert " " in result  # first + last name

    def test_timestamp(self):
        result = resolve_string("{{$timestamp}}")
        assert result.isdigit()
        assert int(result) > 1000000000

    def test_iso_timestamp(self):
        result = resolve_string("{{$isoTimestamp}}")
        assert "T" in result

    def test_multiple_vars_in_string(self):
        result = resolve_string("Hello {{$randomFirstName}}, your ID is {{$guid}}")
        assert "{{" not in result
        assert "Hello " in result
        assert ", your ID is " in result

    def test_unresolved_var_preserved(self):
        result = resolve_string("{{$nonExistentVar}}")
        assert result == "{{$nonExistentVar}}"

    def test_no_vars_passthrough(self):
        result = resolve_string("just a plain string")
        assert result == "just a plain string"

    def test_mixed_resolved_and_unresolved(self):
        result = resolve_string("{{$randomEmail}} and {{$unknownThing}}")
        assert "@" in result
        assert "{{$unknownThing}}" in result

    def test_whitespace_in_braces(self):
        result = resolve_string("{{ $guid }}")
        uuid.UUID(result)

    def test_random_boolean(self):
        result = resolve_string("{{$randomBoolean}}")
        assert result in ("True", "False")

    def test_random_url(self):
        result = resolve_string("{{$randomUrl}}")
        assert result.startswith("http")

    def test_random_ip(self):
        result = resolve_string("{{$randomIP}}")
        parts = result.split(".")
        assert len(parts) == 4

    def test_random_date(self):
        result = resolve_string("{{$randomDate}}")
        assert re.match(r"\d{4}-\d{2}-\d{2}", result)

    def test_random_company(self):
        result = resolve_string("{{$randomCompany}}")
        assert len(result) > 0

    def test_random_city(self):
        result = resolve_string("{{$randomCity}}")
        assert len(result) > 0


class TestResolveValue:
    def test_string(self):
        result = resolve_value("email: {{$randomEmail}}")
        assert "@" in result

    def test_dict(self):
        data = {
            "name": "{{$randomName}}",
            "email": "{{$randomEmail}}",
            "static": "hello",
        }
        result = resolve_value(data)
        assert isinstance(result, dict)
        assert "@" in result["email"]
        assert " " in result["name"]
        assert result["static"] == "hello"

    def test_list(self):
        data = ["{{$guid}}", "{{$randomEmail}}", "plain"]
        result = resolve_value(data)
        assert isinstance(result, list)
        uuid.UUID(result[0])
        assert "@" in result[1]
        assert result[2] == "plain"

    def test_nested_dict(self):
        data = {
            "user": {
                "name": "{{$randomName}}",
                "contacts": ["{{$randomEmail}}"],
            }
        }
        result = resolve_value(data)
        assert "@" in result["user"]["contacts"][0]
        assert " " in result["user"]["name"]

    def test_non_string_passthrough(self):
        assert resolve_value(42) == 42
        assert resolve_value(True) is True
        assert resolve_value(None) is None
        assert resolve_value(3.14) == 3.14

    def test_empty_dict(self):
        assert resolve_value({}) == {}

    def test_empty_list(self):
        assert resolve_value([]) == []


class TestListVariables:
    def test_returns_list(self):
        result = list_variables()
        assert isinstance(result, list)
        assert len(result) > 10

    def test_each_has_required_keys(self):
        for var in list_variables():
            assert "name" in var
            assert "aliases" in var
            assert "example" in var

    def test_guid_in_list(self):
        names = [v["name"] for v in list_variables()]
        assert "guid" in names

    def test_examples_are_non_empty(self):
        for var in list_variables():
            assert len(var["example"]) > 0, f"Empty example for {var['name']}"


class TestAliases:
    """Verify that common alias patterns all resolve."""

    def test_uuid_alias(self):
        result = resolve_string("{{$uuid}}")
        uuid.UUID(result)

    def test_random_guid_alias(self):
        result = resolve_string("{{$random_guid}}")
        uuid.UUID(result)

    def test_random_email_underscore(self):
        result = resolve_string("{{$random_email}}")
        assert "@" in result

    def test_random_int_underscore(self):
        result = resolve_string("{{$random_int}}")
        assert result.isdigit()

    def test_now_alias(self):
        result = resolve_string("{{$now}}")
        assert "T" in result
