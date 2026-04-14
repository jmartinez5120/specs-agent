"""Tests for the test plan generator."""

import json

import yaml

from specs_agent.parsing.extractor import extract_spec
from specs_agent.parsing.plan_generator import generate_plan


def _load_json(path):
    with open(path) as f:
        return json.load(f)


def _load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


class TestPlanGeneration:
    def test_plan_name(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        assert plan.name == "Petstore Test Plan"
        assert plan.spec_title == "Petstore"

    def test_base_url(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        assert plan.base_url == "https://petstore.example.com/v1"

    def test_custom_base_url(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec, base_url="http://localhost:3000")
        assert plan.base_url == "http://localhost:3000"

    def test_test_cases_generated(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        # Each endpoint+response combo gets a test case
        assert plan.total_count > 0
        assert plan.total_count >= len(spec.endpoints)

    def test_success_cases_enabled_by_default(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        for tc in plan.test_cases:
            # Parse expected status from assertions
            status_assertions = [a for a in tc.assertions if a.type.value == "status_code"]
            if status_assertions:
                code = status_assertions[0].expected
                if 200 <= code < 300:
                    assert tc.enabled, f"2xx case should be enabled: {tc.name}"
                else:
                    assert not tc.enabled, f"Non-2xx case should be disabled: {tc.name}"

    def test_status_code_assertion_present(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        for tc in plan.test_cases:
            types = [a.type.value for a in tc.assertions]
            assert "status_code" in types, f"Missing status_code assertion: {tc.name}"

    def test_schema_assertion_for_success(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        # GET /pets -> 200 should have schema assertion (since response has schema)
        get_pets_200 = [
            tc for tc in plan.test_cases
            if tc.endpoint_path == "/pets" and tc.method == "GET"
            and any(a.expected == 200 for a in tc.assertions if a.type.value == "status_code")
        ]
        assert len(get_pets_200) == 1
        schema_asserts = [a for a in get_pets_200[0].assertions if a.type.value == "response_schema"]
        assert len(schema_asserts) == 1

    def test_path_params_placeholder(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        get_pet = [
            tc for tc in plan.test_cases
            if tc.endpoint_path == "/pets/{petId}" and tc.method == "GET"
        ]
        assert len(get_pet) > 0
        # Path param should have a placeholder
        assert "petId" in get_pet[0].path_params
        # Faker template vars (e.g. {{$guid}}) are auto-resolved, so needs_input is False
        assert get_pet[0].needs_input is False

    def test_post_body_generated(self, petstore_v3_path):
        raw = _load_json(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        post_pet_success = [
            tc for tc in plan.test_cases
            if tc.endpoint_path == "/pets" and tc.method == "POST" and tc.enabled
        ]
        assert len(post_pet_success) == 1
        # Body is generated from schema (may be empty dict if $ref unresolved)
        assert post_pet_success[0].body is not None

    def test_post_body_with_resolved_refs(self, petstore_v3_path):
        """When loaded via prance (which resolves $ref), body should have properties."""
        from specs_agent.parsing.loader import load_spec
        raw = load_spec(petstore_v3_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        post_pet_success = [
            tc for tc in plan.test_cases
            if tc.endpoint_path == "/pets" and tc.method == "POST" and tc.enabled
        ]
        assert len(post_pet_success) == 1
        assert post_pet_success[0].body is not None
        assert "name" in post_pet_success[0].body

    def test_minimal_spec(self, minimal_spec_path):
        raw = _load_yaml(minimal_spec_path)
        spec = extract_spec(raw)
        plan = generate_plan(spec)
        # 1 happy path + negative cases
        assert plan.total_count >= 1
        assert plan.test_cases[0].method == "GET"
        assert plan.test_cases[0].endpoint_path == "/health"
        assert plan.enabled_count == 1  # Only happy path enabled
