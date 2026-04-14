"""Unit tests for plan data models."""

from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan


class TestAssertionType:
    def test_all_types(self):
        types = [t.value for t in AssertionType]
        assert "status_code" in types
        assert "response_schema" in types
        assert "response_contains" in types
        assert "header_present" in types
        assert "header_value" in types
        assert "response_time_ms" in types

    def test_from_string(self):
        assert AssertionType("status_code") is AssertionType.STATUS_CODE


class TestAssertion:
    def test_basic(self):
        a = Assertion(type=AssertionType.STATUS_CODE, expected=200)
        assert a.type == AssertionType.STATUS_CODE
        assert a.expected == 200
        assert a.description == ""

    def test_with_description(self):
        a = Assertion(
            type=AssertionType.RESPONSE_TIME_MS,
            expected=500,
            description="Must respond within 500ms",
        )
        assert a.description == "Must respond within 500ms"

    def test_schema_assertion(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        a = Assertion(type=AssertionType.RESPONSE_SCHEMA, expected=schema)
        assert a.expected["type"] == "object"


class TestTestCase:
    def test_auto_generated_id(self):
        tc1 = TestCase()
        tc2 = TestCase()
        assert tc1.id != tc2.id
        assert len(tc1.id) == 8

    def test_display_name_with_name(self):
        tc = TestCase(name="Get all pets", endpoint_path="/pets", method="GET")
        assert tc.display_name == "Get all pets"

    def test_display_name_fallback(self):
        tc = TestCase(endpoint_path="/pets", method="GET")
        assert tc.display_name == "GET /pets"

    def test_defaults(self):
        tc = TestCase()
        assert tc.endpoint_path == ""
        assert tc.method == "GET"
        assert tc.enabled is True
        assert tc.path_params == {}
        assert tc.query_params == {}
        assert tc.headers == {}
        assert tc.body is None
        assert tc.assertions == []
        assert tc.depends_on is None
        assert tc.needs_input is False

    def test_mutable_defaults_isolated(self):
        """Ensure mutable defaults don't leak between instances."""
        tc1 = TestCase()
        tc2 = TestCase()
        tc1.path_params["id"] = "123"
        assert tc2.path_params == {}
        tc1.assertions.append(
            Assertion(type=AssertionType.STATUS_CODE, expected=200)
        )
        assert tc2.assertions == []


class TestTestPlan:
    def _make_plan(self, cases=None):
        return TestPlan(
            name="Test Plan",
            spec_title="API",
            base_url="http://localhost",
            test_cases=cases or [],
        )

    def test_empty_plan(self):
        plan = self._make_plan()
        assert plan.total_count == 0
        assert plan.enabled_count == 0
        assert plan.needs_input_count == 0
        assert plan.enabled_cases == []

    def test_total_count(self):
        cases = [TestCase(), TestCase(), TestCase()]
        plan = self._make_plan(cases)
        assert plan.total_count == 3

    def test_enabled_count(self):
        cases = [
            TestCase(enabled=True),
            TestCase(enabled=False),
            TestCase(enabled=True),
        ]
        plan = self._make_plan(cases)
        assert plan.enabled_count == 2
        assert len(plan.enabled_cases) == 2

    def test_needs_input_count(self):
        cases = [
            TestCase(needs_input=True),
            TestCase(needs_input=False),
            TestCase(needs_input=True),
        ]
        plan = self._make_plan(cases)
        assert plan.needs_input_count == 2

    def test_enabled_cases_returns_correct_subset(self):
        tc_on = TestCase(enabled=True, name="enabled")
        tc_off = TestCase(enabled=False, name="disabled")
        plan = self._make_plan([tc_on, tc_off])
        enabled = plan.enabled_cases
        assert len(enabled) == 1
        assert enabled[0].name == "enabled"

    def test_auth_defaults(self):
        plan = self._make_plan()
        assert plan.auth_type == "none"
        assert plan.auth_value == ""
        assert plan.global_headers == {}
