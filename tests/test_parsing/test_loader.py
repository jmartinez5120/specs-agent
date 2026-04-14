"""Unit tests for the spec loader."""

import json
from pathlib import Path

import pytest
import yaml

from specs_agent.parsing.loader import SpecLoadError, load_spec, load_spec_raw


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestLoadSpec:
    def test_load_v3_json(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        assert "openapi" in raw
        assert raw["info"]["title"] == "Petstore"

    def test_load_v2_yaml(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v2.yaml"))
        assert "swagger" in raw
        assert raw["info"]["title"] == "Petstore"

    def test_load_minimal(self):
        raw = load_spec(str(FIXTURES_DIR / "minimal_spec.yaml"))
        assert raw["info"]["title"] == "Minimal API"

    def test_refs_resolved(self):
        """Prance should resolve all $ref pointers."""
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        # After resolution, the response schema should be inlined
        pets_path = raw["paths"]["/pets"]["get"]
        resp_200 = pets_path["responses"]["200"]
        schema = resp_200["content"]["application/json"]["schema"]
        # Should be resolved — items should have properties, not $ref
        assert "$ref" not in schema.get("items", {})

    def test_load_missing_file(self):
        with pytest.raises(SpecLoadError, match="File not found"):
            load_spec("/nonexistent/path/to/spec.yaml")

    def test_load_invalid_spec_falls_back(self, tmp_path):
        """Incomplete spec (missing paths) should still load via fallback."""
        bad_spec = tmp_path / "bad.yaml"
        bad_spec.write_text("openapi: '3.0.0'\ninfo:\n  title: Bad\n")
        raw = load_spec(str(bad_spec))
        assert raw["info"]["title"] == "Bad"

    def test_load_not_yaml_at_all(self, tmp_path):
        bad_file = tmp_path / "garbage.yaml"
        bad_file.write_text("this is not yaml: [[[{{{")
        with pytest.raises(SpecLoadError):
            load_spec(str(bad_file))

    def test_load_expanduser(self):
        """Source with ~ should be expanded."""
        # This will fail with SpecLoadError (file not found), not a path error
        with pytest.raises(SpecLoadError):
            load_spec("~/nonexistent_spec.yaml")


class TestLoadSpecRaw:
    def test_load_json(self):
        raw = load_spec_raw(str(FIXTURES_DIR / "petstore_v3.json"))
        assert raw["info"]["title"] == "Petstore"
        # Raw load preserves $ref
        post_body = raw["paths"]["/pets"]["post"]["requestBody"]
        schema = post_body["content"]["application/json"]["schema"]
        assert "$ref" in schema

    def test_load_yaml(self):
        raw = load_spec_raw(str(FIXTURES_DIR / "petstore_v2.yaml"))
        assert raw["info"]["title"] == "Petstore"

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_spec_raw("/nonexistent/file.yaml")
