"""Plan editor screen -- battle plan with keybindings, search, and detail popup."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from specs_agent.models.plan import TestPlan
from specs_agent.screens.detail_modal import DetailModal, _has_template_var
from specs_agent.screens.navigation import ArrowNavMixin
from specs_agent.screens.variables_modal import VariablesModal

METHOD_COLORS = {
    "GET": "[#55cc55]GET[/]",
    "POST": "[#cc9944]POST[/]",
    "PUT": "[#5599dd]PUT[/]",
    "PATCH": "[#55aacc]PATCH[/]",
    "DELETE": "[#cc4444]DEL[/]",
}


class PlanEditorScreen(ArrowNavMixin, Screen):
    """Battle plan editor -- arm, inspect, search, and fire test weapons."""

    FOCUS_ZONES = [
        "#plan-table",
        ["#back-btn", "#vars-btn", "#run-btn"],
    ]

    class RunTestsRequested(Message):
        """User wants to run tests."""

    DEFAULT_CSS = """
    PlanEditorScreen {
        background: #1a1b2e;
    }
    #plan-header {
        dock: top;
        height: auto;
        max-height: 10;
        padding: 0 2;
        background: #1a1b2e;
    }
    #plan-title {
        color: #55cc55;
        text-style: bold;
    }
    #plan-summary {
        color: #7a7a9a;
    }
    #plan-hint {
        color: #555577;
    }
    #search-input {
        height: 3;
        background: #222240;
        color: #55cc55;
        border: tall #333355;
        margin: 0;
    }
    #search-input:focus {
        border: tall #55cc55;
    }
    #search-status {
        color: #7a7a9a;
        height: 1;
    }
    #plan-table {
        height: 1fr;
        border: solid #333355;
    }
    #history-panel {
        height: auto;
        max-height: 12;
        padding: 0 2;
        border-top: dashed #333355;
        background: #1e1f32;
    }
    #history-title {
        color: #cc9944;
        text-style: bold;
        height: 1;
    }
    #history-table {
        height: auto;
        max-height: 9;
    }
    #plan-actions {
        dock: bottom;
        height: 3;
        align-horizontal: right;
        padding: 0 2;
        background: #1a1b2e;
    }
    """

    BINDINGS = [
        ("d", "inspect", "Inspect"),
        ("enter", "inspect", "Inspect"),
        ("space", "toggle_selected", "Arm/Disarm"),
        ("e", "toggle_selected", "Arm/Disarm"),
        ("a", "toggle_all", "Toggle All"),
        ("c", "copy_curl", "cURL"),
        ("v", "show_variables", "Variables"),
        ("s", "save_plan", "Save"),
        ("h", "show_history", "History"),
        ("r", "regenerate", "Regen"),
        ("f", "fire", "Fire"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("g", "cursor_top", "Top"),
        ("G", "cursor_bottom", "Bottom"),
        ("escape", "escape_action", "Back"),
    ]

    def __init__(self, plan: TestPlan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan
        self._row_keys: list[str] = []
        self._filtered_cases: list = []
        self._search_active = False
        self._search_query = ""
        self._history_runs: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="plan-header"):
            yield Static(f"BATTLE PLAN: {self.plan.name}", id="plan-title")
            yield Static(id="plan-summary")
            yield Static(
                "[d] inspect  [space] arm/disarm  [a] toggle all  [c] cURL  [s] save  [r] regen  [/] search  [v] vars  [h] history  [f] fire",
                id="plan-hint",
            )
            yield Input(placeholder="Filter by endpoint, method, or name...", id="search-input")
            yield Static("", id="search-status")
        yield DataTable(id="plan-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="history-panel"):
            yield Static("", id="history-title")
            yield DataTable(id="history-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="plan-actions"):
            yield Button("\\[esc] BACK", variant="default", id="back-btn")
            yield Button("\\[v] VARIABLES", variant="warning", id="vars-btn")
            yield Button("\\[f] FIRE", variant="success", id="run-btn")
        yield Footer()

    def _refresh_needs_input(self) -> None:
        """Recalculate needs_input for all test cases based on current values."""
        for tc in self.plan.test_cases:
            tc.needs_input = (
                _has_template_var(tc.path_params)
                or _has_template_var(tc.query_params)
                or _has_template_var(tc.headers)
                or _has_template_var(tc.body)
            )

    def on_mount(self) -> None:
        self._refresh_needs_input()
        self._filtered_cases = list(self.plan.test_cases)
        self._populate_table()
        self._update_summary()
        # Hide and disable search on start
        search_input = self.query_one("#search-input", Input)
        search_input.display = False
        search_input.disabled = True
        self.query_one("#search-status").display = False
        # Load and show history
        self._load_history()
        # Ensure table has focus
        self.query_one(DataTable).focus()

    def on_screen_resume(self) -> None:
        """Called when this screen becomes active again (e.g. after popping results)."""
        self._load_history()

    # ── Table population ─────────────────────────────────────────────────

    def _populate_table(self) -> None:
        table = self.query_one(DataTable)

        # Only add columns once — on subsequent calls just clear rows
        if not table.columns:
            table.add_column("Status", key="enabled")
            table.add_column("Method", key="method")
            table.add_column("Target", key="endpoint")
            table.add_column("Mission", key="name")
            table.add_column("Checks", key="assertions")
            table.add_column("Intel", key="input")
        else:
            table.clear()

        self._row_keys.clear()
        for tc in self._filtered_cases:
            type_icon = "😈" if tc.test_type == "sad" else "😊"
            armed = f"[#55cc55]{type_icon} ARMED[/]" if tc.enabled else f"[#7a7a9a]{type_icon} --[/]"
            method = METHOD_COLORS.get(tc.method, f"[#7a7a9a]{tc.method}[/]")
            needs = "[#cc9944]NEEDED[/]" if tc.needs_input else "[#7a7a9a]ready[/]"
            table.add_row(armed, method, tc.endpoint_path, tc.name,
                          str(len(tc.assertions)), needs, key=tc.id)
            self._row_keys.append(tc.id)

    def _update_summary(self) -> None:
        total = self.plan.total_count
        enabled = self.plan.enabled_count
        needs = self.plan.needs_input_count
        showing = len(self._filtered_cases)
        filter_text = f"    [#55aacc]showing {showing}/{total}[/]" if showing != total else ""
        text = (
            f"[#55cc55]{enabled}[/][#7a7a9a]/{total} armed[/]"
            f"    [#cc9944]{needs}[/][#7a7a9a] need intel[/]"
            f"    [#7a7a9a]target:[/] [#55aacc]{self.plan.base_url}[/]"
            f"{filter_text}"
        )
        self.query_one("#plan-summary", Static).update(text)

    def _get_current_case(self):
        table = self.query_one(DataTable)
        row_idx = table.cursor_row
        if row_idx is not None and row_idx < len(self._row_keys):
            return self._find_case(self._row_keys[row_idx])
        return None

    # ── Search / Filter ──────────────────────────────────────────────────

    def _apply_filter(self, query: str) -> None:
        self._search_query = query
        if not query.strip():
            self._filtered_cases = list(self.plan.test_cases)
        else:
            self._filtered_cases = [
                tc for tc in self.plan.test_cases
                if self._fuzzy_match(query, tc)
            ]
        self._populate_table()
        self._update_summary()

        status = self.query_one("#search-status", Static)
        if query.strip():
            status.update(f"[#7a7a9a]{len(self._filtered_cases)} matches[/]  [#555577][ESC] clear  [ENTER] keep[/]")
        else:
            status.update("")

    @staticmethod
    def _fuzzy_match(query: str, tc) -> bool:
        q = query.lower()
        target = f"{tc.method} {tc.endpoint_path} {tc.name} {tc.description or ''}".lower()
        qi = 0
        for ch in target:
            if qi < len(q) and ch == q[qi]:
                qi += 1
        return qi == len(q)

    def _show_search(self) -> None:
        self._search_active = True
        inp = self.query_one("#search-input", Input)
        inp.display = True
        inp.disabled = False
        self.query_one("#search-status").display = True
        inp.value = self._search_query
        inp.focus()

    def _hide_search(self, clear: bool = False) -> None:
        self._search_active = False
        inp = self.query_one("#search-input", Input)
        inp.display = False
        inp.disabled = True
        self.query_one("#search-status").display = False
        if clear:
            self._search_query = ""
            self._apply_filter("")
        self.query_one(DataTable).focus()

    def on_key(self, event) -> None:
        if self._search_active:
            return
        if event.character == "/":
            event.prevent_default()
            event.stop()
            self._show_search()
        elif event.key == "space":
            event.prevent_default()
            event.stop()
            self.action_toggle_selected()
        elif event.character == "e":
            event.prevent_default()
            event.stop()
            self.action_toggle_selected()
        elif event.character == "c":
            event.prevent_default()
            event.stop()
            self.action_copy_curl()
        elif event.character == "s":
            event.prevent_default()
            event.stop()
            self.action_save_plan()
        elif event.character == "h":
            event.prevent_default()
            event.stop()
            self.action_show_history()
        elif event.character == "r":
            event.prevent_default()
            event.stop()
            self.action_regenerate()

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        self._apply_filter(event.value)

    @on(Input.Submitted, "#search-input")
    def on_search_submitted(self) -> None:
        self._hide_search(clear=False)

    # ── Row selection events ─────────────────────────────────────────────

    @on(DataTable.RowSelected, "#plan-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = str(event.row_key.value)
        tc = self._find_case(row_key)
        if tc:
            self.app.push_screen(DetailModal(tc), callback=self._on_detail_closed)

    def _load_history(self) -> None:
        """Load and display recent test run history in a selectable table."""
        try:
            from specs_agent.history.storage import list_runs
            self._history_runs = list_runs(self.plan.spec_title, self.plan.base_url, limit=10)
        except Exception:
            self._history_runs = []

        panel = self.query_one("#history-panel")
        if not self._history_runs:
            panel.display = False
            return

        panel.display = True
        self.query_one("#history-title", Static).update(
            f"RECENT RUNS ({len(self._history_runs)})  [#7a7a9a]select a run to view details[/]"
        )

        table = self.query_one("#history-table", DataTable)
        has_perf = any(r.get("perf_requests", 0) > 0 for r in self._history_runs)

        if not table.columns:
            table.add_column("Time", key="time")
            table.add_column("Rate", key="rate")
            table.add_column("Delta", key="delta")
            table.add_column("Pass", key="pass")
            table.add_column("Fail", key="fail")
            table.add_column("Err", key="err")
            table.add_column("Duration", key="duration")
            if has_perf:
                table.add_column("Reqs", key="perf_reqs")
                table.add_column("TPS", key="perf_rps")
                table.add_column("Avg", key="perf_avg")
                table.add_column("P95", key="perf_p95")
                table.add_column("P99", key="perf_p99")
                table.add_column("Err%", key="perf_err")
        else:
            table.clear()

        for i, run in enumerate(self._history_runs):
            ts = run.get("timestamp", "")[:16].replace("T", " ")
            rate = run.get("pass_rate", 0)
            passed = run.get("passed", 0)
            failed = run.get("failed", 0)
            errors = run.get("errors", 0)
            duration = run.get("duration", 0)

            rate_color = "#55cc55" if rate >= 80 else "#cc9944" if rate >= 50 else "#cc4444"

            delta_str = "[#7a7a9a]--[/]"
            if i < len(self._history_runs) - 1:
                prev_rate = self._history_runs[i + 1].get("pass_rate", 0)
                diff = rate - prev_rate
                if diff > 0:
                    delta_str = f"[#55cc55]+{diff:.0f}%[/]"
                elif diff < 0:
                    delta_str = f"[#cc4444]{diff:.0f}%[/]"
                else:
                    delta_str = "[#7a7a9a]0%[/]"

            row = [
                ts,
                f"[{rate_color}]{rate:.0f}%[/]",
                delta_str,
                f"[#55cc55]{passed}[/]",
                f"[#cc4444]{failed}[/]",
                f"[#cc9944]{errors}[/]",
                f"{duration:.1f}s",
            ]

            if has_perf:
                perf_reqs = run.get("perf_requests", 0)
                perf_rps = run.get("perf_rps", 0)
                perf_avg = run.get("perf_avg_ms", 0)
                perf_p95 = run.get("perf_p95_ms", 0)
                perf_p99 = run.get("perf_p99_ms", 0)
                perf_err = run.get("perf_err_pct", 0)

                if perf_reqs:
                    err_color = "#cc4444" if perf_err > 1 else "#7a7a9a"
                    row.extend([
                        str(perf_reqs),
                        f"{perf_rps:.0f}",
                        f"{perf_avg:.0f}ms",
                        f"[#cc9944]{perf_p95:.0f}ms[/]",
                        f"[#cc4444]{perf_p99:.0f}ms[/]",
                        f"[{err_color}]{perf_err:.1f}%[/]",
                    ])
                else:
                    row.extend(["[#7a7a9a]--[/]"] * 6)

            table.add_row(*row, key=f"run_{i}")

    @on(DataTable.RowSelected, "#history-table")
    def on_history_row_selected(self, event: DataTable.RowSelected) -> None:
        """Load and display a past run's full results."""
        row_key = str(event.row_key.value)
        if not row_key.startswith("run_"):
            return
        idx = int(row_key.split("_")[1])
        if idx >= len(self._history_runs):
            return

        run = self._history_runs[idx]
        filename = run.get("filename", "")
        if not filename:
            return

        try:
            from specs_agent.history.storage import load_run
            report = load_run(self.plan.spec_title, self.plan.base_url, filename)
            if report:
                from specs_agent.screens.results import ResultsScreen
                self.app.push_screen(ResultsScreen(report))
        except Exception as exc:
            self.notify(f"Failed to load run: {exc}", title="ERROR", severity="error")

    def _on_detail_closed(self, result) -> None:
        """Refresh table after detail modal closes (intel may have changed)."""
        self._refresh_needs_input()
        self._populate_table()
        self._update_summary()

    # ── Actions (keybindings) ────────────────────────────────────────────

    def action_inspect(self) -> None:
        if self._search_active:
            return
        tc = self._get_current_case()
        if tc:
            self.app.push_screen(DetailModal(tc), callback=self._on_detail_closed)

    def action_toggle_selected(self) -> None:
        if self._search_active:
            return
        table = self.query_one(DataTable)
        row_idx = table.cursor_row
        if row_idx is not None and row_idx < len(self._row_keys):
            self._toggle_case(self._row_keys[row_idx])

    def action_toggle_all(self) -> None:
        if self._search_active:
            return
        any_enabled = any(tc.enabled for tc in self._filtered_cases)
        for tc in self._filtered_cases:
            tc.enabled = not any_enabled
        self._populate_table()
        self._update_summary()

    def action_show_variables(self) -> None:
        if self._search_active:
            return
        self.app.push_screen(VariablesModal())

    def action_copy_curl(self) -> None:
        if self._search_active:
            return
        tc = self._get_current_case()
        if not tc:
            return
        from specs_agent.curl_builder import build_curl
        curl = build_curl(
            tc, self.plan.base_url,
            auth_type=self.plan.auth_type,
            auth_value=self.plan.auth_value,
        )
        try:
            import subprocess
            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            process.communicate(curl.encode())
            self.notify("cURL copied to clipboard", title="COPIED")
        except Exception:
            # Fallback: show it in a notification
            self.notify(curl[:200], title="cURL")

    def action_save_plan(self) -> None:
        if self._search_active:
            return
        from pathlib import Path
        from specs_agent.persistence import save_plan
        save_dir = Path.home() / ".specs-agent" / "plans"
        safe_name = self.plan.name.replace(" ", "_").lower()[:40]
        path = str(save_dir / f"{safe_name}.yaml")
        try:
            saved = save_plan(self.plan, path)
            self.notify(f"Saved to {saved}", title="PLAN SAVED")
        except Exception as exc:
            self.notify(f"Save failed: {exc}", title="ERROR", severity="error")

    def action_regenerate(self) -> None:
        """Force regenerate the plan from the current spec."""
        if self._search_active:
            return
        spec = getattr(self.app, "parsed_spec", None)
        if not spec:
            self.notify("No spec loaded", title="ERROR", severity="error")
            return

        from specs_agent.parsing.plan_generator import generate_plan
        fresh = generate_plan(spec)
        # Merge intel from current plan
        old_lookup: dict[str, object] = {}
        for tc in self.plan.test_cases:
            key = f"{tc.method} {tc.endpoint_path} {tc.name}"
            old_lookup[key] = tc

        kept = 0
        for tc in fresh.test_cases:
            key = f"{tc.method} {tc.endpoint_path} {tc.name}"
            old = old_lookup.get(key)
            if old:
                tc.path_params = old.path_params
                tc.query_params = old.query_params
                tc.headers = old.headers
                tc.body = old.body
                tc.enabled = old.enabled
                kept += 1

        fresh.auth_type = self.plan.auth_type
        fresh.auth_value = self.plan.auth_value
        fresh.global_headers = self.plan.global_headers

        # Replace plan
        self.plan.test_cases = fresh.test_cases
        self.plan.performance_slas = fresh.performance_slas
        if hasattr(self.app, "test_plan"):
            self.app.test_plan = self.plan

        self._refresh_needs_input()
        self._filtered_cases = list(self.plan.test_cases)
        self._populate_table()
        self._update_summary()

        total = len(fresh.test_cases)
        happy = sum(1 for tc in fresh.test_cases if tc.test_type == "happy")
        sad = sum(1 for tc in fresh.test_cases if tc.test_type == "sad")
        self.notify(
            f"Regenerated: {total} cases ({happy} happy, {sad} sad, {kept} intel preserved)",
            title="PLAN REGENERATED",
        )

    def action_show_history(self) -> None:
        if self._search_active:
            return
        panel = self.query_one("#history-panel")
        panel.display = not panel.display

    def action_fire(self) -> None:
        if self._search_active:
            return
        self.post_message(self.RunTestsRequested())

    def action_escape_action(self) -> None:
        if self._search_active:
            self._hide_search(clear=True)
        else:
            self.app.pop_screen()

    def action_cursor_down(self) -> None:
        if not self._search_active:
            self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        if not self._search_active:
            self.query_one(DataTable).action_cursor_up()

    def action_cursor_top(self) -> None:
        if not self._search_active:
            self.query_one(DataTable).move_cursor(row=0)

    def action_cursor_bottom(self) -> None:
        if not self._search_active:
            table = self.query_one(DataTable)
            table.move_cursor(row=table.row_count - 1)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _find_case(self, case_id: str):
        for tc in self.plan.test_cases:
            if tc.id == case_id:
                return tc
        return None

    def _toggle_case(self, case_id: str) -> None:
        tc = self._find_case(case_id)
        if not tc:
            return
        tc.enabled = not tc.enabled
        table = self.query_one(DataTable)
        armed = "[#55cc55]ARMED[/]" if tc.enabled else "[#7a7a9a]--[/]"
        table.update_cell(case_id, "enabled", armed)
        self._update_summary()

    # ── Button handlers ──────────────────────────────────────────────────

    @on(Button.Pressed, "#run-btn")
    def on_run_pressed(self) -> None:
        self.post_message(self.RunTestsRequested())

    @on(Button.Pressed, "#back-btn")
    def on_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#vars-btn")
    def on_vars_pressed(self) -> None:
        self.action_show_variables()
