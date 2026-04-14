"""Result detail modal -- full request/response detail with failure explanation."""

from __future__ import annotations

import json

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from specs_agent.models.results import TestResult, TestStatus


class ResultDetailModal(ModalScreen[None]):
    """Overlay showing full detail of a single test result."""

    DEFAULT_CSS = """
    ResultDetailModal {
        align: center middle;
        background: transparent;
    }
    #rd-frame {
        width: 90%;
        height: 85%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #rd-title {
        dock: top;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    #rd-content {
        height: 1fr;
    }
    #rd-left {
        width: 1fr;
        height: 1fr;
        margin: 1 0;
    }
    #rd-live-result {
        height: auto;
    }
    #rd-right {
        width: 1fr;
        height: 1fr;
        margin: 1 0;
        border-left: solid #333355;
        padding-left: 1;
    }
    #rd-spec-content {
        color: #c0c0d0;
    }
    #rd-footer-buttons {
        dock: bottom;
        height: 3;
        align-horizontal: center;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("d", "close", "Close"),
        ("t", "try_again", "Try Again"),
        ("s", "show_spec", "Show Spec"),
    ]

    def __init__(self, result: TestResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self.result = result

    def compose(self) -> ComposeResult:
        with Vertical(id="rd-frame"):
            yield Static("TEST RESULT DETAIL", id="rd-title")
            with Horizontal(id="rd-content"):
                with VerticalScroll(id="rd-left"):
                    yield Static(self._build_detail(), id="rd-detail")
                    yield Static("", id="rd-live-result")
                with VerticalScroll(id="rd-right"):
                    yield Static("[#7a7a9a]Press \\[s] to show endpoint spec[/]", id="rd-spec-content")
            with Horizontal(id="rd-footer-buttons"):
                yield Button("\\[d] CLOSE", variant="default", id="rd-close-btn")
                yield Button("\\[t] TRY AGAIN", variant="primary", id="rd-try-btn")
                yield Button("\\[s] SHOW SPEC", variant="warning", id="rd-spec-btn")

    def _build_detail(self) -> str:
        r = self.result
        lines: list[str] = []

        # Status header
        color = _status_color(r.status)
        type_icon = "😈" if r.test_type == "sad" else "😊"
        lines.append(f"  [{color}]{type_icon} {r.status.value.upper()}[/] [bold #55cc55]{r.method}[/] [#c0c0d0]{r.endpoint}[/]")
        lines.append(f"  [#7a7a9a]{r.test_case_name}[/]")

        # Failure explanation
        if r.status == TestStatus.FAILED:
            lines.append(f"\n  [bold #cc4444]Why it failed[/]")
            lines.append(f"  {_explain_failure(r)}")
        elif r.status == TestStatus.ERROR:
            lines.append(f"\n  [bold #cc9944]Error[/]")
            lines.append(f"  [#cc4444]{r.error_message}[/]")

        # Request section
        lines.append(f"\n  [bold #cc9944]Request[/]")
        lines.append(f"    [#c0c0d0]URL:[/] [#55aacc]{r.request_url or 'N/A'}[/]")
        lines.append(f"    [#c0c0d0]Method:[/] [#55cc55]{r.method}[/]")

        if r.request_headers:
            lines.append(f"\n    [#c0c0d0]Request Headers[/]")
            for k, v in r.request_headers.items():
                # Mask auth values
                display_v = v
                if k.lower() == "authorization" and len(v) > 20:
                    display_v = v[:15] + "..." + v[-4:]
                lines.append(f"      [#7a7a9a]{k}:[/] [#55aacc]{display_v}[/]")
        else:
            lines.append(f"    [#7a7a9a]No custom headers[/]")

        if r.request_body is not None:
            lines.append(f"\n    [#c0c0d0]Request Body[/]")
            body_str = _format_json(r.request_body, max_lines=15)
            for bl in body_str.split("\n"):
                lines.append(f"      [#55aacc]{bl}[/]")
        else:
            lines.append(f"    [#7a7a9a]No request body[/]")

        # Response section
        if r.status_code:
            lines.append(f"\n  [bold #cc9944]Response[/]")
            lines.append(f"    [#c0c0d0]Status:[/] [{color}]{r.status_code}[/]")
            lines.append(f"    [#c0c0d0]Time:[/] [#55aacc]{r.response_time_ms:.1f}ms[/]")

            if r.response_headers:
                lines.append(f"\n    [#c0c0d0]Response Headers[/]")
                for k, v in list(r.response_headers.items())[:15]:
                    lines.append(f"      [#7a7a9a]{k}:[/] [#c0c0d0]{v}[/]")
                if len(r.response_headers) > 15:
                    lines.append(f"      [#7a7a9a]... and {len(r.response_headers) - 15} more[/]")

        # Assertions
        if r.assertion_results:
            lines.append(f"\n  [bold #cc9944]Assertions ({len(r.assertion_results)})[/]")
            for ar in r.assertion_results:
                icon = "[#55cc55]✓[/]" if ar.passed else "[#cc4444]✗[/]"
                lines.append(f"    {icon} [#c0c0d0]{ar.assertion_type}[/]")
                lines.append(f"        [#7a7a9a]expected:[/] [#55aacc]{ar.expected}[/]")
                lines.append(f"        [#7a7a9a]actual:[/]   [#c0c0d0]{ar.actual}[/]")
                if ar.message:
                    lines.append(f"        [#cc4444]{ar.message}[/]")

        # Response body
        if r.response_body is not None:
            lines.append(f"\n  [bold #cc9944]Response Body[/]")
            body_str = _format_json(r.response_body, max_lines=25)
            for bl in body_str.split("\n"):
                lines.append(f"    [#7a7a9a]{bl}[/]")

        return "\n".join(lines)

    @work(thread=False)
    async def action_try_again(self) -> None:
        """Re-execute the same test case and show the result inline."""
        result_widget = self.query_one("#rd-live-result", Static)
        result_widget.update("\n  [#cc9944]Sending request...[/]")

        # Find the test case from the plan
        tc = self._find_test_case()
        if not tc:
            result_widget.update("\n  [#cc4444]Could not find test case in plan[/]")
            return

        from specs_agent.execution.functional import FunctionalExecutor
        from specs_agent.models.config import TestRunConfig

        base_url = ""
        config = TestRunConfig(timeout_seconds=10.0)
        if hasattr(self.app, "test_plan") and self.app.test_plan:
            base_url = self.app.test_plan.base_url
        if hasattr(self.app, "run_config"):
            rc = self.app.run_config
            config.base_url = rc.base_url or base_url
            config.auth_type = rc.auth_type
            config.auth_value = rc.auth_value
            config.verify_ssl = rc.verify_ssl
            config.follow_redirects = rc.follow_redirects
            config.timeout_seconds = rc.timeout_seconds
        if not config.base_url:
            config.base_url = base_url

        executor = FunctionalExecutor(config)
        new_result = await executor.execute(tc)

        # Format the new result
        color = _status_color(new_result.status)
        type_icon = "😈" if new_result.test_type == "sad" else "😊"
        lines = [
            f"\n  [bold #cc9944]Retry Result[/]",
            f"  [{color}]{type_icon} {new_result.status.value.upper()}[/]  "
            f"[#c0c0d0]{new_result.method} {new_result.endpoint}[/]",
        ]
        if new_result.status_code:
            lines.append(f"    Status: [{color}]{new_result.status_code}[/]  Time: [#55aacc]{new_result.response_time_ms:.0f}ms[/]")
        if new_result.error_message:
            lines.append(f"    [#cc4444]{new_result.error_message}[/]")
        for ar in new_result.assertion_results:
            icon = "[#55cc55]✓[/]" if ar.passed else "[#cc4444]✗[/]"
            lines.append(f"    {icon} {ar.assertion_type}: {ar.actual}")
        if new_result.response_body is not None:
            body_str = _format_json(new_result.response_body, max_lines=30)
            lines.append(f"    [#7a7a9a]Body:[/]")
            for bline in body_str.split("\n"):
                lines.append(f"      [#7a7a9a]{bline}[/]")

        if new_result.response_headers:
            lines.append(f"\n    [bold #cc9944]Response Headers[/]")
            for hk, hv in new_result.response_headers.items():
                lines.append(f"      [#7a7a9a]{hk}: {hv}[/]")

        result_widget.update("\n".join(lines))

    def action_show_spec(self) -> None:
        """Show the spec detail for this endpoint on the right panel."""
        target = self.query_one("#rd-spec-content", Static)
        spec = getattr(self.app, "parsed_spec", None)
        if not spec:
            target.update("[#cc4444]No spec loaded[/]")
            return

        r = self.result
        parts = r.endpoint.split(" ", 1)
        method = parts[0] if parts else r.method
        path = parts[1] if len(parts) > 1 else ""

        matching = [ep for ep in spec.endpoints if ep.method.value == method and ep.path == path]
        if not matching:
            target.update(f"[#cc4444]Endpoint {method} {path} not found in spec[/]")
            return

        ep = matching[0]
        lines = [f"[bold #55cc55]{method} {ep.path}[/]"]
        if ep.summary:
            lines.append(f"[#c0c0d0]{ep.summary}[/]")
        if ep.description and ep.description != ep.summary:
            lines.append(f"[#7a7a9a]{ep.description}[/]")
        if ep.operation_id:
            lines.append(f"\n[#cc9944]Operation:[/] {ep.operation_id}")
        if ep.tags:
            lines.append(f"[#cc9944]Tags:[/] {', '.join(ep.tags)}")

        # Parameters
        if ep.parameters:
            lines.append(f"\n[bold #cc9944]Parameters[/]")
            for p in ep.parameters:
                req = "[#cc4444]*[/]" if p.required else " "
                fmt = f"/{p.schema_type}" if p.schema_type else ""
                lines.append(f"  {req} [bold #c0c0d0]{p.name}[/] [#7a7a9a]({p.location.value})[/] [#55aacc]{p.schema_type}[/]")
                if p.description:
                    lines.append(f"    [#7a7a9a]{p.description}[/]")
                if p.enum_values:
                    lines.append(f"    [#7a7a9a]enum: {', '.join(str(e) for e in p.enum_values)}[/]")

        # Request body
        if ep.request_body_schema:
            lines.append(f"\n[bold #cc9944]Request Body[/]")
            schema = ep.request_body_schema
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            if props:
                for name, prop in props.items():
                    req = "[#cc4444]*[/]" if name in required else " "
                    ptype = prop.get("type", "?")
                    fmt = prop.get("format", "")
                    type_str = f"{ptype}/{fmt}" if fmt else ptype
                    extra = ""
                    if prop.get("enum"):
                        extra = f" [#7a7a9a]enum: {prop['enum']}[/]"
                    if prop.get("description"):
                        extra += f" [#7a7a9a]{prop['description'][:40]}[/]"
                    lines.append(f"  {req} [#c0c0d0]{name}[/] [#55aacc]{type_str}[/]{extra}")
            elif schema.get("additionalProperties"):
                lines.append(f"  [#55aacc]map<string, {schema['additionalProperties'].get('type', 'any')}>")

        # Responses — show ALL with full detail
        if ep.responses:
            lines.append(f"\n[bold #cc9944]Responses[/]")
            for resp in ep.responses:
                code_color = "#55cc55" if resp.status_code < 300 else "#cc9944" if resp.status_code < 400 else "#cc4444"
                lines.append(f"  [{code_color}]{resp.status_code}[/] [#c0c0d0]{resp.description}[/]")
                # Show response schema if available
                if resp.schema:
                    schema = resp.schema
                    if "$ref" in schema:
                        ref = schema["$ref"].split("/")[-1]
                        lines.append(f"    [#55aacc]schema: {ref}[/]")
                    elif schema.get("type") == "array":
                        items = schema.get("items", {})
                        if "$ref" in items:
                            ref = items["$ref"].split("/")[-1]
                            lines.append(f"    [#55aacc]schema: array of {ref}[/]")
                        else:
                            lines.append(f"    [#55aacc]schema: array[/]")
                    elif schema.get("type") == "object":
                        props = schema.get("properties", {})
                        for name, prop in props.items():
                            ptype = prop.get("type", "?")
                            fmt = prop.get("format", "")
                            type_str = f"{ptype}/{fmt}" if fmt else ptype
                            lines.append(f"      [#c0c0d0]{name}[/] [#55aacc]{type_str}[/]")
        else:
            lines.append(f"\n[#7a7a9a]No responses documented in spec[/]")

        # Security
        if ep.security:
            lines.append(f"\n[bold #cc9944]Security[/]")
            for sec in ep.security:
                for name, scopes in sec.items():
                    lines.append(f"  [#c0c0d0]{name}[/] [#7a7a9a]{', '.join(scopes) if scopes else ''}[/]")

        # Performance SLA
        if ep.performance_sla:
            sla = ep.performance_sla
            lines.append(f"\n[bold #cc9944]Performance SLA[/]")
            if sla.latency_p95_ms:
                lines.append(f"  p95: [#55aacc]{sla.latency_p95_ms:.0f}ms[/]")
            if sla.latency_p99_ms:
                lines.append(f"  p99: [#55aacc]{sla.latency_p99_ms:.0f}ms[/]")
            if sla.throughput_rps:
                lines.append(f"  throughput: [#55aacc]{sla.throughput_rps:.0f} TPS[/]")

        target.update("\n".join(lines))

    def _find_test_case(self):
        """Find the TestCase matching this result from the current plan."""
        plan = getattr(self.app, "test_plan", None)
        if not plan:
            return None
        for tc in plan.test_cases:
            if tc.id == self.result.test_case_id:
                return tc
        return None

    def action_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#rd-close-btn")
    def on_close_btn(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#rd-try-btn")
    def on_try_btn(self) -> None:
        self.action_try_again()

    @on(Button.Pressed, "#rd-spec-btn")
    def on_spec_btn(self) -> None:
        self.action_show_spec()


def _status_color(status: TestStatus) -> str:
    return {
        TestStatus.PASSED: "#55cc55",
        TestStatus.FAILED: "#cc4444",
        TestStatus.ERROR: "#cc9944",
        TestStatus.SKIPPED: "#7a7a9a",
    }.get(status, "#7a7a9a")


def _format_json(data, max_lines: int = 20) -> str:
    """Pretty-print JSON data, truncated to max_lines."""
    try:
        text = json.dumps(data, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(data)
    lines = text.split("\n")
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"... ({len(text.split(chr(10))) - max_lines} more lines)")
    return "\n".join(lines)


def _explain_failure(r: TestResult) -> str:
    """Generate a human-readable explanation of why a test failed."""
    explanations: list[str] = []

    for ar in r.assertion_results:
        if ar.passed:
            continue

        if ar.assertion_type == "status_code":
            expected = ar.expected
            actual = ar.actual
            if actual == 401:
                explanations.append(
                    f"[#cc4444]Got 401 Unauthorized.[/] The API requires authentication. "
                    f"Configure auth in the Test Configuration (bearer token, API key, or basic auth)."
                )
            elif actual == 403:
                explanations.append(
                    f"[#cc4444]Got 403 Forbidden.[/] The provided credentials don't have "
                    f"sufficient permissions for this endpoint."
                )
            elif actual == 404 and expected != 404:
                explanations.append(
                    f"[#cc4444]Got 404 Not Found.[/] The resource at this path doesn't exist. "
                    f"Check that the path parameters (ID) reference an existing resource."
                )
            elif actual == 400 and expected != 400:
                # Check response body for details
                body_hint = ""
                if isinstance(r.response_body, dict):
                    msg = r.response_body.get("message") or r.response_body.get("error") or r.response_body.get("detail", "")
                    if isinstance(msg, dict):
                        msg = msg.get("message", str(msg))
                    if msg:
                        body_hint = f" Server says: \"{msg}\""
                explanations.append(
                    f"[#cc4444]Got 400 Bad Request.[/] The request data is invalid.{body_hint} "
                    f"Check the request body fields and parameter types."
                )
            elif actual == 405:
                explanations.append(
                    f"[#cc4444]Got 405 Method Not Allowed.[/] The HTTP method {r.method} "
                    f"is not supported on this endpoint."
                )
            elif actual == 415:
                explanations.append(
                    f"[#cc4444]Got 415 Unsupported Media Type.[/] The Content-Type header "
                    f"doesn't match what the API expects (usually application/json)."
                )
            elif actual == 500:
                explanations.append(
                    f"[#cc4444]Got 500 Internal Server Error.[/] The server encountered an "
                    f"unexpected error. This is a server-side bug — check the API logs."
                )
            elif actual == 502 or actual == 503:
                explanations.append(
                    f"[#cc4444]Got {actual}.[/] The server is unavailable or overloaded. "
                    f"Try again later or check if the service is running."
                )
            elif actual == 429:
                explanations.append(
                    f"[#cc4444]Got 429 Too Many Requests.[/] Rate limited. "
                    f"Reduce the request rate or add a delay between tests."
                )
            else:
                explanations.append(
                    f"[#cc4444]Expected status {expected}, got {actual}.[/] "
                    f"The API returned a different status code than documented in the spec."
                )

        elif ar.assertion_type == "response_schema":
            explanations.append(
                f"[#cc4444]Response body doesn't match the expected schema.[/] "
                f"The API returned a different structure than documented. "
                f"Validation error: {ar.message[:100]}"
            )

        elif ar.assertion_type == "response_time_ms":
            explanations.append(
                f"[#cc4444]Response took too long.[/] {ar.message}"
            )

    if not explanations:
        explanations.append("[#cc4444]One or more assertions failed. Check the assertion details above.[/]")

    return "\n  ".join(explanations)
