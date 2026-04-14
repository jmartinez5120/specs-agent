"""Scan preview modal -- shows what will happen before loading a spec."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from specs_agent.models.spec import ParsedSpec
from specs_agent.persistence import load_plan


class ScanPreviewModal(ModalScreen[bool | str]):
    """Preview modal shown before loading a spec — warns about overwrites."""

    DEFAULT_CSS = """
    ScanPreviewModal {
        align: center middle;
        background: transparent;
    }
    #preview-frame {
        width: 90%;
        height: 80%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #preview-title {
        dock: top;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    #preview-scroll {
        height: 1fr;
        margin: 1 0;
    }
    #preview-footer {
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

    def __init__(self, spec: ParsedSpec, source: str, old_spec: ParsedSpec | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.spec = spec
        self.source = source
        self.old_spec = old_spec

    def compose(self) -> ComposeResult:
        with Vertical(id="preview-frame"):
            yield Static("SCAN PREVIEW", id="preview-title")
            with VerticalScroll(id="preview-scroll"):
                yield Static(self._build_preview())
            with Horizontal(id="preview-footer"):
                yield Button("\\[esc] CANCEL", variant="default", id="cancel-btn")
                yield Button("\\[r] REFRESH", variant="primary", id="refresh-btn")
                yield Button("\\[enter] PROCEED", variant="success", id="proceed-btn")

    def _build_preview(self) -> str:
        spec = self.spec
        lines: list[str] = []

        # Spec info
        lines.append(f"[bold #55cc55]{spec.title}[/] [#7a7a9a]v{spec.version}[/]")
        if spec.description:
            lines.append(f"[#7a7a9a]{spec.description[:100]}[/]")
        lines.append(f"\n[#cc9944]Base URL:[/] [#55aacc]{spec.base_url}[/]")
        lines.append(f"[#cc9944]Source:[/] [#7a7a9a]{self.source}[/]")
        lines.append(f"[#cc9944]Endpoints:[/] [#c0c0d0]{len(spec.endpoints)}[/]")
        lines.append(f"[#cc9944]Tags:[/] [#c0c0d0]{', '.join(spec.tags) or 'auto-detected'}[/]")

        # If refreshing with old spec, show diff instead of plain endpoint list
        if self.old_spec:
            self._build_diff_section(lines)
        else:
            self._build_endpoint_list(lines)

        # Check for existing saved plan
        saved_plan = self._check_saved_plan()
        if saved_plan:
            lines.append(f"\n[bold #ff0000]⚠ EXISTING PLAN FOUND[/]")
            lines.append(f"  [#c0c0d0]Plan:[/] [#7a7a9a]{saved_plan['name']}[/]")
            lines.append(f"  [#c0c0d0]Test cases:[/] [#7a7a9a]{saved_plan['cases']}[/]")
            lines.append(f"  [#c0c0d0]Created:[/] [#7a7a9a]{saved_plan['created']}[/]")

            # Compare endpoints
            saved_endpoints = set(saved_plan.get("endpoints", []))
            fresh_endpoints = {f"{ep.method.value} {ep.path}" for ep in spec.endpoints}

            new_eps = fresh_endpoints - saved_endpoints
            removed_eps = saved_endpoints - fresh_endpoints

            if new_eps or removed_eps:
                lines.append(f"\n[#7a7a9a]Your intel from unchanged endpoints will be preserved.[/]")
                lines.append(f"[#7a7a9a]The old plan will be archived.[/]")
            else:
                lines.append(f"\n[#55cc55]No endpoint changes — your saved intel will be restored.[/]")
        elif not self.old_spec:
            lines.append(f"\n[#55cc55]No existing plan — a fresh test plan will be generated.[/]")

        return "\n".join(lines)

    def _build_endpoint_list(self, lines: list[str]) -> None:
        """Show plain endpoint list (initial load)."""
        lines.append(f"\n[bold #cc9944]Endpoints[/]")
        by_tag = self.spec.endpoints_by_tag
        for tag, eps in sorted(by_tag.items()):
            lines.append(f"  [bold #cc9944]{tag}[/] [#7a7a9a]({len(eps)})[/]")
            for ep in eps:
                color = _method_color(ep.method.value)
                sla = ""
                if ep.performance_sla and ep.performance_sla.latency_p99_ms:
                    sla = f" [#7a7a9a]SLA p99<{ep.performance_sla.latency_p99_ms:.0f}ms[/]"
                lines.append(f"    [{color}]{ep.method.value:<6}[/] [#c0c0d0]{ep.path}[/]{sla}")

    def _build_diff_section(self, lines: list[str]) -> None:
        """Compare old_spec vs new spec and highlight all differences."""
        old = self.old_spec
        new = self.spec

        # Build endpoint lookup: key -> Endpoint
        old_eps = {f"{ep.method.value} {ep.path}": ep for ep in old.endpoints}
        new_eps = {f"{ep.method.value} {ep.path}": ep for ep in new.endpoints}

        old_keys = set(old_eps.keys())
        new_keys = set(new_eps.keys())

        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        common = sorted(old_keys & new_keys)

        # Detect modified endpoints
        modified: list[tuple[str, list[str]]] = []
        unchanged: list[str] = []
        for key in common:
            changes = _diff_endpoint(old_eps[key], new_eps[key])
            if changes:
                modified.append((key, changes))
            else:
                unchanged.append(key)

        # Header with counts
        lines.append(f"\n[bold #cc9944]REFRESH DIFF[/] [#7a7a9a](vs previously loaded spec)[/]")
        parts = []
        if added:
            parts.append(f"[#55aacc]{len(added)} new[/]")
        if removed:
            parts.append(f"[#cc4444]{len(removed)} removed[/]")
        if modified:
            parts.append(f"[#cc9944]{len(modified)} modified[/]")
        if unchanged:
            parts.append(f"[#55cc55]{len(unchanged)} unchanged[/]")
        lines.append(f"  {' · '.join(parts)}")

        if not added and not removed and not modified:
            lines.append(f"\n[#55cc55]No changes detected — spec is identical.[/]")
            return

        # New endpoints
        if added:
            lines.append(f"\n  [bold #55aacc]+ New Endpoints[/]")
            for key in added:
                ep = new_eps[key]
                color = _method_color(ep.method.value)
                summary = f" [#7a7a9a]{ep.summary}[/]" if ep.summary else ""
                lines.append(f"    [#55aacc]+[/] [{color}]{ep.method.value:<6}[/] [#c0c0d0]{ep.path}[/]{summary}")

        # Removed endpoints
        if removed:
            lines.append(f"\n  [bold #cc4444]- Removed Endpoints[/]")
            for key in removed:
                ep = old_eps[key]
                color = _method_color(ep.method.value)
                lines.append(f"    [#cc4444]-[/] [{color}]{ep.method.value:<6}[/] [#7a7a9a]{ep.path}[/]")

        # Modified endpoints
        if modified:
            lines.append(f"\n  [bold #cc9944]~ Modified Endpoints[/]")
            for key, changes in modified:
                ep = new_eps[key]
                color = _method_color(ep.method.value)
                lines.append(f"    [#cc9944]~[/] [{color}]{ep.method.value:<6}[/] [#c0c0d0]{ep.path}[/]")
                for change in changes:
                    lines.append(f"      [#7a7a9a]{change}[/]")

        # Unchanged (collapsed)
        if unchanged:
            lines.append(f"\n  [#55cc55]✓ {len(unchanged)} endpoints unchanged[/]")

    def _check_saved_plan(self) -> dict | None:
        """Check if there's a saved plan for this spec."""
        save_dir = Path.home() / ".specs-agent" / "plans"
        safe_name = f"{self.spec.title} Test Plan".replace(" ", "_").lower()[:40]
        path = save_dir / f"{safe_name}.yaml"
        if not path.exists():
            return None

        try:
            plan = load_plan(str(path))
            endpoints = [f"{tc.method} {tc.endpoint_path}" for tc in plan.test_cases]
            # Deduplicate (multiple test cases per endpoint)
            unique_eps = sorted(set(endpoints))
            return {
                "name": plan.name,
                "cases": plan.total_count,
                "created": plan.created_at[:16].replace("T", " ") if plan.created_at else "unknown",
                "endpoints": unique_eps,
            }
        except Exception:
            return None

    @on(Button.Pressed, "#proceed-btn")
    def on_proceed(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_btn(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_refresh(self) -> None:
        self.dismiss("refresh")

    @on(Button.Pressed, "#refresh-btn")
    def on_refresh(self) -> None:
        self.action_refresh()

    def action_proceed(self) -> None:
        self.dismiss(True)


def _method_color(method: str) -> str:
    return {
        "GET": "#55cc55", "POST": "#cc9944", "PUT": "#5599dd",
        "PATCH": "#55aacc", "DELETE": "#cc4444",
    }.get(method, "#c0c0d0")


def _diff_endpoint(old, new) -> list[str]:
    """Compare two Endpoint objects and return a list of human-readable changes."""
    changes: list[str] = []

    # Summary
    if old.summary != new.summary:
        changes.append(f"summary: \"{old.summary}\" → \"{new.summary}\"")

    # Parameters
    old_params = {p.name: p for p in old.parameters}
    new_params = {p.name: p for p in new.parameters}
    for name in sorted(set(new_params) - set(old_params)):
        p = new_params[name]
        changes.append(f"+ param: {name} ({p.location.value}, {p.schema_type})")
    for name in sorted(set(old_params) - set(new_params)):
        changes.append(f"- param: {name}")
    for name in sorted(set(old_params) & set(new_params)):
        op, np = old_params[name], new_params[name]
        diffs = []
        if op.schema_type != np.schema_type:
            diffs.append(f"type {op.schema_type}→{np.schema_type}")
        if op.required != np.required:
            diffs.append(f"required {op.required}→{np.required}")
        if diffs:
            changes.append(f"~ param {name}: {', '.join(diffs)}")

    # Request body schema
    old_body = old.request_body_schema or {}
    new_body = new.request_body_schema or {}
    if old_body != new_body:
        old_props = set((old_body.get("properties") or {}).keys())
        new_props = set((new_body.get("properties") or {}).keys())
        added = new_props - old_props
        removed = old_props - new_props
        if added:
            changes.append(f"+ body fields: {', '.join(sorted(added))}")
        if removed:
            changes.append(f"- body fields: {', '.join(sorted(removed))}")
        if not added and not removed:
            changes.append("~ request body schema changed")

    # Responses
    old_codes = {r.status_code for r in old.responses}
    new_codes = {r.status_code for r in new.responses}
    for code in sorted(new_codes - old_codes):
        changes.append(f"+ response: {code}")
    for code in sorted(old_codes - new_codes):
        changes.append(f"- response: {code}")

    # SLA
    old_sla = old.performance_sla
    new_sla = new.performance_sla
    if (old_sla is None) != (new_sla is None):
        if new_sla:
            changes.append("+ performance SLA added")
        else:
            changes.append("- performance SLA removed")
    elif old_sla and new_sla:
        sla_diffs = []
        if old_sla.latency_p99_ms != new_sla.latency_p99_ms:
            sla_diffs.append(f"p99 {old_sla.latency_p99_ms}→{new_sla.latency_p99_ms}ms")
        if old_sla.latency_p95_ms != new_sla.latency_p95_ms:
            sla_diffs.append(f"p95 {old_sla.latency_p95_ms}→{new_sla.latency_p95_ms}ms")
        if old_sla.throughput_rps != new_sla.throughput_rps:
            sla_diffs.append(f"TPS {old_sla.throughput_rps}→{new_sla.throughput_rps}")
        if sla_diffs:
            changes.append(f"~ SLA: {', '.join(sla_diffs)}")

    return changes
