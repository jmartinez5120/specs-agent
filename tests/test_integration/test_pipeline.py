"""Integration tests — full pipeline from spec loading through plan generation."""

from pathlib import Path

from specs_agent.parsing.extractor import extract_spec
from specs_agent.parsing.loader import load_spec
from specs_agent.parsing.plan_generator import generate_plan

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestV3Pipeline:
    """Full pipeline with OpenAPI v3 spec."""

    def test_load_extract_generate(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        # Spec parsed correctly
        assert spec.title == "Petstore"
        assert spec.version == "1.0.0"
        assert len(spec.endpoints) == 5

        # Plan generated correctly
        assert plan.name == "Petstore Test Plan"
        assert plan.base_url == "https://petstore.example.com/v1"
        assert plan.total_count > 0

    def test_refs_resolved_end_to_end(self):
        """$ref pointers should be resolved by prance, so schemas are inlined."""
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        spec = extract_spec(raw)

        # POST /pets should have a resolved request body schema
        post_pets = [
            e for e in spec.endpoints
            if e.path == "/pets" and e.method.value == "POST"
        ][0]
        assert post_pets.request_body_schema is not None
        assert post_pets.request_body_schema.get("type") == "object"
        assert "name" in post_pets.request_body_schema.get("properties", {})

    def test_plan_body_has_resolved_properties(self):
        """Plan's generated body for POST should have actual properties from resolved schema."""
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        post_cases = [
            tc for tc in plan.test_cases
            if tc.endpoint_path == "/pets" and tc.method == "POST" and tc.enabled
        ]
        assert len(post_cases) == 1
        body = post_cases[0].body
        assert body is not None
        assert "name" in body

    def test_all_endpoints_have_test_cases(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        # Every endpoint should have at least one test case
        endpoint_paths = {(e.path, e.method.value) for e in spec.endpoints}
        case_paths = {(tc.endpoint_path, tc.method) for tc in plan.test_cases}
        for ep in endpoint_paths:
            assert ep in case_paths, f"No test case for {ep[1]} {ep[0]}"

    def test_success_cases_have_schema_assertions(self):
        """2xx responses with schemas should get schema validation assertions."""
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        # GET /pets -> 200 has a response schema
        get_pets_200 = [
            tc for tc in plan.test_cases
            if tc.endpoint_path == "/pets" and tc.method == "GET"
            and any(a.expected == 200 for a in tc.assertions if a.type.value == "status_code")
        ]
        assert len(get_pets_200) == 1
        schema_asserts = [a for a in get_pets_200[0].assertions if a.type.value == "response_schema"]
        assert len(schema_asserts) == 1
        # Schema should be resolved (not a $ref)
        assert schema_asserts[0].expected.get("type") == "array"

    def test_path_params_have_faker_placeholders(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        # Get happy-path cases for pet by ID
        pet_by_id_cases = [
            tc for tc in plan.test_cases
            if tc.endpoint_path == "/pets/{petId}" and tc.enabled
        ]
        assert len(pet_by_id_cases) > 0
        for tc in pet_by_id_cases:
            assert "petId" in tc.path_params
            assert tc.needs_input is False
            assert "{{" in tc.path_params["petId"]

    def test_custom_base_url_override(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v3.json"))
        spec = extract_spec(raw)
        plan = generate_plan(spec, base_url="http://localhost:3000")
        assert plan.base_url == "http://localhost:3000"


class TestV2Pipeline:
    """Full pipeline with Swagger 2.0 spec."""

    def test_load_extract_generate(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v2.yaml"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        assert spec.title == "Petstore"
        assert spec.spec_version == "2.0"
        assert spec.base_url == "https://petstore.example.com/v1"
        assert len(spec.endpoints) == 4
        assert plan.total_count > 0

    def test_v2_body_param_resolved(self):
        """Swagger 2.0 body parameters should become request_body_schema."""
        raw = load_spec(str(FIXTURES_DIR / "petstore_v2.yaml"))
        spec = extract_spec(raw)

        post_pets = [
            e for e in spec.endpoints
            if e.path == "/pets" and e.method.value == "POST"
        ][0]
        assert post_pets.request_body_schema is not None
        # Body params should not be in the parameters list
        body_params = [p for p in post_pets.parameters if p.location.value == "body"]
        assert len(body_params) == 0

    def test_v2_server_url_constructed(self):
        raw = load_spec(str(FIXTURES_DIR / "petstore_v2.yaml"))
        spec = extract_spec(raw)
        assert len(spec.servers) == 1
        assert "petstore.example.com" in spec.servers[0].url


class TestMinimalPipeline:
    """Pipeline with minimal spec (no params, no body, no schemas)."""

    def test_minimal_end_to_end(self):
        raw = load_spec(str(FIXTURES_DIR / "minimal_spec.yaml"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        assert spec.title == "Minimal API"
        assert len(spec.endpoints) == 1
        assert plan.total_count >= 1  # Happy path + negative cases
        assert plan.enabled_count == 1  # Only happy path enabled

        tc = plan.test_cases[0]
        assert tc.method == "GET"
        assert tc.endpoint_path == "/health"
        assert tc.enabled is True
        assert tc.needs_input is False
        assert tc.body is None
        assert tc.path_params == {}
        assert tc.query_params == {}

    def test_minimal_has_status_assertion(self):
        raw = load_spec(str(FIXTURES_DIR / "minimal_spec.yaml"))
        spec = extract_spec(raw)
        plan = generate_plan(spec)

        tc = plan.test_cases[0]
        status_asserts = [a for a in tc.assertions if a.type.value == "status_code"]
        assert len(status_asserts) == 1
        assert status_asserts[0].expected == 200


class TestEdgeCases:
    """Edge cases and robustness."""

    def test_spec_with_no_responses(self, tmp_path):
        """An endpoint with no responses should get a smoke test + negative cases."""
        spec_data = {
            "openapi": "3.0.0",
            "info": {"title": "No Responses", "version": "1.0"},
            "paths": {
                "/ping": {
                    "get": {
                        "summary": "Ping",
                        "responses": {},
                    }
                }
            },
        }

        spec = extract_spec(spec_data)
        plan = generate_plan(spec)

        assert plan.total_count >= 1
        assert "smoke test" in plan.test_cases[0].name
        assert plan.test_cases[0].enabled is True

    def test_spec_with_multiple_tags_per_endpoint(self, tmp_path):
        spec_data = {
            "openapi": "3.0.0",
            "info": {"title": "Multi Tag", "version": "1.0"},
            "paths": {
                "/items": {
                    "get": {
                        "tags": ["items", "search"],
                        "summary": "List items",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec = extract_spec(spec_data)
        by_tag = spec.endpoints_by_tag
        assert "items" in by_tag
        assert "search" in by_tag
        # Same endpoint in both tags
        assert by_tag["items"][0] is by_tag["search"][0]

    def test_all_http_methods_supported(self, tmp_path):
        paths = {}
        for method in ["get", "post", "put", "patch", "delete", "options", "head"]:
            paths.setdefault("/test", {})[method] = {
                "summary": f"Test {method}",
                "responses": {"200": {"description": "OK"}},
            }
        spec_data = {
            "openapi": "3.0.0",
            "info": {"title": "All Methods", "version": "1.0"},
            "paths": paths,
        }
        spec = extract_spec(spec_data)
        methods = {e.method.value for e in spec.endpoints}
        assert methods == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}

    def test_enum_parameters(self):
        spec_data = {
            "openapi": "3.0.0",
            "info": {"title": "Enum Test", "version": "1.0"},
            "paths": {
                "/items": {
                    "get": {
                        "parameters": [
                            {
                                "name": "sort",
                                "in": "query",
                                "required": True,
                                "schema": {
                                    "type": "string",
                                    "enum": ["asc", "desc"],
                                },
                            }
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        spec = extract_spec(spec_data)
        plan = generate_plan(spec)
        tc = plan.test_cases[0]
        # Required enum query param should use first enum value
        assert tc.query_params.get("sort") == "asc"

    def test_plan_generation_with_nested_schema(self):
        spec_data = {
            "openapi": "3.0.0",
            "info": {"title": "Nested", "version": "1.0"},
            "paths": {
                "/orders": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["items"],
                                        "properties": {
                                            "items": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "id": {"type": "integer"},
                                                        "qty": {"type": "integer"},
                                                    },
                                                },
                                            },
                                            "note": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {"201": {"description": "Created"}},
                    }
                }
            },
        }
        spec = extract_spec(spec_data)
        plan = generate_plan(spec)
        post_case = [tc for tc in plan.test_cases if tc.enabled][0]
        assert post_case.body is not None
        assert "items" in post_case.body
        assert isinstance(post_case.body["items"], list)
