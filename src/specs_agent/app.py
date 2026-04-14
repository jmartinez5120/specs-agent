"""Main Textual application for specs-agent."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import LoadingIndicator, Static

from specs_agent.config import AppConfig, add_recent_spec, load_config, save_config
from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import TestCase, TestPlan
from specs_agent.models.results import Report
from specs_agent.models.spec import ParsedSpec
from specs_agent.parsing.extractor import extract_spec
from specs_agent.parsing.loader import SpecLoadError, load_spec, last_warnings
from specs_agent.parsing.plan_generator import generate_plan
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

    def __init__(self, spec_source: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.initial_spec = spec_source
        self.config: AppConfig = load_config()
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

        # Generate fresh plan from current spec
        fresh_plan = generate_plan(self.parsed_spec)

        # Try loading saved plan and merge intel from matching endpoints
        saved_plan = self._try_load_saved_plan(self.parsed_spec.title)
        if saved_plan:
            merged, kept, new, removed = self._merge_plans(fresh_plan, saved_plan)
            self.test_plan = merged

            if spec_refreshed or new > 0 or removed > 0:
                # Spec changed — archive old plan and save the new merged one
                self._archive_plan(saved_plan)
                self._auto_save_plan(merged)
                self.notify(
                    f"Spec updated: {new} new, {removed} removed, {kept} intel preserved",
                    title="PLAN REGENERATED",
                )
            else:
                self.notify(
                    f"Loaded saved plan ({kept} intel values preserved)",
                    title="PLAN RESTORED",
                )
        else:
            self.test_plan = fresh_plan

        self.push_screen(PlanEditorScreen(self.test_plan))

    def _auto_save_plan(self, plan: TestPlan) -> None:
        """Save plan to disk after merge/regeneration."""
        from pathlib import Path
        from specs_agent.persistence import save_plan
        save_dir = Path.home() / ".specs-agent" / "plans"
        save_dir.mkdir(parents=True, exist_ok=True)
        safe_name = plan.name.replace(" ", "_").lower()[:40]
        path = str(save_dir / f"{safe_name}.yaml")
        try:
            save_plan(plan, path)
        except Exception:
            pass

    def _try_load_saved_plan(self, spec_title: str) -> TestPlan | None:
        from pathlib import Path
        from specs_agent.persistence import load_plan
        save_dir = Path.home() / ".specs-agent" / "plans"
        safe_name = f"{spec_title} Test Plan".replace(" ", "_").lower()[:40]
        path = save_dir / f"{safe_name}.yaml"
        if path.exists():
            try:
                return load_plan(str(path))
            except Exception:
                return None
        return None

    def _merge_plans(self, fresh: TestPlan, saved: TestPlan) -> tuple[TestPlan, int, int, int]:
        """Merge intel from saved plan into fresh plan.

        Uses test case name as key (e.g. "PUT /path → 200") so each variant
        merges independently.  For body fields, saved values are merged INTO
        the fresh body so new required fields from the updated spec are kept.

        Returns (merged_plan, kept_count, new_count, removed_count).
        """
        # Build lookup from saved plan keyed by name (unique per variant)
        saved_lookup: dict[str, TestCase] = {}
        for tc in saved.test_cases:
            saved_lookup[tc.name] = tc

        kept = 0
        new = 0
        for tc in fresh.test_cases:
            old_tc = saved_lookup.pop(tc.name, None)
            if old_tc:
                # Preserve user-edited path/query/header intel
                tc.path_params = old_tc.path_params
                tc.query_params = old_tc.query_params
                tc.headers = old_tc.headers
                tc.enabled = old_tc.enabled
                # Smart body merge: start with fresh body (has new required fields),
                # then overlay saved user edits on top
                tc.body = _merge_body(tc.body, old_tc.body)
                kept += 1
            else:
                new += 1

        removed = len(saved_lookup)  # Test cases in saved but not in fresh

        fresh.auth_type = saved.auth_type
        fresh.auth_value = saved.auth_value
        fresh.global_headers = saved.global_headers

        return fresh, kept, new, removed

    def _archive_plan(self, plan: TestPlan) -> None:
        """Archive a plan before overwriting with updated spec version."""
        from datetime import datetime, timezone
        from pathlib import Path
        from specs_agent.persistence import save_plan

        archive_dir = Path.home() / ".specs-agent" / "plans" / "archive"
        safe_name = plan.name.replace(" ", "_").lower()[:40]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = str(archive_dir / f"{safe_name}_{timestamp}.yaml")
        try:
            save_plan(plan, path)
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
        # Auto-save to history
        try:
            from specs_agent.history.storage import save_run
            path = save_run(event.report)
            self.notify(f"Run saved to history", title="HISTORY")
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
            raw = load_spec(source)
            spec = extract_spec(raw, source_url=source)
            self.call_from_thread(
                self.notify,
                f"Fetched {len(spec.endpoints)} endpoints",
                title="REFRESH LOADED",
            )
            self.call_from_thread(self._on_refresh_complete, spec)
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

        has_changes = _specs_differ(old_spec, new_spec)
        if has_changes:
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

        from specs_agent.config import add_recent_spec, save_config
        add_recent_spec(self.config, self.spec_source, spec.title)
        save_config(self.config)

        # Auto-regenerate the test plan if spec changed
        if self._spec_was_refreshed and self.test_plan:
            fresh_plan = generate_plan(spec)
            saved_plan = self._try_load_saved_plan(spec.title)
            if saved_plan:
                merged, kept, new, removed = self._merge_plans(fresh_plan, saved_plan)
                self._archive_plan(saved_plan)
                self._auto_save_plan(merged)
                self.test_plan = merged
                self.notify(
                    f"Plan regenerated: {new} new, {removed} removed, {kept} intel preserved",
                    title="PLAN UPDATED",
                )
            else:
                self.test_plan = fresh_plan
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
        # Determine source type
        if source.startswith(("http://", "https://")):
            self.spec_source_type = "url"
        elif "/.specs-agent/pasted/" in source:
            self.spec_source_type = "clipboard"
        else:
            self.spec_source_type = "file"
        self.notify(f"Scanning sector {source}...", title="SCANNING")
        try:
            raw = load_spec(source)
            spec = extract_spec(raw, source_url=source)
            self.parsed_spec = spec

            add_recent_spec(self.config, source, spec.title)
            save_config(self.config)

            warnings = list(last_warnings.warnings)
            self.call_from_thread(self._on_spec_loaded, spec, warnings)
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


def _merge_body(fresh_body, saved_body):
    """Merge saved user edits into the fresh body from the updated spec.

    - Fresh body has all fields the new spec requires (including newly added ones).
    - Saved body has user-edited values.
    - Result: fresh body with saved values overlaid where keys match.
    """
    if fresh_body is None:
        return saved_body
    if saved_body is None:
        return fresh_body
    if isinstance(fresh_body, dict) and isinstance(saved_body, dict):
        merged = dict(fresh_body)  # Start with all fresh keys (includes new required fields)
        for key, val in saved_body.items():
            if key in merged:
                # Recursively merge nested dicts
                merged[key] = _merge_body(merged[key], val)
            else:
                # User added a custom field not in fresh spec — keep it
                merged[key] = val
        return merged
    # For non-dict bodies (string, list, etc.), prefer saved if it was edited
    return saved_body


def _specs_differ(old: ParsedSpec, new: ParsedSpec) -> bool:
    """Check if two parsed specs differ in any way — raw comparison."""
    import json
    try:
        old_json = json.dumps(old.raw_spec, sort_keys=True)
        new_json = json.dumps(new.raw_spec, sort_keys=True)
        return old_json != new_json
    except Exception:
        # Fallback: always treat as different if serialization fails
        return True
