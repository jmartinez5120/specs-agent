"""Spec browser screen -- scan targets and plan attack."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from specs_agent.models.spec import Endpoint, ParsedSpec
from specs_agent.screens.navigation import ArrowNavMixin
from specs_agent.widgets.endpoint_tree import EndpointTree


class SpecBrowserScreen(ArrowNavMixin, Screen):
    """Browse API endpoints from a parsed spec."""

    FOCUS_ZONES = [
        ["#tree-panel", "#detail-panel"],
        ["#back-btn", "#generate-plan-btn"],
    ]

    class GeneratePlanRequested(Message):
        """User clicked Generate Plan."""

    DEFAULT_CSS = """
    SpecBrowserScreen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto;
        background: #1a1b2e;
    }
    #browser-content {
        height: 1fr;
    }
    #tree-panel {
        width: 2fr;
        height: 1fr;
    }
    #detail-panel {
        width: 3fr;
        height: 1fr;
        border: solid #333355;
        padding: 1 2;
        overflow-y: auto;
        background: #1a1b2e;
    }
    #detail-content {
        width: 100%;
        color: #c0c0d0;
    }
    #action-bar {
        height: 3;
        align-horizontal: right;
        padding: 0 2;
        background: #1a1b2e;
    }
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("g", "generate_plan", "Plan Attack"),
        ("r", "refresh_spec", "Refresh"),
        ("left", "focus_left", "Left"),
        ("right", "focus_right", "Right"),
    ]

    def __init__(self, spec: ParsedSpec, **kwargs) -> None:
        super().__init__(**kwargs)
        self.spec = spec

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="browser-content"):
            yield EndpointTree(id="tree-panel")
            with VerticalScroll(id="detail-panel", can_focus=True):
                yield Static(
                    "[#7a7a9a]Select a target to analyze[/]",
                    id="detail-content",
                )
        with Horizontal(id="action-bar"):
            yield Button("\\[esc] BACK", variant="default", id="back-btn")
            yield Button("\\[r] REFRESH", variant="primary", id="refresh-btn")
            yield Button("\\[g] PLAN ATTACK", variant="success", id="generate-plan-btn")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one(EndpointTree)
        tree.load_spec(self.spec)
        self._show_spec_overview()

    @on(EndpointTree.NodeSelected)
    def on_node_selected(self, event: EndpointTree.NodeSelected) -> None:
        endpoint = event.node.data
        if isinstance(endpoint, Endpoint):
            self._show_endpoint_detail(endpoint)

    @on(EndpointTree.NodeHighlighted)
    def on_node_highlighted(self, event: EndpointTree.NodeHighlighted) -> None:
        node = event.node
        if isinstance(node.data, Endpoint):
            self._show_endpoint_detail(node.data)
        elif node == node.tree.root:
            self._show_spec_overview()
        elif node.children:
            self._show_tag_overview(node)

    def _show_spec_overview(self) -> None:
        """Show full spec summary when root node is highlighted."""
        spec = self.spec
        lines: list[str] = []
        lines.append(f"[bold #55cc55]{spec.title}[/] [#7a7a9a]v{spec.version}[/]")
        if spec.description:
            lines.append(f"[#c0c0d0]{spec.description}[/]")
        lines.append(f"\n[#cc9944]Base URL:[/] [#55aacc]{spec.base_url}[/]")
        lines.append(f"[#cc9944]Spec version:[/] [#c0c0d0]{spec.spec_version}[/]")
        lines.append(f"[#cc9944]Endpoints:[/] [#c0c0d0]{len(spec.endpoints)}[/]")
        lines.append(f"[#cc9944]Sectors:[/] [#c0c0d0]{', '.join(spec.tags) or 'none'}[/]")

        lines.append(f"\n[bold #cc9944]All Endpoints[/]")
        by_tag = spec.endpoints_by_tag
        for tag, endpoints in sorted(by_tag.items()):
            lines.append(f"\n  [bold #cc9944]{tag}[/]")
            for ep in endpoints:
                icon = f"[{_method_color(ep.method.value)}]{ep.method.value:<6}[/]"
                summary = f" [#7a7a9a]{ep.summary}[/]" if ep.summary else ""
                lines.append(f"    {icon} [#c0c0d0]{ep.path}[/]{summary}")

        self.query_one("#detail-content", Static).update("\n".join(lines))

    def _show_tag_overview(self, node) -> None:
        """Show all endpoints in a tag when a tag node is highlighted."""
        lines: list[str] = []
        # Collect endpoints from children
        endpoints = [child.data for child in node.children if isinstance(child.data, Endpoint)]
        tag_label = str(node.label)
        lines.append(f"[bold #cc9944]{tag_label}[/]")
        lines.append(f"[#7a7a9a]{len(endpoints)} endpoints[/]")

        for ep in endpoints:
            lines.append("")
            icon = f"[{_method_color(ep.method.value)}]{ep.method.value:<6}[/]"
            lines.append(f"  {icon} [#c0c0d0]{ep.path}[/]")
            if ep.summary:
                lines.append(f"    [#7a7a9a]{ep.summary}[/]")
            if ep.parameters:
                params = ", ".join(p.name for p in ep.parameters)
                lines.append(f"    [#555577]params: {params}[/]")
            if ep.responses:
                codes = " ".join(
                    f"[{_status_color(r.status_code)}]{r.status_code}[/]"
                    for r in ep.responses
                )
                lines.append(f"    [#555577]responses: {codes}[/]")

        self.query_one("#detail-content", Static).update("\n".join(lines))

    def _show_endpoint_detail(self, ep: Endpoint) -> str:
        lines: list[str] = []
        lines.append(f"[bold #55cc55]{ep.method.value}[/] [#c0c0d0]{ep.path}[/]")
        if ep.summary:
            lines.append(f"[#c0c0d0]{ep.summary}[/]")
        if ep.description and ep.description != ep.summary:
            lines.append(f"[#7a7a9a]{ep.description}[/]")
        if ep.operation_id:
            lines.append(f"\n[#cc9944]Operation:[/] {ep.operation_id}")
        if ep.tags:
            lines.append(f"[#cc9944]Sector:[/] {', '.join(ep.tags)}")

        # Parameters
        if ep.parameters:
            lines.append(f"\n[bold #cc9944]Parameters[/]")
            for p in ep.parameters:
                req = "[#cc4444]*[/]" if p.required else " "
                lines.append(
                    f"  {req} [bold #c0c0d0]{p.name}[/] [#7a7a9a]({p.location.value})[/] "
                    f"[#55aacc]{p.schema_type}[/]"
                )
                if p.description:
                    lines.append(f"    [#7a7a9a]{p.description}[/]")
                if p.default is not None:
                    lines.append(f"    [#7a7a9a]default:[/] [#55cc55]{p.default}[/]")
                if p.example is not None:
                    lines.append(f"    [#7a7a9a]example:[/] [#55cc55]{p.example}[/]")
                if p.enum_values:
                    lines.append(f"    [#7a7a9a]enum:[/] [#55aacc]{', '.join(str(e) for e in p.enum_values)}[/]")

        # Request Body — show full schema
        if ep.request_body_schema:
            lines.append(f"\n[bold #cc9944]Request Body[/]")
            _format_schema_full(ep.request_body_schema, lines, indent=2)

        # Responses — show full schema for each
        if ep.responses:
            lines.append(f"\n[bold #cc9944]Responses[/]")
            for r in ep.responses:
                lines.append(
                    f"  [{_status_color(r.status_code)}]{r.status_code}[/] "
                    f"[#c0c0d0]{r.description}[/]"
                )
                if r.schema:
                    _format_schema_full(r.schema, lines, indent=4)

        # Security
        if ep.security:
            lines.append(f"\n[bold #cc9944]Security[/]")
            for sec in ep.security:
                for name, scopes in sec.items():
                    scope_str = f" [#7a7a9a]({', '.join(scopes)})[/]" if scopes else ""
                    lines.append(f"  [#c0c0d0]{name}[/]{scope_str}")

        # Performance SLA
        if ep.performance_sla:
            sla = ep.performance_sla
            lines.append(f"\n[bold #cc9944]Performance SLA (x-performance)[/]")
            if sla.latency_p95_ms:
                lines.append(f"  [#c0c0d0]p95:[/] [#55aacc]{sla.latency_p95_ms:.0f}ms[/]")
            if sla.latency_p99_ms:
                lines.append(f"  [#c0c0d0]p99:[/] [#55aacc]{sla.latency_p99_ms:.0f}ms[/]")
            if sla.throughput_rps:
                lines.append(f"  [#c0c0d0]throughput:[/] [#55aacc]{sla.throughput_rps:.0f} TPS[/]")
            if sla.timeout_ms:
                lines.append(f"  [#c0c0d0]timeout:[/] [#55aacc]{sla.timeout_ms:.0f}ms[/]")

        content = "\n".join(lines)
        self.query_one("#detail-content", Static).update(content)
        return content

    @on(Button.Pressed, "#generate-plan-btn")
    def on_generate_plan(self) -> None:
        self.post_message(self.GeneratePlanRequested())

    @on(Button.Pressed, "#back-btn")
    def on_back(self) -> None:
        self.app.pop_screen()

    def action_refresh_spec(self) -> None:
        self.app.call_later(self.app.refresh_spec)

    @on(Button.Pressed, "#refresh-btn")
    def on_refresh(self) -> None:
        self.action_refresh_spec()

    def action_generate_plan(self) -> None:
        self.post_message(self.GeneratePlanRequested())


