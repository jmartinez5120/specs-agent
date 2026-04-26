"""Main Textual application for specs-agent.

This module is a **thin UI layer** over `specs_agent.engine.Engine`.
All business logic (parsing, plan gen, merging, persistence, history)
lives in the engine. The app owns screen navigation and reactive UI state.
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import LoadingIndicator, Static

from specs_agent.config import AppConfig
from specs_agent.engine import Engine, MergeResult, SpecLoadResult
from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import TestPlan
from specs_agent.models.results import Report
from specs_agent.models.spec import ParsedSpec
from specs_agent.parsing.loader import SpecLoadError
from specs_agent.screens.execution import ExecutionScreen
from specs_agent.screens.plan_editor import PlanEditorScreen
from specs_agent.screens.results import ResultsScreen
from specs_agent.screens.spec_browser import SpecBrowserScreen
from specs_agent.screens.test_config import TestConfigModal
from specs_agent.screens.welcome import WelcomeScreen


class SpecsAgentApp(App):
    """The specs-agent TUI application."""

    TITLE = "SPECS INVADERS"
    SUB_TITLE = ">> DEFEND YOUR APIs <<"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        ("q", "request_quit", "Eject"),
        ("f1", "go_home", "Base"),
    ]

    # Shared state
    parsed_spec: reactive[ParsedSpec | None] = reactive(None)
    test_plan: reactive[TestPlan | None] = reactive(None)
    run_config: reactive[TestRunConfig] = reactive(TestRunConfig)
    last_report: reactive[Report | None] = reactive(None)

    def __init__(
        self,
        spec_source: str | None = None,
        engine: Engine | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.engine: Engine = engine or Engine()
        self.initial_spec = spec_source
        self.config: AppConfig = self.engine.load_config()
        self.spec_source: str = ""  # Original source (URL, file path, or clipboard temp path)
        self.spec_source_type: str = ""  # "url", "file", or "clipboard"
        self._spec_was_refreshed: bool = False  # Set after a refresh with changes

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen())
        if self.initial_spec:
            self._load_spec(self.initial_spec)

    # --- Message handlers ---

    @on(WelcomeScreen.SpecSelected)
    def on_spec_selected(self, event: WelcomeScreen.SpecSelected) -> None:
        self._load_spec(event.source)

    @on(SpecBrowserScreen.GeneratePlanRequested)
    def on_generate_plan(self) -> None:
        if not self.parsed_spec:
            return

        spec_refreshed = self._spec_was_refreshed
        self._spec_was_refreshed = False

        plan, merge = self.engine.generate_or_merge_plan(self.parsed_spec)
        self.test_plan = plan

        if merge is not None:
            # Saved plan existed — merged with fresh
            if spec_refreshed or merge.new > 0 or merge.removed > 0:
                # Spec changed: archive old saved plan, save the merged one
                saved = self.engine.load_saved_plan(self.parsed_spec.title)
                if saved is not None:
                    self.engine.archive_plan(saved)
                self._auto_save_plan(plan)
                self.notify(
                    f"Spec updated: {merge.new} new, {merge.removed} removed, "
                    f"{merge.kept} intel preserved",
                    title="PLAN REGENERATED",
                )
            else:
                self.notify(
                    f"Loaded saved plan ({merge.kept} intel values preserved)",
                    title="PLAN RESTORED",
                )

        self.push_screen(PlanEditorScreen(self.test_plan))

    def _auto_save_plan(self, plan: TestPlan) -> None:
        """Save plan to storage after merge/regeneration."""
        try:
            self.engine.save_plan(plan)
        except Exception:
            pass

    @on(PlanEditorScreen.RunTestsRequested)
    def on_run_tests(self) -> None:
        if not self.test_plan:
            return
        # Show config modal, then start execution on save
        base_url = self.test_plan.base_url
        self.run_config.base_url = base_url
        self.push_screen(
            TestConfigModal(self.run_config, base_url=base_url),
            callback=self._on_config_saved,
        )

    def _on_config_saved(self, config: TestRunConfig | None) -> None:
        if config is None or not self.test_plan:
            return
        self.run_config = config
        self.push_screen(ExecutionScreen(self.test_plan, config))

    @on(ExecutionScreen.ExecutionComplete)
    def on_execution_complete(self, event: ExecutionScreen.ExecutionComplete) -> None:
        self.last_report = event.report
        try:
            self.engine.save_run_to_history(event.report)
            self.notify("Run saved to history", title="HISTORY")
        except Exception:
            pass

    # --- Actions ---

    def action_request_quit(self) -> None:
        from specs_agent.screens.quit_modal import QuitModal
        self.push_screen(QuitModal(), callback=self._on_quit_decision)

    def _on_quit_decision(self, quit: bool) -> None:
        if quit:
            self.exit()

    def action_go_home(self) -> None:
        while len(self.screen_stack) > 2:
            self.pop_screen()

    def refresh_spec(self) -> None:
        """Re-fetch the spec from its original source and show diff."""
        if self.spec_source_type == "clipboard":
            self.notify(
                "This spec was pasted from clipboard — paste again with [ctrl+v] to refresh",
                title="CLIPBOARD SOURCE",
                severity="warning",
            )
            return
        if not self.spec_source:
            self.notify("No spec source to refresh from", title="ERROR", severity="error")
            return
        # Save old spec for diff comparison
        self._old_spec_for_diff = self.parsed_spec
        self._refresh_spec_worker(self.spec_source)

    @work(thread=True, group="refresh_spec")
    def _refresh_spec_worker(self, source: str) -> None:
        """Reload spec in background without popping screens."""
        self.call_from_thread(self.notify, f"Refreshing from {source}...", title="REFRESHING")
        try:
            result = self.engine.load_spec_from_source(source)
            self.call_from_thread(
                self.notify,
                f"Fetched {len(result.spec.endpoints)} endpoints",
                title="REFRESH LOADED",
            )
            self.call_from_thread(self._on_refresh_complete, result.spec)
        except SpecLoadError as exc:
            self.call_from_thread(
                self.notify, str(exc), title="REFRESH FAILED", severity="error",
            )

    def _on_refresh_complete(self, new_spec: ParsedSpec) -> None:
        """Show side-by-side diff modal in-place after refresh."""
        old_spec = getattr(self, '_old_spec_for_diff', None)
        self._old_spec_for_diff = None

        if not old_spec:
            old_spec = self.parsed_spec

        if self.engine.specs_differ(old_spec, new_spec):
            self._spec_was_refreshed = True

        # Always show side-by-side diff modal
        from specs_agent.screens.refresh_diff_modal import RefreshDiffModal
        self._pending_spec = new_spec
        self._pending_source = self.spec_source
        self.push_screen(
            RefreshDiffModal(old_spec, new_spec, self.spec_source),
            callback=self._on_refresh_decision,
        )

    def _on_refresh_decision(self, proceed: bool | str) -> None:
        """Handle diff modal result — apply or discard refreshed spec."""
        if proceed == "refresh":
            self.refresh_spec()
            return
        if not proceed or not self._pending_spec:
            return
        # Apply the refreshed spec
        spec = self._pending_spec
        self.parsed_spec = spec

        self.engine.record_recent_spec(self.config, self.spec_source, spec.title)

        # Auto-regenerate the test plan if spec changed
        if self._spec_was_refreshed and self.test_plan:
            plan, merge = self.engine.generate_or_merge_plan(spec)
            if merge is not None:
                saved = self.engine.load_saved_plan(spec.title)
                if saved is not None:
                    self.engine.archive_plan(saved)
                self._auto_save_plan(plan)
                self.test_plan = plan
                self.notify(
                    f"Plan regenerated: {merge.new} new, {merge.removed} removed, "
                    f"{merge.kept} intel preserved",
                    title="PLAN UPDATED",
                )
            else:
                self.test_plan = plan
                self.notify("Plan regenerated from updated spec", title="PLAN UPDATED")

        self.notify(
            f"Spec refreshed: {spec.title} v{spec.version} — {len(spec.endpoints)} endpoints",
            title="SPEC UPDATED",
        )
        # Pop back to welcome, then push fresh browser
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.push_screen(SpecBrowserScreen(spec))

    # --- Workers ---

    @work(thread=True, exclusive=True)
    def _load_spec(self, source: str) -> None:
        """Load and parse a spec in a background thread."""
        self._last_source = source
        self.spec_source = source
        self.spec_source_type = Engine.classify_source(source)
        self.notify(f"Scanning sector {source}...", title="SCANNING")
        try:
            result = self.engine.load_spec_from_source(source)
            self.parsed_spec = result.spec
            self.engine.record_recent_spec(self.config, source, result.spec.title)
            self.call_from_thread(self._on_spec_loaded, result.spec, result.warnings)
        except SpecLoadError as exc:
            self.call_from_thread(
                self.notify,
                str(exc),
                title="SCAN FAILED",
                severity="error",
            )

    def _on_spec_loaded(self, spec: ParsedSpec, warnings: list[str] | None = None) -> None:
        """Called on the main thread after initial spec load (not refresh)."""
        self._pending_spec = spec
        self._pending_source = getattr(self, '_last_source', '')
        if warnings:
            for w in warnings:
                self.notify(w, title="WARNING", severity="warning")

        # Show preview modal before proceeding
        from specs_agent.screens.scan_preview import ScanPreviewModal
        self.push_screen(
            ScanPreviewModal(spec, self._pending_source),
            callback=self._on_preview_decision,
        )

    def _on_preview_decision(self, proceed: bool | str) -> None:
        if proceed == "refresh":
            self.refresh_spec()
            return
        if not proceed or not self._pending_spec:
            return
        spec = self._pending_spec
        self.notify(
            f"Detected {spec.title} v{spec.version} -- {len(spec.endpoints)} targets acquired",
            title="TARGETS LOCKED",
        )
        self.push_screen(SpecBrowserScreen(spec))
