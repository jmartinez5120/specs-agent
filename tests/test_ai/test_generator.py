"""Unit tests for the AI generator — classification, mocked inference, fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from specs_agent.ai.generator import AIGenerator


# ------------------------------------------------------------------ #
# Classification: should_use_ai
# ------------------------------------------------------------------ #


class TestShouldUseAI:
    """Verify the two-tier classification logic."""

    def test_faker_for_email_format(self) -> None:
        assert AIGenerator.should_use_ai("x", {"type": "string", "format": "email"}) is False

    def test_faker_for_date_format(self) -> None:
        assert AIGenerator.should_use_ai("x", {"type": "string", "format": "date-time"}) is False

    def test_faker_for_uuid_format(self) -> None:
        assert AIGenerator.should_use_ai("x", {"type": "string", "format": "uuid"}) is False

    def test_faker_for_known_name_email(self) -> None:
        assert AIGenerator.should_use_ai("email", {"type": "string"}) is False

    def test_faker_for_known_name_city(self) -> None:
        assert AIGenerator.should_use_ai("city", {"type": "string"}) is False

    def test_faker_for_known_name_id(self) -> None:
        assert AIGenerator.should_use_ai("id", {"type": "string"}) is False

    def test_faker_for_boolean_no_desc(self) -> None:
        assert AIGenerator.should_use_ai("active", {"type": "boolean"}) is False

    def test_faker_for_integer_no_desc(self) -> None:
        assert AIGenerator.should_use_ai("count", {"type": "integer"}) is False

    def test_ai_for_enum(self) -> None:
        assert AIGenerator.should_use_ai("status", {
            "type": "string",
            "enum": ["PLANNED", "LAUNCHING", "IN_FLIGHT"],
        }) is True

    def test_ai_for_described_string(self) -> None:
        assert AIGenerator.should_use_ai("callsign", {
            "type": "string",
            "description": "Aircraft callsign in ICAO format (e.g. UAL123)",
        }) is True

    def test_ai_for_nontrivial_name(self) -> None:
        assert AIGenerator.should_use_ai("mission_objective", {"type": "string"}) is True

    def test_faker_for_short_desc_boolean(self) -> None:
        assert AIGenerator.should_use_ai("flag", {
            "type": "boolean",
            "description": "A flag",
        }) is False

    def test_ai_for_integer_with_long_desc(self) -> None:
        assert AIGenerator.should_use_ai("priority", {
            "type": "integer",
            "description": "Priority level from 1 (critical) to 5 (low)",
        }) is True

    def test_case_insensitive_name_match(self) -> None:
        assert AIGenerator.should_use_ai("Email", {"type": "string"}) is False
        assert AIGenerator.should_use_ai("EMAIL", {"type": "string"}) is False

    def test_underscore_name_match(self) -> None:
        assert AIGenerator.should_use_ai("first_name", {"type": "string"}) is False
        assert AIGenerator.should_use_ai("street_address", {"type": "string"}) is False


# ------------------------------------------------------------------ #
# Availability checks
# ------------------------------------------------------------------ #


class TestAvailability:
    def test_llama_cpp_available_when_not_installed(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "specs_agent.ai.generator.AIGenerator.llama_cpp_available",
            staticmethod(lambda: False),
        )
        gen = AIGenerator()
        assert gen.is_available() is False

    def test_not_available_without_model_file(self) -> None:
        gen = AIGenerator(model_path="/nonexistent/model.gguf")
        # Even if llama_cpp is importable, no model file → not available
        assert gen.resolved_model_path is None

    def test_status_dict_shape(self) -> None:
        gen = AIGenerator()
        s = gen.status()
        assert "llama_cpp_installed" in s
        assert "model_found" in s
        assert "model_loaded" in s
        assert "cache" in s
        assert isinstance(s["cache"], dict)


# ------------------------------------------------------------------ #
# Mocked inference
# ------------------------------------------------------------------ #


class TestMockedInference:
    @pytest.fixture
    def gen(self, tmp_path: Path) -> AIGenerator:
        g = AIGenerator(cache_dir=str(tmp_path / "cache"))
        # Inject a mock model that echoes back the requested field names
        # with plausible values based on what the prompt asked for.
        mock_model = MagicMock()

        def mock_completion(**kwargs):
            # Parse the prompt to extract field names, return matching JSON
            import re, json as _json
            msgs = kwargs.get("messages", [])
            user_msg = msgs[-1]["content"] if msgs else ""
            # Extract field names from the prompt pattern: "field_name": <value>
            names = re.findall(r'"(\w+)":\s*<value>', user_msg)
            if not names:
                names = re.findall(r'^- "(\w+)"', user_msg, re.MULTILINE)
            values = {}
            for n in names:
                if n == "status":
                    values[n] = "IN_FLIGHT"
                elif n == "notes":
                    values[n] = "Orbit insertion confirmed"
                else:
                    values[n] = f"generated_{n}"
            return {
                "choices": [{"message": {"content": _json.dumps(values)}}]
            }

        mock_model.create_chat_completion.side_effect = mock_completion
        g._model = mock_model
        g._load_attempted = True
        return g

    def test_generate_for_endpoint_returns_dict(self, gen: AIGenerator) -> None:
        fields = [
            {"name": "status", "type": "string", "description": "Mission status", "enum": ["PLANNED", "IN_FLIGHT"]},
            {"name": "notes", "type": "string", "description": "Status notes"},
        ]
        result = gen.generate_for_endpoint(fields, "PUT", "/missions/{id}/status", "Update mission")
        assert result == {"status": "IN_FLIGHT", "notes": "Orbit insertion confirmed"}

    def test_result_is_cached(self, gen: AIGenerator) -> None:
        fields = [{"name": "x", "type": "string", "description": "A domain field"}]
        gen.generate_for_endpoint(fields, "GET", "/test")

        # Second call should hit cache (model NOT called again)
        gen._model.create_chat_completion.reset_mock()
        result = gen.generate_for_endpoint(fields, "GET", "/test")
        gen._model.create_chat_completion.assert_not_called()
        assert result  # got cached value

    def test_empty_fields_returns_empty(self, gen: AIGenerator) -> None:
        assert gen.generate_for_endpoint([], "GET", "/x") == {}

    def test_inference_failure_returns_empty(self, gen: AIGenerator) -> None:
        gen._model.create_chat_completion.side_effect = RuntimeError("OOM")
        fields = [{"name": "x", "type": "string", "description": "test field"}]
        result = gen.generate_for_endpoint(fields, "GET", "/x")
        assert result == {}

    def test_unparseable_response_returns_empty(self, gen: AIGenerator) -> None:
        # Use side_effect override to return garbage for THIS specific call
        gen._model.create_chat_completion.side_effect = lambda **kw: {
            "choices": [{"message": {"content": "I don't understand the question"}}]
        }
        # Use a unique endpoint so we don't hit cache from prior tests
        fields = [{"name": "zzz", "type": "string", "description": "unique field for this test"}]
        result = gen.generate_for_endpoint(fields, "GET", "/unparseable-test")
        assert result == {}


# ------------------------------------------------------------------ #
# Fallback chain
# ------------------------------------------------------------------ #


class TestFallbackChain:
    def test_no_model_returns_empty(self, tmp_path: Path) -> None:
        gen = AIGenerator(model_path="/nonexistent", cache_dir=str(tmp_path / "cache"))
        fields = [{"name": "x", "type": "string", "description": "test"}]
        result = gen.generate_for_endpoint(fields, "GET", "/x")
        assert result == {}
        assert gen._load_error != ""

    def test_load_attempted_only_once(self, tmp_path: Path) -> None:
        gen = AIGenerator(model_path="/nonexistent", cache_dir=str(tmp_path / "cache"))
        fields = [{"name": "x", "type": "string", "description": "test"}]
        gen.generate_for_endpoint(fields, "GET", "/a")
        gen.generate_for_endpoint(fields, "GET", "/b")
        # _load_attempted is True after the first call — the second call
        # doesn't re-attempt the load
        assert gen._load_attempted is True
        assert gen._model is None