def _method_color(method: str) -> str:
    return {
        "GET": "#55cc55",
        "POST": "#cc9944",
        "PUT": "#5599dd",
        "PATCH": "#55aacc",
        "DELETE": "#cc4444",
        "OPTIONS": "#9977cc",
        "HEAD": "#7a7a9a",
    }.get(method, "#c0c0d0")


def _status_color(code: int) -> str:
    if 200 <= code < 300:
        return "#55cc55"
    if 300 <= code < 400:
        return "#cc9944"
    if 400 <= code < 500:
        return "#cc4444"
    return "#cc2222"


def _format_schema_full(schema: dict, lines: list[str], indent: int = 2) -> None:
    """Render a full JSON schema with all properties and types."""
    pad = " " * indent
    st = schema.get("type", "object")

    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        lines.append(f"{pad}[#55aacc]$ref: {ref}[/]")
        return

    if st == "array":
        items = schema.get("items", {})
        if "$ref" in items:
            ref = items["$ref"].split("/")[-1]
            lines.append(f"{pad}[#55aacc]array[/] of [#55aacc]{ref}[/]")
        elif items.get("type") == "object":
            lines.append(f"{pad}[#55aacc]array[/] of objects:")
            _format_schema_full(items, lines, indent + 2)
        else:
            lines.append(f"{pad}[#55aacc]array[/] of [#55aacc]{items.get('type', '?')}[/]")
        return

    if st == "object":
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not props:
            lines.append(f"{pad}[#55aacc]object[/]")
            return
        for name, prop in props.items():
            req = "[#cc4444]*[/]" if name in required else " "
            prop_type = prop.get("type", "object")
            fmt = prop.get("format", "")
            type_str = f"{prop_type}"
            if fmt:
                type_str += f"/{fmt}"

            # Nested object or array
            if prop_type == "object" and prop.get("properties"):
                lines.append(f"{pad}{req} [bold #c0c0d0]{name}[/] [#55aacc]{type_str}[/]")
                _format_schema_full(prop, lines, indent + 4)
            elif prop_type == "array":
                items = prop.get("items", {})
                item_hint = items.get("type", items.get("$ref", "?").split("/")[-1])
                lines.append(f"{pad}{req} [bold #c0c0d0]{name}[/] [#55aacc]array\\[{item_hint}][/]")
            elif "$ref" in prop:
                ref = prop["$ref"].split("/")[-1]
                lines.append(f"{pad}{req} [bold #c0c0d0]{name}[/] [#55aacc]{ref}[/]")
            else:
                extra = ""
                if prop.get("enum"):
                    extra = f" [#7a7a9a]enum: {prop['enum']}[/]"
                if prop.get("description"):
                    extra += f" [#7a7a9a]{prop['description'][:60]}[/]"
                if prop.get("minimum") is not None or prop.get("maximum") is not None:
                    mn = prop.get("minimum", "")
                    mx = prop.get("maximum", "")
                    extra += f" [#7a7a9a]range: {mn}..{mx}[/]"
                if prop.get("minLength") is not None or prop.get("maxLength") is not None:
                    mn = prop.get("minLength", "")
                    mx = prop.get("maxLength", "")
                    extra += f" [#7a7a9a]len: {mn}..{mx}[/]"
                lines.append(f"{pad}{req} [bold #c0c0d0]{name}[/] [#55aacc]{type_str}[/]{extra}")
        return

    lines.append(f"{pad}[#55aacc]{st}[/]")
