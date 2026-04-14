"""Tests for plan save/load."""

from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan
from specs_agent.persistence import load_plan, save_plan


def _make_plan() -> TestPlan:
    return TestPlan(
        name="Test Plan",
        spec_title="API",
        base_url="https://api.example.com",
        created_at="2026-04-09T00:00:00",
        auth_type="bearer",
        auth_value="secret",
        global_headers={"X-Custom": "value"},
        test_cases=[
            TestCase(
                id="tc1",
                endpoint_path="/pets",
                method="GET",
                name="List pets",
                enabled=True,
                query_params={"limit": "10"},
                assertions=[
                    Assertion(type=AssertionType.STATUS_CODE, expected=200, description="OK"),
                ],
            ),
            TestCase(
                id="tc2",
                endpoint_path="/pets/{petId}",
                method="GET",
                name="Get pet",
                enabled=False,
                path_params={"petId": "{{$guid}}"},
                needs_input=True,
                assertions=[
                    Assertion(type=AssertionType.STATUS_CODE, expected=200),
                    Assertion(type=AssertionType.RESPONSE_SCHEMA, expected={"type": "object"}),
                ],
            ),
        ],
    )


class TestSaveLoad:
    def test_roundtrip(self, tmp_path):
        plan = _make_plan()
        path = str(tmp_path / "plan.yaml")
        save_plan(plan, path)
        loaded = load_plan(path)

        assert loaded.name == plan.name
        assert loaded.spec_title == plan.spec_title
        assert loaded.base_url == plan.base_url
        assert loaded.auth_type == plan.auth_type
        assert loaded.auth_value == plan.auth_value
        assert loaded.global_headers == plan.global_headers
        assert len(loaded.test_cases) == 2

    def test_test_case_fields(self, tmp_path):
        plan = _make_plan()
        path = str(tmp_path / "plan.yaml")
        save_plan(plan, path)
        loaded = load_plan(path)

        tc1 = loaded.test_cases[0]
        assert tc1.id == "tc1"
        assert tc1.endpoint_path == "/pets"
        assert tc1.method == "GET"
        assert tc1.enabled is True
        assert tc1.query_params == {"limit": "10"}

        tc2 = loaded.test_cases[1]
        assert tc2.enabled is False
        assert tc2.needs_input is True
        assert tc2.path_params == {"petId": "{{$guid}}"}

    def test_assertions_preserved(self, tmp_path):
        plan = _make_plan()
        path = str(tmp_path / "plan.yaml")
        save_plan(plan, path)
        loaded = load_plan(path)

        tc1 = loaded.test_cases[0]
        assert len(tc1.assertions) == 1
        assert tc1.assertions[0].type == AssertionType.STATUS_CODE
        assert tc1.assertions[0].expected == 200
        assert tc1.assertions[0].description == "OK"

        tc2 = loaded.test_cases[1]
        assert len(tc2.assertions) == 2
        assert tc2.assertions[1].type == AssertionType.RESPONSE_SCHEMA
        assert tc2.assertions[1].expected == {"type": "object"}

    def test_file_is_readable_yaml(self, tmp_path):
        import yaml
        plan = _make_plan()
        path = str(tmp_path / "plan.yaml")
        save_plan(plan, path)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert data["name"] == "Test Plan"
        assert len(data["test_cases"]) == 2
