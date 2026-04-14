"""Tests for the spec extractor."""

import json

import yaml

from specs_agent.parsing.extractor import extract_spec


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


class TestExtractV3:
    def test_basic_info(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        assert spec.title == "Petstore"
        assert spec.version == "1.0.0"
        assert spec.spec_version == "3.0.3"

    def test_servers(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        assert len(spec.servers) == 1
        assert spec.servers[0].url == "https://petstore.example.com/v1"

    def test_endpoints_count(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        # GET /pets, POST /pets, GET /pets/{petId}, DELETE /pets/{petId}, GET /store/inventory
        assert len(spec.endpoints) == 5

    def test_endpoint_parameters(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        # Find GET /pets
        get_pets = [e for e in spec.endpoints if e.path == "/pets" and e.method.value == "GET"][0]
        assert len(get_pets.parameters) == 2
        limit_param = [p for p in get_pets.parameters if p.name == "limit"][0]
        assert limit_param.schema_type == "integer"
        assert limit_param.required is False

    def test_endpoint_responses(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        get_pets = [e for e in spec.endpoints if e.path == "/pets" and e.method.value == "GET"][0]
        assert len(get_pets.responses) == 2
        codes = {r.status_code for r in get_pets.responses}
        assert codes == {200, 500}

    def test_request_body(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        post_pets = [e for e in spec.endpoints if e.path == "/pets" and e.method.value == "POST"][0]
        assert post_pets.request_body_schema is not None
        # Without prance resolution, $ref is preserved
        assert "$ref" in post_pets.request_body_schema or post_pets.request_body_schema.get("type") == "object"

    def test_tags(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        assert "pets" in spec.tags
        assert "store" in spec.tags

    def test_endpoints_by_tag(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        by_tag = spec.endpoints_by_tag
        assert "pets" in by_tag
        assert len(by_tag["pets"]) == 4
        assert len(by_tag["store"]) == 1


class TestExtractV2:
    def test_basic_info(self, petstore_v2_path):
        raw = _load_yaml(petstore_v2_path)
        spec = extract_spec(raw)
        assert spec.title == "Petstore"
        assert spec.version == "1.0.0"
        assert spec.spec_version == "2.0"

    def test_servers_from_host(self, petstore_v2_path):
        raw = _load_yaml(petstore_v2_path)
        spec = extract_spec(raw)
        assert len(spec.servers) == 1
        assert spec.servers[0].url == "https://petstore.example.com/v1"

    def test_endpoints_count(self, petstore_v2_path):
        raw = _load_yaml(petstore_v2_path)
        spec = extract_spec(raw)
        assert len(spec.endpoints) == 4  # v2 fixture has 4 endpoints

    def test_body_param_becomes_request_body(self, petstore_v2_path):
        raw = _load_yaml(petstore_v2_path)
        spec = extract_spec(raw)
        post_pets = [e for e in spec.endpoints if e.path == "/pets" and e.method.value == "POST"][0]
        assert post_pets.request_body_schema is not None
        # Body params should NOT appear in parameters list
        body_params = [p for p in post_pets.parameters if p.location.value == "body"]
        assert len(body_params) == 0


class TestExtractMinimal:
    def test_minimal_spec(self, minimal_spec_path):
        raw = _load_yaml(minimal_spec_path)
        spec = extract_spec(raw)
        assert spec.title == "Minimal API"
        assert len(spec.endpoints) == 1
        assert spec.endpoints[0].path == "/health"
        assert spec.endpoints[0].method.value == "GET"
