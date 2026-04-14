"""Results screen -- test run summary with functional and performance tables."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static, TabbedContent, TabPane

from specs_agent.models.results import Report, TestResult, TestStatus
from specs_agent.screens.navigation import ArrowNavMixin


class ResultsScreen(ArrowNavMixin, Screen):
    """Display test run results with functional + performance tabs."""

    FOCUS_ZONES = [
        "#results-tabs",
        ["#back-btn", "#export-btn"],
    ]

    DEFAULT_CSS = """
    ResultsScreen {
        background: #1a1b2e;
    }
    #results-header {
        dock: top;
        height: auto;
        padding: 1 2;
    }
    #results-title {
        color: #55cc55;
        text-style: bold;
    }
    #results-summary {
        color: #c0c0d0;
    }
    #results-tabs {
        height: 1fr;
    }
    #func-table {
        height: 1fr;
        border: solid #333355;
    }
    #perf-chart {
        height: auto;
        max-height: 14;
        padding: 1 2;
        color: #c0c0d0;
    }
    #perf-table {
        height: 1fr;
        border: solid #333355;
    }
    #results-actions {
        dock: bottom;
        height: 3;
        align-horizontal: right;
        padding: 0 2;
    }
    """

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("d", "inspect_selected", "Inspect"),
        ("x", "export_report", "Export"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("left", "focus_left", "Left"),
        ("right", "focus_right", "Right"),
    ]

    def __init__(self, report: Report, **kwargs) -> None:
        super().__init__(**kwargs)
        self.report = report
        self._results_by_row: list[TestResult] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="results-header"):
            yield Static("MISSION REPORT", id="results-title")
            yield Static(id="results-summary")
        with TabbedContent(id="results-tabs"):
            with TabPane(f"Functional ({self.report.total_tests})", id="func-tab"):
                yield DataTable(id="func-table", cursor_type="row", zebra_stripes=True)
            if self.report.performance_results:
                with TabPane(f"Performance ({len(self.report.performance_results)})", id="perf-tab"):
                    yield Static(id="perf-chart")
                    yield DataTable(id="perf-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="results-actions"):
            yield Button("\\[esc] BACK", variant="default", id="back-btn")
            yield Button("\\[x] EXPORT", variant="success", id="export-btn")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_summary()
        self._populate_func_table()
        if self.report.performance_results:
            self._populate_perf_chart()
            self._populate_perf_table()

    def _populate_summary(self) -> None:
        r = self.report
        rate = f"{r.pass_rate:.0f}%" if r.total_tests else "N/A"
        perf_info = ""
        if r.performance_results:
            total_reqs = sum(pm.total_requests for pm in r.performance_results)
            total_tps = sum(pm.requests_per_second for pm in r.performance_results)
            peak_tps = max((pm.peak_tps for pm in r.performance_results), default=0)
            perf_info = (
                f"    [#cc9944]{total_reqs}[/][#7a7a9a] perf reqs[/]  "
                f"[#55aacc]{total_tps:.1f}[/][#7a7a9a] avg TPS[/]  "
                f"[#cc9944]{peak_tps:.1f}[/][#7a7a9a] peak TPS[/]"
            )
        summary = (
            f"[#55cc55]{r.passed_tests}[/] passed  "
            f"[#cc4444]{r.failed_tests}[/] failed  "
            f"[#cc9944]{r.error_tests}[/] errors  "
            f"[#7a7a9a]{r.total_tests} total[/]  "
            f"[#55aacc]{rate}[/] pass rate  "
            f"[#7a7a9a]{r.duration_seconds:.1f}s[/]"
            f"{perf_info}"
        )
        self.query_one("#results-summary", Static).update(summary)

    def _populate_func_table(self) -> None:
        table = self.query_one("#func-table", DataTable)
        table.add_column("Status", key="status")
        table.add_column("Method", key="method")
        table.add_column("Endpoint", key="endpoint")
        table.add_column("Code", key="code")
        table.add_column("Time", key="time")
        table.add_column("Detail", key="detail")

        self._results_by_row.clear()
        for result in self.report.functional_results:
            status = _status_label(result.status, getattr(result, 'test_type', 'happy'))
            code = str(result.status_code) if result.status_code else "--"
            time_str = f"{result.response_time_ms:.0f}ms" if result.response_time_ms else "--"
            detail = _result_detail(result)

            table.add_row(status, result.method, result.endpoint, code, time_str, detail)
            self._results_by_row.append(result)

    def _populate_perf_chart(self) -> None:
        """Build an aligned latency bar chart with SLA threshold markers."""
        results = self.report.performance_results
        if not results:
            return

        has_any_sla = any(pm.has_sla for pm in results)
        lines: list[str] = []
        lines.append("[bold #cc9944]Latency Distribution (ms)[/]")
        lines.append("")

        max_method = max(len(pm.method) for pm in results)
        max_ep = max(len(pm.endpoint) for pm in results)

        # Header
        sla_hdr = "    SLA" if has_any_sla else ""
        header = (
            f"  [#7a7a9a]{'Method':<{max_method}}  {'Endpoint':<{max_ep}}  "
            f"{'Bar':<40}  {'p50':>5}  {'p95':>5}  {'p99':>5}{sla_hdr}[/]"
        )
        lines.append(header)

        bar_width = 40

        for pm in results:
            method_str = f"{pm.method:<{max_method}}"
            ep_str = f"{pm.endpoint:<{max_ep}}"

            # Per-endpoint scale so each bar uses full width
            sla_val = pm.sla_p99_ms or pm.sla_p95_ms
            ep_max = max(pm.p99_latency_ms, sla_val or 0, 1)

            p50_pos = int((pm.p50_latency_ms / ep_max) * bar_width)
            p95_pos = int((pm.p95_latency_ms / ep_max) * bar_width)
            p99_pos = int((pm.p99_latency_ms / ep_max) * bar_width)
            # Ensure at least 1 char for non-zero values
            if pm.p99_latency_ms > 0 and p99_pos == 0:
                p99_pos = 1
            if pm.p95_latency_ms > 0 and p95_pos == 0:
                p95_pos = 1
            if pm.p50_latency_ms > 0 and p50_pos == 0:
                p50_pos = 1

            # SLA threshold position on the bar
            sla_pos = None
            if sla_val:
                sla_pos = int((sla_val / ep_max) * bar_width)
                sla_pos = min(sla_pos, bar_width - 1)  # keep within bar

            # Check if breaching
            breaching = pm.has_sla and not pm.sla_passed

            # Build bar — if breaching, the portion beyond SLA is bright red
            bar = ""
            for i in range(bar_width):
                if sla_pos is not None and i == sla_pos:
                    # SLA threshold marker
                    bar += "[bold #ffffff]│[/]"
                elif i < p50_pos:
                    bar += "[#55cc55]█[/]"
                elif i < p95_pos:
                    if breaching and sla_pos and i >= sla_pos:
                        bar += "[bold #ff0000]█[/]"
                    else:
                        bar += "[#cc9944]█[/]"
                elif i < p99_pos:
                    if breaching and sla_pos and i >= sla_pos:
                        bar += "[bold #ff0000]█[/]"
                    else:
                        bar += "[#cc4444]█[/]"
                else:
                    bar += "[#333355]▏[/]"

            # SLA column
            sla_str = ""
            if has_any_sla:
                if not pm.has_sla:
                    sla_str = "  [#7a7a9a]   --[/]"
                elif pm.sla_passed:
                    threshold = pm.sla_p99_ms or pm.sla_p95_ms or 0
                    sla_str = f"  [#55cc55]{threshold:>4.0f}[/][#55cc55] OK[/]"
                else:
                    threshold = pm.sla_p99_ms or pm.sla_p95_ms or 0
                    sla_str = f"  [#ff0000]{threshold:>4.0f}[/][#ff0000] !!![/]"

            lines.append(
                f"  [#7a7a9a]{method_str}[/]  [#c0c0d0]{ep_str}[/]  {bar}  "
                f"[#55cc55]{pm.p50_latency_ms:>5.0f}[/]  "
                f"[#cc9944]{pm.p95_latency_ms:>5.0f}[/]  "
                f"[#cc4444]{pm.p99_latency_ms:>5.0f}[/]"
                f"{sla_str}"
            )

        lines.append("")
        legend = (
            "  [#7a7a9a]Legend:[/]  "
            "[#55cc55]██[/] [#7a7a9a]p50[/]  "
            "[#cc9944]██[/] [#7a7a9a]p95[/]  "
            "[#cc4444]██[/] [#7a7a9a]p99[/]"
        )
        if has_any_sla:
            legend += "  [bold #ffffff]│[/] [#7a7a9a]SLA threshold[/]  [bold #ff0000]██[/] [#7a7a9a]breach[/]"
        lines.append(legend)

        # SLA summary
        sla_endpoints = [pm for pm in results if pm.has_sla]
        if sla_endpoints:
            breaches = [pm for pm in sla_endpoints if not pm.sla_passed]
            lines.append("")
            if breaches:
                lines.append(f"  [bold #ff0000]SLA BREACHES: {len(breaches)}/{len(sla_endpoints)} endpoints[/]")
                for pm in breaches:
                    for check in pm.sla_checks:
                        if not check.passed:
                            lines.append(f"    [#ff0000]✗ {pm.method} {pm.endpoint}: {check.message}[/]")
            else:
                lines.append(f"  [#55cc55]✓ All SLAs met ({len(sla_endpoints)} endpoints)[/]")

        self.query_one("#perf-chart", Static).update("\n".join(lines))

    def _populate_perf_table(self) -> None:
        table = self.query_one("#perf-table", DataTable)
        table.add_column("Method", key="method")
        table.add_column("Endpoint", key="endpoint")
        table.add_column("Reqs", key="reqs")
        table.add_column("TPS", key="tps")
        table.add_column("Avg", key="avg")
        table.add_column("P50", key="p50")
        table.add_column("P95", key="p95")
        table.add_column("P99", key="p99")
        table.add_column("Min", key="min")
        table.add_column("Max", key="max")
        table.add_column("Errors", key="errors")
        table.add_column("SLA", key="sla")
        table.add_column("Status", key="sla_status")

        for pm in self.report.performance_results:
            method = _method_label(pm.method)
            err_color = "#cc4444" if pm.error_rate_pct > 1 else "#7a7a9a"

            # Color p95/p99 red if breaching their specific SLA
            p95_breach = pm.sla_p95_ms and pm.p95_latency_ms > pm.sla_p95_ms
            p99_breach = pm.sla_p99_ms and pm.p99_latency_ms > pm.sla_p99_ms
            p95_color = "#ff0000" if p95_breach else "#cc9944"
            p99_color = "#ff0000" if p99_breach else "#cc4444"

            # SLA threshold display
            if pm.has_sla:
                sla_parts = []
                if pm.sla_p95_ms:
                    sla_parts.append(f"p95<{pm.sla_p95_ms:.0f}")
                if pm.sla_p99_ms:
                    sla_parts.append(f"p99<{pm.sla_p99_ms:.0f}")
                if pm.sla_throughput_rps:
                    sla_parts.append(f">{pm.sla_throughput_rps:.0f}tps")
                if pm.sla_timeout_ms:
                    sla_parts.append(f"max<{pm.sla_timeout_ms:.0f}")
                sla_label = " ".join(sla_parts)
            else:
                sla_label = "[#7a7a9a]--[/]"

            # SLA status
            if pm.has_sla:
                status_label = "[#55cc55]OK[/]" if pm.sla_passed else "[bold #ff0000]BREACH[/]"
            else:
                status_label = "[#7a7a9a]--[/]"

            table.add_row(
                method,
                pm.endpoint,
                str(pm.total_requests),
                f"[#55aacc]{pm.requests_per_second:.1f}[/]",
                f"{pm.avg_latency_ms:.0f}ms",
                f"{pm.p50_latency_ms:.0f}ms",
                f"[{p95_color}]{pm.p95_latency_ms:.0f}ms[/]",
                f"[{p99_color}]{pm.p99_latency_ms:.0f}ms[/]",
                f"{pm.min_latency_ms:.0f}ms",
                f"{pm.max_latency_ms:.0f}ms",
                f"[{err_color}]{pm.error_rate_pct:.1f}%[/]",
                sla_label,
                status_label,
            )

    def action_inspect_selected(self) -> None:
        table = self.query_one("#func-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is not None and row_idx < len(self._results_by_row):
            result = self._results_by_row[row_idx]
            from specs_agent.screens.result_detail_modal import ResultDetailModal
            self.app.push_screen(ResultDetailModal(result))

    def action_export_report(self) -> None:
        from specs_agent.screens.report_export import ReportExportModal
        self.app.push_screen(ReportExportModal(self.report))

    def action_cursor_down(self) -> None:
        try:
            self.query_one("#func-table", DataTable).action_cursor_down()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        try:
            self.query_one("#func-table", DataTable).action_cursor_up()
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#back-btn")
    def on_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#export-btn")
    def on_export_pressed(self) -> None:
        self.action_export_report()

    @on(DataTable.RowSelected, "#func-table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_inspect_selected()


def _status_label(status: TestStatus, test_type: str = "happy") -> str:
    icon = "😈" if test_type == "sad" else "😊"
    return {
        TestStatus.PASSED: f"[#55cc55]{icon} PASS[/]",
        TestStatus.FAILED: f"[#cc4444]{icon} FAIL[/]",
        TestStatus.ERROR: f"[#cc9944]{icon} ERR[/]",
        TestStatus.SKIPPED: f"[#7a7a9a]{icon} SKIP[/]",
    }.get(status, f"[#7a7a9a]{icon} ?[/]")


def _method_label(method: str) -> str:
    colors = {
        "GET": "#55cc55", "POST": "#cc9944", "PUT": "#5599dd",
        "PATCH": "#55aacc", "DELETE": "#cc4444",
    }
    color = colors.get(method, "#c0c0d0")
    return f"[{color}]{method}[/]"


def _result_detail(result: TestResult) -> str:
    if result.error_message:
        return result.error_message[:60]
    if result.assertion_results:
        failed = [a for a in result.assertion_results if not a.passed]
        if failed:
            return failed[0].message[:60]
    return ""
