"""Report export modal -- save report as HTML or PDF."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from specs_agent.models.results import Report
from specs_agent.reporting.generator import generate_html_report, generate_pdf_report


class ReportExportModal(ModalScreen[str | None]):
    """Overlay for exporting test report."""

    DEFAULT_CSS = """
    ReportExportModal {
        align: center middle;
        background: transparent;
    }
    #export-frame {
        width: 70;
        height: auto;
        max-height: 60%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #export-title {
        dock: top;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    .form-label {
        color: #7a7a9a;
        margin-top: 1;
    }
    #export-footer {
        dock: bottom;
        height: 3;
        align-horizontal: center;
        margin-top: 1;
    }
    #export-status {
        color: #55cc55;
        text-align: center;
        width: 100%;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, report: Report, **kwargs) -> None:
        super().__init__(**kwargs)
        self.report = report
        self._default_dir = str(Path.home() / ".specs-agent" / "reports")

    def compose(self) -> ComposeResult:
        with Vertical(id="export-frame"):
            yield Static("EXPORT REPORT", id="export-title")
            yield Label("Format", classes="form-label")
            yield Select(
                [("HTML", "html"), ("PDF (requires weasyprint)", "pdf")],
                value="html",
                id="format-select",
            )
            yield Label("Output directory", classes="form-label")
            yield Input(value=self._default_dir, id="output-dir-input")
            yield Checkbox("Open after export", value=True, id="open-check")
            yield Static("", id="export-status")
            with Horizontal(id="export-footer"):
                yield Button("\\[esc] CANCEL", variant="default", id="cancel-btn")
                yield Button("EXPORT", variant="success", id="export-btn")

    @on(Button.Pressed, "#export-btn")
    def on_export(self) -> None:
        fmt_select = self.query_one("#format-select", Select)
        fmt = str(fmt_select.value) if fmt_select.value != Select.BLANK else "html"
        output_dir = self.query_one("#output-dir-input", Input).value.strip()
        open_after = self.query_one("#open-check", Checkbox).value

        # Build filename
        safe_name = self.report.plan_name.replace(" ", "_").lower()[:40]
        timestamp = self.report.started_at[:19].replace(":", "-").replace("T", "_")
        filename = f"{safe_name}_{timestamp}.{fmt}"
        output_path = str(Path(output_dir) / filename)

        status = self.query_one("#export-status", Static)

        try:
            if fmt == "pdf":
                path = generate_pdf_report(self.report, output_path)
            else:
                path = generate_html_report(self.report, output_path)

            status.update(f"[#55cc55]Exported to {path}[/]")

            if open_after:
                _open_file(path)

            self.dismiss(path)

        except ImportError as exc:
            status.update(f"[#cc4444]{exc}[/]")
        except Exception as exc:
            status.update(f"[#cc4444]Export failed: {exc}[/]")

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_btn(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _open_file(path: str) -> None:
    """Open a file with the system default application."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", path])
        elif sys.platform == "win32":
            subprocess.Popen(["start", path], shell=True)
    except Exception:
        pass
