"""Retry editor modal -- edit request before re-sending from result detail."""

from __future__ import annotations

import json
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from specs_agent.models.plan import TestCase
from specs_agent.models.results import TestResult, TestStatus
from specs_agent.templating.variables import _GENERATORS, list_variables


class RetryEditorModal(ModalScreen[None]):
    """Edit request params/headers/body before retrying."""

    DEFAULT_CSS = """
    RetryEditorModal {
        align: center middle;
        background: transparent;
    }
    #retry-frame {
        width: 92%;
        height: 90%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #retry-title {
        dock: top;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    #retry-panels {
        height: 1fr;
    }
    #retry-editor {
        width: 1fr;
        padding: 0 1;
    }
    #retry-result-panel {
        width: 1fr;
        border-left: solid #333355;
        padding: 0 1;
    }
    #retry-result-content {
        color: #c0c0d0;
    }
    .retry-label {
        color: #cc9944;
        text-style: bold;
        margin-top: 1;
    }
    .retry-sublabel {
        color: #7a7a9a;
    }
    #retry-url-input {
        margin: 0;
    }
    #retry-method-label {
        color: #55cc55;
        text-style: bold;
        height: 1;
    }
    #retry-query-input, #retry-headers-area, #retry-body-area {
        height: 1fr;
        min-height: 4;
    }
    #retry-footer {
        dock: bottom;
        height: 3;
        align-horizontal: center;
    }
    #retry-autocomplete {
        height: auto;
        max-height: 8;
        color: #55cc55;
        background: #222240;
        border: solid #555577;
        padding: 0 1;
        display: none;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("s", "save_to_plan", "Save to Plan"),
        ("ctrl+s", "send", "Send"),
    ]

    def __init__(self, result: TestResult, test_case: TestCase | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.result = result
        self.test_case = test_case
        self._all_vars = sorted(
            [(v["name"], v.get("example", "")) for v in list_variables()],
            key=lambda v: v[0],
        )
        self._suggestions: list[tuple[str, str]] = []
        self._suggest_index: int = -1
        self._completing_prefix: str = ""

    def compose(self) -> ComposeResult:
        r = self.result
        with Vertical(id="retry-frame"):
            yield Static("RETRY REQUEST", id="retry-title")
            with Horizontal(id="retry-panels"):
                with VerticalScroll(id="retry-editor"):
                    yield Static(f"[#55cc55]{r.method}[/] [#c0c0d0]{r.endpoint}[/]", id="retry-method-label")

                    yield Label("URL", classes="retry-label")
                    yield Input(
                        value=r.request_url or "",
                        id="retry-url-input",
                    )

                    yield Label("Query Params (key=value, one per line)", classes="retry-label")
                    yield TextArea(
                        self._format_query_params(),
                        id="retry-query-input",
                        language=None,
                    )

                    yield Label("Headers (key: value, one per line)", classes="retry-label")
                    yield TextArea(
                        self._format_headers(),
                        id="retry-headers-area",
                        language=None,
                    )

                    yield Label("Body (JSON — use {{$randomInt}}, {{$guid}}, etc.)", classes="retry-label")
                    yield TextArea(
                        self._format_body(),
                        id="retry-body-area",
                        language="json",
                    )
                    yield Static("", id="retry-autocomplete")

                with VerticalScroll(id="retry-result-panel"):
                    yield Static("[#7a7a9a]Press \\[ctrl+s] to send request[/]", id="retry-result-content")

            with Horizontal(id="retry-footer"):
                yield Button("\\[esc] CLOSE", variant="default", id="retry-close-btn")
                yield Button("\\[s] SAVE TO PLAN", variant="warning", id="retry-save-btn")
                yield Button("\\[ctrl+s] SEND", variant="success", id="retry-send-btn")

    # ── Autocomplete for body TextArea ──────────────────────────────

    @on(TextArea.Changed, "#retry-body-area")
    def on_body_changed(self, event: TextArea.Changed) -> None:
        """Detect {{$ prefix and show autocomplete suggestions."""
        ta = event.text_area
        cursor = ta.cursor_location
        line_text = ta.document.get_line(cursor[0])
        col = cursor[1]

        # Find {{$ prefix before cursor
        text_before = line_text[:col]
        idx = text_before.rfind("{{$")
        if idx == -1:
            self._hide_autocomplete()
            return

        prefix = text_before[idx + 3:]  # text after {{$
        # If we already closed with }}, no autocomplete
        if "}}" in prefix:
            self._hide_autocomplete()
            return

        self._completing_prefix = prefix
        self._filter_suggestions(prefix)

    def _filter_suggestions(self, prefix: str) -> None:
        prefix_lower = prefix.lower()
        self._suggestions = [
            (name, desc) for name, desc in self._all_vars
            if prefix_lower in name.lower()
        ][:10]
        self._suggest_index = 0 if self._suggestions else -1

        ac = self.query_one("#retry-autocomplete", Static)
        if not self._suggestions:
            ac.display = False
            return

        lines = []
        for i, (name, desc) in enumerate(self._suggestions):
            marker = "[#55cc55]▸[/] " if i == self._suggest_index else "  "
            lines.append(f"{marker}[#55cc55]{name}[/] [#7a7a9a]{desc}[/]")
        ac.update("\n".join(lines))
        ac.display = True

    def _hide_autocomplete(self) -> None:
        self._suggestions = []
        self._suggest_index = -1
        self._completing_prefix = ""
        try:
            self.query_one("#retry-autocomplete", Static).display = False
        except Exception:
            pass

    def _accept_suggestion(self) -> None:
        if not self._suggestions or self._suggest_index < 0:
            return
        name, _ = self._suggestions[self._suggest_index]
        ta = self.query_one("#retry-body-area", TextArea)
        cursor = ta.cursor_location
        line_text = ta.document.get_line(cursor[0])
        col = cursor[1]

        # Find the {{$ prefix position
        text_before = line_text[:col]
        idx = text_before.rfind("{{$")
        if idx == -1:
            return

        # Check if }} already exists after cursor
        text_after = line_text[col:]
        has_closing = text_after.startswith("}}")

        replacement = "{{$" + name + "}}"
        start = (cursor[0], idx)
        # If }} already there, consume them too
        end = (cursor[0], col + 2 if has_closing else col)
        ta.replace(replacement, start, end)
        self._hide_autocomplete()

    def on_key(self, event) -> None:
        """Handle arrow keys and enter/tab for autocomplete navigation."""
        if not self._suggestions:
            return

        if event.key == "down":
            event.prevent_default()
            event.stop()
            self._suggest_index = min(self._suggest_index + 1, len(self._suggestions) - 1)
            self._update_suggest_highlight()
        elif event.key == "up":
            event.prevent_default()
            event.stop()
            self._suggest_index = max(self._suggest_index - 1, 0)
            self._update_suggest_highlight()
        elif event.key in ("enter", "tab"):
            event.prevent_default()
            event.stop()
            self._accept_suggestion()
        elif event.key == "escape":
            if self._suggestions:
                event.prevent_default()
                event.stop()
                self._hide_autocomplete()

    def _update_suggest_highlight(self) -> None:
        lines = []
        for i, (name, desc) in enumerate(self._suggestions):
            marker = "[#55cc55]▸[/] " if i == self._suggest_index else "  "
            lines.append(f"{marker}[#55cc55]{name}[/] [#7a7a9a]{desc}[/]")
        self.query_one("#retry-autocomplete", Static).update("\n".join(lines))

    # ── Field formatting ─────────────────────────────────────────────

    def _format_query_params(self) -> str:
        if self.test_case and self.test_case.query_params:
            return "\n".join(f"{k}={v}" for k, v in self.test_case.query_params.items())
        # Try to parse from URL
        url = self.result.request_url or ""
        if "?" in url:
            qs = url.split("?", 1)[1]
            return "\n".join(qs.split("&"))
        return ""

    def _format_headers(self) -> str:
        headers = self.result.request_headers or {}
        if not headers and self.test_case:
            headers = dict(self.test_case.headers)
        lines = []
        for k, v in headers.items():
            # Skip default headers
            if k.lower() in ("host", "user-agent", "accept", "accept-encoding", "connection"):
                continue
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    def _format_body(self) -> str:
        # Prefer test case body (has {{$faker}} templates) over result body (resolved)
        body = None
        if self.test_case and self.test_case.body is not None:
            body = self.test_case.body
        elif self.result.request_body is not None:
            body = self.result.request_body
        if body is None:
            return ""
        if isinstance(body, (dict, list)):
            try:
                return json.dumps(body, indent=2, default=str)
            except (TypeError, ValueError):
                return str(body)
        return str(body)

    def _parse_headers(self) -> dict[str, str]:
        text = self.query_one("#retry-headers-area", TextArea).text.strip()
        headers: dict[str, str] = {}
        for line in text.split("\n"):
            line = line.strip()
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip()] = v.strip()
        return headers

    def _parse_query_params(self) -> dict[str, str]:
        text = self.query_one("#retry-query-input", TextArea).text.strip()
        params: dict[str, str] = {}
        for line in text.split("\n"):
            line = line.strip()
            if "=" in line:
                k, _, v = line.partition("=")
                params[k.strip()] = v.strip()
        return params

    def _parse_body(self) -> Any:
        text = self.query_one("#retry-body-area", TextArea).text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @work(thread=False)
    async def action_send(self) -> None:
        """Send the edited request."""
        result_panel = self.query_one("#retry-result-content", Static)
        result_panel.update("[#cc9944]Sending request...[/]")

        import httpx
        import time
        from specs_agent.templating.variables import resolve_value

        url = self.query_one("#retry-url-input", Input).value.strip()
        headers = resolve_value(self._parse_headers())
        query_params = resolve_value(self._parse_query_params())
        body = resolve_value(self._parse_body())
        method = self.result.method

        # Inject auth from run config
        if hasattr(self.app, "run_config"):
            rc = self.app.run_config
            if rc.auth_type == "bearer" and rc.auth_value:
                headers.setdefault(rc.auth_header, f"Bearer {rc.auth_value}")
            elif rc.auth_type == "api_key" and rc.auth_value:
                headers.setdefault(rc.auth_header, rc.auth_value)

        timeout = 10.0
        if hasattr(self.app, "run_config"):
            timeout = self.app.run_config.timeout_seconds

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    params=query_params or None,
                    headers=headers or None,
                    json=body if body and isinstance(body, (dict, list)) else None,
                    content=str(body).encode() if body and not isinstance(body, (dict, list)) else None,
                )
            elapsed_ms = (time.monotonic() - start) * 1000

            try:
                resp_body = response.json()
            except Exception:
                resp_body = response.text

            result_panel.update(self._format_response(
                response.status_code, elapsed_ms,
                dict(response.headers), resp_body,
                url, method, headers, body,
            ))

        except httpx.TimeoutException:
            elapsed_ms = (time.monotonic() - start) * 1000
            result_panel.update(
                f"[#cc4444]Timeout after {elapsed_ms:.0f}ms[/]"
            )
        except Exception as exc:
            result_panel.update(
                f"[#cc4444]Error: {exc}[/]"
            )

    def _format_response(
        self,
        status_code: int,
        elapsed_ms: float,
        resp_headers: dict,
        resp_body: Any,
        url: str,
        method: str,
        req_headers: dict,
        req_body: Any,
    ) -> str:
        lines: list[str] = []

        # Status
        color = "#55cc55" if 200 <= status_code < 300 else "#cc9944" if 300 <= status_code < 400 else "#cc4444"
        lines.append(f"[{color}]{status_code}[/]  [#55aacc]{elapsed_ms:.0f}ms[/]")
        lines.append(f"[#7a7a9a]{method} {url}[/]")

        # Request sent
        lines.append(f"\n[bold #cc9944]Request Sent[/]")
        if req_headers:
            for k, v in req_headers.items():
                lines.append(f"  [#7a7a9a]{k}: {v}[/]")
        if req_body:
            lines.append(f"\n  [#7a7a9a]Body:[/]")
            body_str = _format_json(req_body, max_lines=10)
            for bl in body_str.split("\n"):
                lines.append(f"    [#55aacc]{bl}[/]")

        # Response headers
        lines.append(f"\n[bold #cc9944]Response Headers[/]")
        for k, v in list(resp_headers.items())[:10]:
            lines.append(f"  [#7a7a9a]{k}: {v}[/]")

        # Response body
        lines.append(f"\n[bold #cc9944]Response Body[/]")
        body_str = _format_json(resp_body, max_lines=30)
        for bl in body_str.split("\n"):
            lines.append(f"  [#c0c0d0]{bl}[/]")

        return "\n".join(lines)

    def action_save_to_plan(self) -> None:
        """Save the edited request values back to the test case in the plan."""
        if not self.test_case:
            self.notify("No test case found to save to", title="ERROR", severity="error")
            return

        tc = self.test_case
        tc.headers = self._parse_headers()
        tc.query_params = self._parse_query_params()
        tc.body = self._parse_body()

        # Auto-save the plan to disk
        plan = getattr(self.app, "test_plan", None)
        if plan:
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

        self.notify("Saved to test plan", title="SAVED")

    def action_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#retry-close-btn")
    def on_close_btn(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#retry-save-btn")
    def on_save_btn(self) -> None:
        self.action_save_to_plan()

    @on(Button.Pressed, "#retry-send-btn")
    def on_send_btn(self) -> None:
        self.action_send()


def _format_json(data: Any, max_lines: int = 20) -> str:
    try:
        text = json.dumps(data, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(data)
    lines = text.split("\n")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    return text
