"""Refresh diff modal -- side-by-side comparison of old vs new spec."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from specs_agent.models.spec import Endpoint, ParsedSpec
from specs_agent.screens.scan_preview import _diff_endpoint


class RefreshDiffModal(ModalScreen[bool | str]):
    """Side-by-side diff of old vs new spec after refresh."""

    DEFAULT_CSS = """
    RefreshDiffModal {
        align: center middle;
        background: transparent;
    }
    #diff-frame {
        width: 95%;
        height: 90%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #diff-title {
        dock: top;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    #diff-summary {
        dock: top;
        text-align: center;
        height: auto;
        padding: 0 2;
        margin-bottom: 1;
    }
    #diff-panels {
        height: 1fr;
    }
    #diff-left {
        width: 1fr;
        border-right: solid #333355;
        padding: 0 1;
    }
    #diff-right {
        width: 1fr;
        padding: 0 1;
    }
    .diff-panel-title {
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }
    #diff-footer {
        dock: bottom;
        height: 3;
        align-horizontal: center;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "proceed", "Proceed"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, old_spec: ParsedSpec, new_spec: ParsedSpec, source: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.old_spec = old_spec
        self.new_spec = new_spec
        self.source = source

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-frame"):
            yield Static("SPEC REFRESH", id="diff-title")
            yield Static(self._build_summary(), id="diff-summary")
            with Horizontal(id="diff-panels"):
                with VerticalScroll(id="diff-left"):
                    yield Static("PREVIOUS", classes="diff-panel-title")
                    yield Static(self._build_spec_panel(self.old_spec, side="old"), id="left-content")
                with VerticalScroll(id="diff-right"):
                    yield Static("UPDATED", classes="diff-panel-title")
                    yield Static(self._build_spec_panel(self.new_spec, side="new"), id="right-content")
            with Horizontal(id="diff-footer"):
                yield Button("\\[esc] CANCEL", variant="default", id="cancel-btn")
                yield Button("\\[r] REFRESH", variant="primary", id="refresh-btn")
                yield Button("\\[enter] APPLY", variant="success", id="proceed-btn")

    def _build_summary(self) -> str:
        old_eps = {f"{ep.method.value} {ep.path}": ep for ep in self.old_spec.endpoints}
        new_eps = {f"{ep.method.value} {ep.path}": ep for ep in self.new_spec.endpoints}

        added = sorted(set(new_eps) - set(old_eps))
        removed = sorted(set(old_eps) - set(new_eps))
        common = set(old_eps) & set(new_eps)
        modified = [k for k in sorted(common) if _diff_endpoint(old_eps[k], new_eps[k])]
        unchanged = len(common) - len(modified)

        parts = []
        if added:
            parts.append(f"[#55aacc]{len(added)} new[/]")
        if removed:
            parts.append(f"[#cc4444]{len(removed)} removed[/]")
        if modified:
            parts.append(f"[#cc9944]{len(modified)} modified[/]")
        if unchanged:
            parts.append(f"[#55cc55]{unchanged} unchanged[/]")

        if not added and not removed and not modified:
            return "[#55cc55]No endpoint changes detected — spec is identical[/]"

        return f"[#7a7a9a]Source: {self.source}[/]\n" + " · ".join(parts)

    def _build_spec_panel(self, spec: ParsedSpec, side: str) -> str:
        """Build the endpoint list for one side, highlighting changes."""
        other = self.new_spec if side == "old" else self.old_spec
        other_eps = {f"{ep.method.value} {ep.path}": ep for ep in other.endpoints}
        this_eps = {f"{ep.method.value} {ep.path}": ep for ep in spec.endpoints}

        lines: list[str] = []
        lines.append(f"[bold #55cc55]{spec.title}[/] [#7a7a9a]v{spec.version}[/]")
        lines.append(f"[#7a7a9a]{len(spec.endpoints)} endpoints[/]")
        lines.append("")

        by_tag = spec.endpoints_by_tag
        for tag, eps in sorted(by_tag.items()):
            lines.append(f"[bold #cc9944]{tag}[/] [#7a7a9a]({len(eps)})[/]")
            for ep in eps:
                key = f"{ep.method.value} {ep.path}"
                color = _method_color(ep.method.value)

                # Determine change status
                if key not in other_eps:
                    if side == "new":
                        # New endpoint in updated spec
                        marker = "[bold #55aacc]+ [/]"
                        line_color = "#55aacc"
                    else:
                        # Removed endpoint (in old, not in new)
                        marker = "[bold #cc4444]- [/]"
                        line_color = "#cc4444"
                elif side == "new" and _diff_endpoint(other_eps[key], ep):
                    marker = "[bold #cc9944]~ [/]"
                    line_color = "#c0c0d0"
                elif side == "old" and _diff_endpoint(ep, other_eps.get(key, ep)):
                    marker = "[bold #cc9944]~ [/]"
                    line_color = "#7a7a9a"
                else:
                    marker = "  "
                    line_color = "#7a7a9a" if side == "old" else "#c0c0d0"

                summary = f" [{line_color}]{ep.summary}[/]" if ep.summary else ""
                lines.append(f"  {marker}[{color}]{ep.method.value:<6}[/] [{line_color}]{ep.path}[/]{summary}")

                # Show change details on the new side
                if side == "new" and key in other_eps:
                    changes = _diff_endpoint(other_eps[key], ep)
                    for change in changes:
                        lines.append(f"          [#cc9944]{change}[/]")

                # Show endpoint details for changed/new items
                if key not in other_eps or (side == "new" and _diff_endpoint(other_eps.get(key, ep), ep)):
                    self._append_endpoint_details(ep, lines, side)

            lines.append("")

        return "\n".join(lines)

    def _append_endpoint_details(self, ep: Endpoint, lines: list[str], side: str) -> None:
        """Add parameter/body/response details for an endpoint."""
        indent = "          "
        detail_color = "#55aacc" if side == "new" else "#cc4444"

        if ep.parameters:
            param_strs = []
            for p in ep.parameters:
                req = "*" if p.required else ""
                param_strs.append(f"{req}{p.name}({p.location.value})")
            lines.append(f"{indent}[{detail_color}]params: {', '.join(param_strs)}[/]")

        if ep.request_body_schema:
            props = ep.request_body_schema.get("properties", {})
            required = set(ep.request_body_schema.get("required", []))
            if props:
                fields = []
                for name in sorted(props):
                    req = "*" if name in required else ""
                    fields.append(f"{req}{name}")
                lines.append(f"{indent}[{detail_color}]body: {', '.join(fields)}[/]")

        if ep.responses:
            codes = " ".join(str(r.status_code) for r in ep.responses)
            lines.append(f"{indent}[{detail_color}]responses: {codes}[/]")

        if ep.performance_sla:
            sla = ep.performance_sla
            parts = []
            if sla.latency_p99_ms:
                parts.append(f"p99<{sla.latency_p99_ms:.0f}ms")
            if sla.throughput_rps:
                parts.append(f"{sla.throughput_rps:.0f}TPS")
            if parts:
                lines.append(f"{indent}[{detail_color}]SLA: {', '.join(parts)}[/]")

    @on(Button.Pressed, "#proceed-btn")
    def on_proceed(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_btn(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#refresh-btn")
    def on_refresh(self) -> None:
        self.dismiss("refresh")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_proceed(self) -> None:
        self.dismiss(True)

    def action_refresh(self) -> None:
        self.dismiss("refresh")


def _method_color(method: str) -> str:
    return {
        "GET": "#55cc55", "POST": "#cc9944", "PUT": "#5599dd",
        "PATCH": "#55aacc", "DELETE": "#cc4444",
    }.get(method, "#c0c0d0")
