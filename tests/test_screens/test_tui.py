"""TUI screen tests using Textual's app testing pilot."""

from pathlib import Path

import pytest

from textual.widgets import Button, DataTable, Input, Static

from specs_agent.app import SpecsAgentApp
from specs_agent.models.plan import Assertion, AssertionType, TestCase, TestPlan
from specs_agent.models.spec import (
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    ParsedSpec,
    ResponseSpec,
    ServerInfo,
)
from specs_agent.screens.plan_editor import PlanEditorScreen
from specs_agent.screens.spec_browser import SpecBrowserScreen
from specs_agent.screens.welcome import WelcomeScreen
from specs_agent.widgets.endpoint_tree import EndpointTree


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _make_spec() -> ParsedSpec:
    """Create a minimal ParsedSpec for testing."""
    return ParsedSpec(
        title="Test API",
        version="1.0",
        servers=[ServerInfo(url="https://test.example.com/v1")],
        endpoints=[
            Endpoint(
                path="/items",
                method=HttpMethod.GET,
                operation_id="listItems",
                summary="List items",
                tags=["items"],
                parameters=[
                    Parameter(
                        name="limit",
                        location=ParameterLocation.QUERY,
                        required=False,
                        schema_type="integer",
                    )
                ],
                responses=[
                    ResponseSpec(status_code=200, description="OK"),
                    ResponseSpec(status_code=500, description="Error"),
                ],
            ),
            Endpoint(
                path="/items/{id}",
                method=HttpMethod.GET,
                operation_id="getItem",
                summary="Get item by ID",
                tags=["items"],
                parameters=[
                    Parameter(
                        name="id",
                        location=ParameterLocation.PATH,
                        required=True,
                        schema_type="string",
                    )
                ],
                responses=[
                    ResponseSpec(status_code=200, description="OK"),
                ],
            ),
        ],
        tags=["items"],
    )


def _make_plan() -> TestPlan:
    """Create a minimal TestPlan for testing."""
    return TestPlan(
        name="Test Plan",
        spec_title="Test API",
        base_url="https://test.example.com/v1",
        test_cases=[
            TestCase(
                id="tc001",
                endpoint_path="/items",
                method="GET",
                name="GET /items -> 200",
                enabled=True,
                assertions=[
                    Assertion(type=AssertionType.STATUS_CODE, expected=200),
                ],
            ),
            TestCase(
                id="tc002",
                endpoint_path="/items",
                method="GET",
                name="GET /items -> 500",
                enabled=False,
                assertions=[
                    Assertion(type=AssertionType.STATUS_CODE, expected=500),
                ],
            ),
            TestCase(
                id="tc003",
                endpoint_path="/items/{id}",
                method="GET",
                name="GET /items/{id} -> 200",
                enabled=True,
                needs_input=True,
                path_params={"id": "<id>"},
                assertions=[
                    Assertion(type=AssertionType.STATUS_CODE, expected=200),
                ],
            ),
        ],
    )


class TestWelcomeScreen:
    @pytest.mark.asyncio
    async def test_welcome_screen_renders(self):
        """WelcomeScreen should render with expected widgets."""
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Should start on the WelcomeScreen
            screen = app.screen
            assert isinstance(screen, WelcomeScreen)
            # Should have the input and button
            inp = screen.query_one("#spec-input", Input)
            assert inp is not None
            btn = screen.query_one("#load-button", Button)
            assert btn is not None

    @pytest.mark.asyncio
    async def test_welcome_screen_has_banner(self):
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            banner = app.screen.query_one("#banner", Static)
            assert banner is not None

    @pytest.mark.asyncio
    async def test_empty_input_does_not_navigate(self):
        """Pressing load with empty input should not navigate away."""
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#load-button", Button)
            btn.press()
            await pilot.pause()
            # Should still be on WelcomeScreen
            assert isinstance(app.screen, WelcomeScreen)


class TestSpecBrowserScreen:
    @pytest.mark.asyncio
    async def test_spec_browser_renders(self):
        """SpecBrowserScreen should render with tree and detail panel."""
        spec = _make_spec()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            tree = app.screen.query_one(EndpointTree)
            assert tree is not None

    @pytest.mark.asyncio
    async def test_spec_browser_has_buttons(self):
        spec = _make_spec()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            gen_btn = app.screen.query_one("#generate-plan-btn", Button)
            assert gen_btn is not None
            back_btn = app.screen.query_one("#back-btn", Button)
            assert back_btn is not None

    @pytest.mark.asyncio
    async def test_spec_browser_detail_default(self):
        spec = _make_spec()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            detail = app.screen.query_one("#detail-content", Static)
            assert detail is not None


