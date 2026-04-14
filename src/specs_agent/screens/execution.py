"""Execution screen -- live progress of functional and performance test phases."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, ProgressBar, Static

from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import TestPlan
from specs_agent.models.results import Report, TestResult, TestStatus
from specs_agent.execution.runner import TestRunner
from specs_agent.screens.navigation import ArrowNavMixin


class ExecutionScreen(ArrowNavMixin, Screen):
    """Live test execution with separate functional and performance phases."""

    FOCUS_ZONES = [
        "#exec-table",
        ["#cancel-btn", "#results-btn"],
    ]

    class ExecutionComplete(Message):
        def __init__(self, report: Report) -> None:
            self.report = report
            super().__init__()

    DEFAULT_CSS = """
    ExecutionScreen {
        background: #1a1b2e;
    }
    #exec-header {
        dock: top;
        height: auto;
        padding: 1 2;
    }
    #exec-title {
        color: #55cc55;
        text-style: bold;
    }
    #exec-phase {
        color: #cc9944;
    }
    #exec-stats {
        color: #7a7a9a;
    }
    #progress-bar {
        dock: top;
        margin: 0 2;
        height: 1;
    }
    #exec-table {
        height: 1fr;
        border: solid #333355;
    }
    #perf-panel {
        height: 6;
        padding: 0 2;
        border-bottom: dashed #333355;
        background: #1e1f32;
    }
    #perf-progress {
        height: 1;
        margin: 0;
    }
    #perf-header {
        color: #cc9944;
        text-style: bold;
    }
    #perf-live {
        color: #c0c0d0;
    }
    #perf-endpoints {
        color: #7a7a9a;
    }
    #exec-actions {
        dock: bottom;
        height: 3;
        align-horizontal: right;
        padding: 0 2;
    }
    """

    BINDINGS = [
        ("c", "cancel_run", "Cancel"),
        ("r", "show_results", "Results"),
        ("escape", "go_back", "Back"),
        ("left", "focus_left", "Left"),
        ("right", "focus_right", "Right"),
    ]

    def __init__(self, plan: TestPlan, config: TestRunConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan
        self.run_config = config
        self._runner: TestRunner | None = None
        self._report: Report | None = None
        self._passed = 0
        self._failed = 0
        self._errors = 0
        self._completed = 0
        self._total = len(plan.enabled_cases)
        self._perf_enabled = config.performance.enabled

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="exec-header"):
            yield Static("EXECUTING BATTLE PLAN", id="exec-title")
            yield Static("[#cc9944]Phase: Functional Tests[/]", id="exec-phase")
            yield Static(id="exec-stats")
        yield ProgressBar(total=self._total, id="progress-bar")
        with Vertical(id="perf-panel"):
            yield Static("", id="perf-header")
            yield ProgressBar(total=100, id="perf-progress", show_eta=False)
            yield Static("", id="perf-live")
            yield Static("", id="perf-endpoints")
        yield DataTable(id="exec-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="exec-actions"):
            yield Button("\\[c] CANCEL", variant="warning", id="cancel-btn")
            yield Button("\\[r] RESULTS", variant="success", id="results-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Status", key="status")
        table.add_column("Method", key="method")
        table.add_column("Endpoint", key="endpoint")
        table.add_column("Code", key="code")
        table.add_column("Time", key="time")
        table.add_column("Result", key="result")
        self._update_stats()
        # Hide perf panel initially
        self.query_one("#perf-panel").display = False
        self._start_execution()

    @work(thread=False)
    async def _start_execution(self) -> None:
        self._runner = TestRunner(self.plan, self.run_config)
        report = await self._runner.run(
            on_result=self._on_test_result,
            on_progress=self._on_progress,
            on_perf_update=self._on_perf_update,
            on_phase=self._on_phase,
        )
        self._report = report
        self._on_complete(report)

    def _on_test_result(self, result: TestResult) -> None:
        self._add_result_row(result)

    def _on_progress(self, completed: int, total: int) -> None:
        pass

    def _on_phase(self, phase: str) -> None:
        phase_widget = self.query_one("#exec-phase", Static)
        if phase == "functional":
            phase_widget.update("[#cc9944]Phase: Functional Tests[/]")
        elif phase == "performance":
            phase_widget.update("[#cc9944]Phase: Performance Tests[/]")
            # Show perf panel
            panel = self.query_one("#perf-panel")
            panel.display = True
            perf = self.run_config.performance
            tps_info = (
                f"target {perf.target_tps:.0f} TPS"
                if perf.target_tps > 0
                else "unlimited TPS"
            )
            if perf.stages:
                stages_str = " → ".join(f"{s.users}u/{s.duration_seconds}s" for s in perf.stages)
                self.query_one("#perf-header", Static).update(
                    f"PERFORMANCE  "
                    f"[#7a7a9a]staged: {stages_str} | {tps_info}[/]"
                )
            else:
                self.query_one("#perf-header", Static).update(
                    f"PERFORMANCE  "
                    f"[#7a7a9a]{perf.concurrent_users} users | "
                    f"{perf.duration_seconds}s | "
                    f"ramp {perf.ramp_up_seconds}s | "
                    f"{tps_info}[/]"
                )
            self.query_one("#perf-live", Static).update("[#7a7a9a]Starting...[/]")
        elif phase == "complete":
            phase_widget.update("[#55cc55]Complete[/]")

    def _on_perf_update(self, stats: dict) -> None:
        total = stats.get("total_requests", 0)
        avg = stats.get("avg_latency", 0)
        p50 = stats.get("p50_latency", 0)
        p95 = stats.get("p95_latency", 0)
        p99 = stats.get("p99_latency", 0)
        err_rate = stats.get("error_rate", 0)
        elapsed = stats.get("elapsed_seconds", 0)
        duration = stats.get("duration_seconds", self.run_config.performance.duration_seconds)
        window_tps = stats.get("window_tps", 0)
        peak_tps = stats.get("peak_tps", 0)
        target_tps = stats.get("target_tps", 0)
        active_workers = stats.get("active_workers", 0)

        # Update progress bar
        pct = min(100, int((elapsed / max(duration, 1)) * 100))
        perf_bar = self.query_one("#perf-progress", ProgressBar)
        perf_bar.update(progress=pct)

        remaining = max(0, duration - elapsed)
        tps_label = f"[#55aacc]{window_tps:.1f} TPS[/]"
        if target_tps > 0:
            tps_label += f"[#7a7a9a]/{target_tps:.0f}[/]"
        tps_label += f"  [#cc9944]peak {peak_tps:.1f}[/]"
        workers_label = f"[#7a7a9a]{active_workers}u[/]" if active_workers else ""
        self.query_one("#perf-live", Static).update(
            f"[#c0c0d0]{total}[/] reqs  "
            f"{tps_label}  "
            f"{workers_label}  "
            f"[#55cc55]avg {avg:.0f}ms[/]  "
            f"[#55aacc]p50 {p50:.0f}ms[/]  "
            f"[#cc9944]p95 {p95:.0f}ms[/]  "
            f"[#cc4444]p99 {p99:.0f}ms[/]  "
            f"[{'#cc4444' if err_rate > 1 else '#7a7a9a'}]{err_rate:.1f}% err[/]  "
            f"[#7a7a9a]{remaining:.0f}s left[/]"
        )

        per_ep = stats.get("per_endpoint", {})
        if per_ep:
            parts = []
            for key, ep_stats in list(per_ep.items())[:5]:
                parts.append(f"[#7a7a9a]{key}: {ep_stats['total']} reqs[/]")
            self.query_one("#perf-endpoints", Static).update("  ".join(parts))

    def _add_result_row(self, result: TestResult) -> None:
        self._completed += 1
        type_icon = "😈" if result.test_type == "sad" else "😊"
        if result.status == TestStatus.PASSED:
            self._passed += 1
            status = f"[#55cc55]{type_icon} PASS[/]"
        elif result.status == TestStatus.FAILED:
            self._failed += 1
            status = f"[#cc4444]{type_icon} FAIL[/]"
        elif result.status == TestStatus.ERROR:
            self._errors += 1
            status = f"[#cc9944]{type_icon} ERR[/]"
        else:
            status = f"[#7a7a9a]{type_icon} SKIP[/]"

        code = str(result.status_code) if result.status_code else "--"
        time_str = f"{result.response_time_ms:.0f}ms" if result.response_time_ms else "--"

        detail = ""
        if result.error_message:
            detail = result.error_message[:60]
        elif result.assertion_results:
            failed = [a for a in result.assertion_results if not a.passed]
            if failed:
                detail = failed[0].message[:60]

        table = self.query_one(DataTable)
        table.add_row(status, result.method, result.endpoint, code, time_str, detail)
        self._update_stats()

        progress = self.query_one(ProgressBar)
        progress.advance(1)

    def _update_stats(self) -> None:
        text = (
            f"[#55cc55]{self._passed}[/] passed  "
            f"[#cc4444]{self._failed}[/] failed  "
            f"[#cc9944]{self._errors}[/] errors  "
            f"[#7a7a9a]{self._completed}/{self._total}[/]"
        )
        self.query_one("#exec-stats", Static).update(text)

    def _on_complete(self, report: Report) -> None:
        title = self.query_one("#exec-title", Static)
        if report.failed_tests == 0 and report.error_tests == 0:
            title.update("[#55cc55]MISSION COMPLETE[/]")
        else:
            title.update("[#cc4444]MISSION REPORT[/]")
        self.query_one("#cancel-btn", Button).disabled = True
        self.query_one("#results-btn", Button).disabled = False
        self.post_message(self.ExecutionComplete(report))

    def action_cancel_run(self) -> None:
        if self._runner:
            self._runner.cancel()
            self.notify("Cancelling...", title="ABORT", severity="warning")

    def action_go_back(self) -> None:
        if self._report:
            self.app.pop_screen()
        else:
            self.action_cancel_run()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_pressed(self) -> None:
        self.action_cancel_run()

    def action_show_results(self) -> None:
        if self._report:
            from specs_agent.screens.results import ResultsScreen
            self.app.push_screen(ResultsScreen(self._report))

    @on(Button.Pressed, "#results-btn")
    def on_results_pressed(self) -> None:
        self.action_show_results()