class TestPlanEditorScreen:
    @pytest.mark.asyncio
    async def test_plan_editor_renders(self):
        """PlanEditorScreen should render with DataTable."""
        plan = _make_plan()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(PlanEditorScreen(plan))
            await pilot.pause()
            table = app.screen.query_one(DataTable)
            assert table is not None
            assert table.row_count == 3

    @pytest.mark.asyncio
    async def test_plan_editor_summary(self):
        plan = _make_plan()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(PlanEditorScreen(plan))
            await pilot.pause()
            summary = app.screen.query_one("#plan-summary", Static)
            assert summary is not None

    @pytest.mark.asyncio
    async def test_plan_editor_has_action_buttons(self):
        plan = _make_plan()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(PlanEditorScreen(plan))
            await pilot.pause()
            run_btn = app.screen.query_one("#run-btn", Button)
            assert run_btn is not None
            vars_btn = app.screen.query_one("#vars-btn", Button)
            assert vars_btn is not None
            back_btn = app.screen.query_one("#back-btn", Button)
            assert back_btn is not None

    @pytest.mark.asyncio
    async def test_toggle_all_disables_all(self):
        plan = _make_plan()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = PlanEditorScreen(plan)
            await app.push_screen(screen)
            await pilot.pause()

            # Initially 2 enabled
            assert plan.enabled_count == 2

            # Toggle all — should disable all since some are enabled
            screen.action_toggle_all()
            await pilot.pause()
            assert plan.enabled_count == 0

            # Toggle all again — should enable all
            screen.action_toggle_all()
            await pilot.pause()
            assert plan.enabled_count == 3


class TestEndpointTreeWidget:
    @pytest.mark.asyncio
    async def test_tree_loads_spec(self):
        """EndpointTree should populate nodes from spec."""
        spec = _make_spec()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            tree = app.screen.query_one(EndpointTree)
            # Root should have children (tag nodes)
            assert len(tree.root.children) > 0

    @pytest.mark.asyncio
    async def test_tree_groups_by_tag(self):
        spec = _make_spec()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            tree = app.screen.query_one(EndpointTree)
            # Should have "items" tag node
            tag_labels = [str(child.label).lower() for child in tree.root.children]
            assert any("items" in label for label in tag_labels)


class TestAppNavigation:
    @pytest.mark.asyncio
    async def test_app_starts_on_welcome(self):
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, WelcomeScreen)

    @pytest.mark.asyncio
    async def test_navigate_to_browser_and_back(self):
        spec = _make_spec()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Navigate to browser
            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            assert isinstance(app.screen, SpecBrowserScreen)

            # Navigate back
            app.pop_screen()
            await pilot.pause()
            assert isinstance(app.screen, WelcomeScreen)

    @pytest.mark.asyncio
    async def test_full_navigation_flow(self):
        """Welcome -> Browser -> PlanEditor and back."""
        spec = _make_spec()
        plan = _make_plan()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Welcome
            assert isinstance(app.screen, WelcomeScreen)

            # -> Browser
            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            assert isinstance(app.screen, SpecBrowserScreen)

            # -> Plan Editor
            await app.push_screen(PlanEditorScreen(plan))
            await pilot.pause()
            assert isinstance(app.screen, PlanEditorScreen)

            # Back to Browser
            app.pop_screen()
            await pilot.pause()
            assert isinstance(app.screen, SpecBrowserScreen)

            # Back to Welcome
            app.pop_screen()
            await pilot.pause()
            assert isinstance(app.screen, WelcomeScreen)

    @pytest.mark.asyncio
    async def test_go_home_pops_to_welcome(self):
        """go_home should pop back to WelcomeScreen."""
        spec = _make_spec()
        plan = _make_plan()
        app = SpecsAgentApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # WelcomeScreen is pushed in on_mount, so stack is: default -> Welcome
            assert isinstance(app.screen, WelcomeScreen)

            await app.push_screen(SpecBrowserScreen(spec))
            await pilot.pause()
            await app.push_screen(PlanEditorScreen(plan))
            await pilot.pause()
            assert isinstance(app.screen, PlanEditorScreen)

            # action_go_home pops until stack size is 1 (keeps the default screen)
            # but WelcomeScreen is at index 1 in the stack, so we pop to it
            app.action_go_home()
            await pilot.pause()
            # After go_home, we should be back on WelcomeScreen
            # The stack is: default -> Welcome (go_home stops at len > 1)
            assert isinstance(app.screen, WelcomeScreen)
