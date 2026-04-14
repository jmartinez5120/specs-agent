"""Detail modal -- overlay panel with editable fields and faker autocomplete."""

from __future__ import annotations

import re

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from specs_agent.execution.functional import FunctionalExecutor
from specs_agent.models.config import TestRunConfig
from specs_agent.models.plan import TestCase
from specs_agent.templating.variables import _GENERATORS

_VAR_PATTERN = re.compile(r"\{\{.*?\}\}")
_ALL_VARS = sorted(set(_GENERATORS.keys()))

# Short descriptions per function category
_VAR_DESCRIPTIONS: dict[str, str] = {
    "guid": "UUID v4 identifier",
    "randomint": "random integer 1-1000",
    "randomfloat": "random decimal 0-100",
    "randomboolean": "true or false",
    "randomword": "single random word",
    "randomwords": "three random words",
    "randomsentence": "random sentence",
    "randomhex": "16-char hex string",
    "randomcolor": "hex color code",
    "randomname": "full person name",
    "randomfirstname": "first name",
    "randomlastname": "last name",
    "randomusername": "username",
    "randomemail": "email address",
    "randomphone": "phone number",
    "randomurl": "URL",
    "randomip": "IPv4 address",
    "randomipv6": "IPv6 address",
    "timestamp": "Unix timestamp (now)",
    "isotimestamp": "ISO 8601 datetime (now)",
    "randomdate": "random date YYYY-MM-DD",
    "randomdatetime": "random ISO datetime",
    "randomcompany": "company name",
    "randomjobtitle": "job title",
    "randomcountry": "country name",
    "randomcity": "city name",
    "randomstreet": "street address",
    "randomzip": "postal/zip code",
    "randomcreditcard": "credit card number",
    "randomcurrency": "currency code (USD, EUR...)",
}


def _strip_braces(value: str) -> str:
    """Strip {{$...}} wrapper, returning just the function name."""
    s = value.strip()
    if s.startswith("{{") and s.endswith("}}"):
        s = s[2:-2].strip().lstrip("$")
    return s


def _has_template_var(value) -> bool:
    """Check if a value has unresolved template vars (not valid faker functions)."""
    if isinstance(value, str):
        matches = _VAR_PATTERN.findall(value)
        for m in matches:
            # Strip {{ }} and $ to get the function name
            inner = m.strip().lstrip("{").rstrip("}").strip().lstrip("$").strip()
            if inner.lower() not in _GENERATORS:
                return True  # Unknown template var
        return False  # All template vars are valid faker functions
    if isinstance(value, dict):
        return any(_has_template_var(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_template_var(v) for v in value)
    return False


def _describe_field(key: str) -> str:
    k = key.lower()
    if "id" in k:
        return "expects: integer ID (e.g. 1, 2, 3) or randomInt"
    if "email" in k:
        return "expects: email address or randomEmail"
    if "name" in k and "user" in k:
        return "expects: username or randomUserName"
    if "name" in k:
        return "expects: text name or randomName"
    if "price" in k or "amount" in k:
        return "expects: number (e.g. 19.99) or randomFloat"
    if "date" in k:
        return "expects: date (YYYY-MM-DD) or randomDate"
    if "url" in k or "uri" in k:
        return "expects: URL or randomUrl"
    if "phone" in k:
        return "expects: phone number or randomPhone"
    if "quantity" in k or "count" in k or "stock" in k:
        return "expects: integer or randomInt"
    if "sku" in k or "code" in k:
        return "expects: string code or randomHex"
    if "active" in k or "enabled" in k:
        return "expects: true/false or randomBoolean"
    if "description" in k or "comment" in k or "text" in k:
        return "expects: text or randomSentence"
    if "category" in k:
        return "expects: category ID or randomInt"
    if "keyword" in k or "search" in k:
        return "expects: search term or randomWord"
    if "rating" in k or "score" in k:
        return "expects: integer (e.g. 1-5) or randomInt"
    return "expects: value or faker function (e.g. randomWord)"


def _fuzzy_match_vars(query: str) -> list[tuple[str, str, str]]:
    """Returns list of (name, example, description)."""
    q = query.lower().lstrip("$").replace("{{", "").replace("}}", "").strip()
    if not q:
        return []

    seen_fns: set[int] = set()
    results: list[tuple[str, str, str]] = []
    for name in _ALL_VARS:
        if q in name:
            fn = _GENERATORS[name]
            fn_id = id(fn)
            if fn_id in seen_fns:
                continue
            seen_fns.add(fn_id)
            example = str(fn())
            if len(example) > 30:
                example = example[:27] + "..."
            desc = _VAR_DESCRIPTIONS.get(name, "")
            results.append((name, example, desc))
    return results[:10]


class DetailModal(ModalScreen[None]):
    """Overlay panel with editable intel fields and faker autocomplete."""

    DEFAULT_CSS = """
    DetailModal {
        align: center middle;
        background: transparent;
    }
    #detail-frame {
        width: 90%;
        height: 85%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #detail-title {
        dock: top;
        width: 100%;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    #detail-scroll {
        height: 1fr;
        margin: 1 0;
    }
    .intel-label {
        color: #c0c0d0;
    }
    .intel-input {
        height: 3;
        margin: 0 0 0 2;
        background: #222240;
        color: #55cc55;
        border: tall #cc9944;
    }
    .intel-input:focus {
        border: tall #55cc55;
    }
    .intel-suggest {
        color: #55aacc;
        margin: 0 0 0 2;
        height: auto;
    }
    #try-result {
        margin-top: 1;
        padding: 1 2;
        height: auto;
    }
    #detail-footer {
        dock: bottom;
        height: 3;
        align-horizontal: center;
    }
    """

    BINDINGS = [
        ("escape", "close_or_dismiss_suggest", "Close"),
        ("t", "try_request", "Try It"),
        ("ctrl+s", "save_intel", "Save"),
    ]

    def __init__(self, test_case: TestCase, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tc = test_case
        self._edit_fields: dict[str, tuple[str, str]] = {}
        self._suggest_map: dict[str, str] = {}
        # Autocomplete state
        self._current_suggestions: list[tuple[str, str, str]] = []
        self._suggest_index: int = -1
        self._active_input_id: str | None = None
        self._mounted = False
        self._initial_values: set[str] = set()  # Track initial values to suppress suggestions

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-frame"):
            yield Static("MISSION DETAIL", id="detail-title")
            with VerticalScroll(id="detail-scroll"):
                yield Static(self._build_header())

                if self.tc.path_params:
                    has_vars = any(_has_template_var(v) for v in self.tc.path_params.values())
                    tag = "  [#ff0000]INTEL NEEDED[/]" if has_vars else ""
                    yield Static(f"[bold {'#ff0000' if has_vars else '#cc9944'}]Path Parameters[/]{tag}")
                    for k, v in self.tc.path_params.items():
                        yield from self._render_field("path_params", "path", k, v)

                if self.tc.query_params:
                    has_vars = any(_has_template_var(v) for v in self.tc.query_params.values())
                    tag = "  [#ff0000]INTEL NEEDED[/]" if has_vars else ""
                    yield Static(f"\n[bold {'#ff0000' if has_vars else '#cc9944'}]Query Parameters[/]{tag}")
                    for k, v in self.tc.query_params.items():
                        yield from self._render_field("query_params", "query", k, v)

                if self.tc.headers:
                    has_vars = any(_has_template_var(v) for v in self.tc.headers.values())
                    tag = "  [#ff0000]INTEL NEEDED[/]" if has_vars else ""
                    yield Static(f"\n[bold {'#ff0000' if has_vars else '#cc9944'}]Headers[/]{tag}")
                    for k, v in self.tc.headers.items():
                        yield from self._render_field("headers", "header", k, v)

                if self.tc.body is not None and isinstance(self.tc.body, dict):
                    has_vars = _has_template_var(self.tc.body)
                    tag = "  [#ff0000]INTEL NEEDED[/]" if has_vars else ""
                    yield Static(f"\n[bold {'#ff0000' if has_vars else '#cc9944'}]Request Body[/]{tag}")
                    for k, v in self.tc.body.items():
                        if isinstance(v, str):
                            yield from self._render_field("body", "body", k, v)
                        else:
                            color = "#55cc55" if not _has_template_var(v) else "#cc9944"
                            yield Static(f"    [#c0c0d0]{k}:[/] [{color}]{repr(v)}[/]")
                elif self.tc.body is not None:
                    yield Static(f"\n[bold #cc9944]Request Body[/]")
                    yield Static(f"    [#55aacc]{self.tc.body!r}[/]")

                yield Static(self._build_assertions())
                yield Static(self._build_status())

                # Try-it response area
                yield Static("", id="try-result")

            with Horizontal(id="detail-footer"):
                yield Button("\\[esc] CLOSE", variant="default", id="close-btn")
                yield Button("\\[t] TRY IT", variant="primary", id="try-btn")
                yield Button("\\[c] CURL", variant="warning", id="curl-btn")
                yield Button("\\[ctrl+s] SAVE", variant="success", id="save-btn")

    def _render_field(self, section: str, prefix: str, key: str, value):
        """Render a field — always editable with description and autocomplete."""
        needs = _has_template_var(value)
        desc = _describe_field(key)
        marker = "[#ff0000]▸[/]" if needs else "[#55cc55]✓[/]"
        yield Label(f"  {marker} [bold #c0c0d0]{key}[/]  [#7a7a9a]{desc}[/]", classes="intel-label")
        input_id = f"{prefix}_{key}"
        suggest_id = f"suggest_{prefix}_{key}"
        self._edit_fields[input_id] = (section, key)
        self._suggest_map[input_id] = suggest_id
        display_val = _strip_braces(str(value))
        yield Input(value=display_val, placeholder=f"Value or faker function (e.g. randomInt)", id=input_id, classes="intel-input")
        yield Static("", id=suggest_id, classes="intel-suggest")

    def on_key(self, event) -> None:
        """Handle arrow navigation in suggestions."""
        if not self._current_suggestions or self._active_input_id is None:
            if not isinstance(self.focused, Input):
                if event.character == "c":
                    event.prevent_default()
                    event.stop()
                    self.action_copy_curl()
                elif event.character == "t":
                    event.prevent_default()
                    event.stop()
                    self.action_try_request()
            return

        if event.key == "down":
            event.prevent_default()
            event.stop()
            self._suggest_index = min(self._suggest_index + 1, len(self._current_suggestions) - 1)
            self._render_suggestions()
        elif event.key == "up":
            event.prevent_default()
            event.stop()
            self._suggest_index = max(self._suggest_index - 1, -1)
            self._render_suggestions()
        elif event.key == "tab" or (event.key == "enter" and self._suggest_index >= 0):
            event.prevent_default()
            event.stop()
            self._accept_suggestion()

    def on_mount(self) -> None:
        # Record initial values so we don't show suggestions until user edits
        for input_id in self._edit_fields:
            try:
                inp = self.query_one(f"#{input_id}", Input)
                self._initial_values.add(inp.value)
            except Exception:
                pass
        self._mounted = True

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        input_id = event.input.id
        if input_id not in self._suggest_map:
            return

        # Don't show suggestions for initial values (mount-time)
        if event.value in self._initial_values:
            return
        # Once user edits, remove from initial set
        self._initial_values.discard(event.value)

        self._active_input_id = input_id
        text = event.value.strip()

        if text and not text.startswith(("http", "/", "{")) and len(text) >= 2:
            self._current_suggestions = _fuzzy_match_vars(text)
            self._suggest_index = -1
            if self._current_suggestions:
                self._render_suggestions()
            else:
                self._clear_suggestions(input_id)
        else:
            self._current_suggestions = []
            self._clear_suggestions(input_id)

    def _clear_suggestions(self, input_id: str) -> None:
        suggest_id = self._suggest_map.get(input_id)
        if suggest_id:
            try:
                self.query_one(f"#{suggest_id}", Static).update("")
            except Exception:
                pass

    def _render_suggestions(self) -> None:
        if not self._active_input_id:
            return
        suggest_id = self._suggest_map.get(self._active_input_id)
        if not suggest_id:
            return

        lines = []
        for i, (name, example, desc) in enumerate(self._current_suggestions):
            if i == self._suggest_index:
                lines.append(f"    [bold #55cc55]▸ {name}[/]  [#c0c0d0]{desc}[/]  [#7a7a9a]→ {example}[/]")
            else:
                lines.append(f"      [#55aacc]{name}[/]  [#555577]{desc}[/]  [#7a7a9a]→ {example}[/]")

        try:
            self.query_one(f"#{suggest_id}", Static).update("\n".join(lines))
        except Exception:
            pass

    def _accept_suggestion(self) -> None:
        if self._suggest_index < 0 or self._suggest_index >= len(self._current_suggestions):
            return
        if not self._active_input_id:
            return

        name = self._current_suggestions[self._suggest_index][0]

        # Add to initial_values so the changed event ignores the new value
        self._initial_values.add(name)

        # Clear suggestions first
        self._current_suggestions = []
        self._suggest_index = -1
        suggest_id = self._suggest_map.get(self._active_input_id)
        if suggest_id:
            try:
                self.query_one(f"#{suggest_id}", Static).update("")
            except Exception:
                pass

        # Set value (this triggers on_input_changed, but initial_values blocks suggestions)
        try:
            inp = self.query_one(f"#{self._active_input_id}", Input)
            inp.value = name
        except Exception:
            pass

        self._active_input_id = None

    def _build_header(self) -> str:
        tc = self.tc
        armed = "[#55cc55]ARMED[/]" if tc.enabled else "[#7a7a9a]DISARMED[/]"
        lines = [
            f"  [bold #55cc55]{tc.method}[/] [#c0c0d0]{tc.endpoint_path}[/]  {armed}",
            f"  [#7a7a9a]{tc.name}[/]",
        ]
        if tc.description:
            lines.append(f"  [#7a7a9a]{tc.description}[/]")

        # Recalculate actual needs_input from current values
        actually_needs = (
            _has_template_var(tc.path_params)
            or _has_template_var(tc.query_params)
            or _has_template_var(tc.headers)
            or _has_template_var(tc.body)
        )
        if actually_needs:
            # Build a specific list of what's missing, with section labels for duplicates
            missing: list[str] = []
            for k, v in tc.path_params.items():
                if _has_template_var(v):
                    desc = _describe_field(k).split(":", 1)[1].strip() if ":" in _describe_field(k) else ""
                    missing.append(f"[#c0c0d0]{k}[/] [#7a7a9a](path — {desc})[/]")
            for k, v in tc.query_params.items():
                if _has_template_var(v):
                    desc = _describe_field(k).split(":", 1)[1].strip() if ":" in _describe_field(k) else ""
                    missing.append(f"[#c0c0d0]{k}[/] [#7a7a9a](query — {desc})[/]")
            for k, v in tc.headers.items():
                if _has_template_var(v):
                    missing.append(f"[#c0c0d0]{k}[/] [#7a7a9a](header)[/]")
            if isinstance(tc.body, dict):
                for k, v in tc.body.items():
                    if isinstance(v, str) and _has_template_var(v):
                        desc = _describe_field(k).split(":", 1)[1].strip() if ":" in _describe_field(k) else ""
                        missing.append(f"[#c0c0d0]{k}[/] [#7a7a9a](body — {desc})[/]")

            lines.append(f"\n  [bold #ff0000]⚠ INTEL NEEDED — {len(missing)} field(s) require values:[/]")
            for m in missing:
                lines.append(f"    [#ff0000]•[/] {m}")
            lines.append(f"\n  [#7a7a9a]Enter a real value or type a faker function name (e.g. randomInt)[/]")
        return "\n".join(lines)

    def _build_assertions(self) -> str:
        lines: list[str] = []
        if self.tc.assertions:
            lines.append(f"\n  [bold #cc9944]Assertions ({len(self.tc.assertions)})[/]")
            for a in self.tc.assertions:
                expected = a.expected
                if isinstance(expected, dict):
                    st = expected.get("type", "object")
                    props = expected.get("properties", {})
                    if props:
                        expected = f"{st} {{ {', '.join(list(props.keys())[:5])} }}"
                    else:
                        expected = st
                lines.append(f"    [#55aacc]{a.type.value}[/] = [#c0c0d0]{expected}[/]")
                if a.description:
                    lines.append(f"      [#7a7a9a]{a.description}[/]")
        return "\n".join(lines)

    def _build_status(self) -> str:
        tc = self.tc
        actually_needs = (
            _has_template_var(tc.path_params)
            or _has_template_var(tc.query_params)
            or _has_template_var(tc.headers)
            or _has_template_var(tc.body)
        )
        lines = [f"\n  [bold #cc9944]Status[/]"]
        lines.append(f"    [#c0c0d0]ID:[/] [#7a7a9a]{tc.id}[/]")
        if actually_needs:
            lines.append(f"    [#c0c0d0]Needs intel:[/] [#ff0000]Yes — edit fields above and save[/]")
        else:
            lines.append(f"    [#c0c0d0]Needs intel:[/] [#55cc55]Ready — all values will auto-resolve[/]")
        return "\n".join(lines)

    def action_save_intel(self) -> None:
        # Validate before saving
        errors: list[str] = []
        warnings: list[str] = []
        resolved: list[str] = []

        for input_id, (section, key) in self._edit_fields.items():
            try:
                inp = self.query_one(f"#{input_id}", Input)
            except Exception:
                continue
            raw_val = inp.value.strip()

            if not raw_val:
                errors.append(f"{key} ({section}) — empty, needs a value")
                continue

            # Check if it's a known faker function
            clean = raw_val.lstrip("$")
            if clean in _GENERATORS:
                resolved.append(f"{key} → {clean}")
                continue

            # Check if it still has unresolved template vars
            if _has_template_var(raw_val):
                # It's a {{$something}} that might not be a valid function
                inner = _strip_braces(raw_val)
                if inner not in _GENERATORS:
                    warnings.append(f"{key} ({section}) — unknown function '{inner}'")
                else:
                    resolved.append(f"{key} → {inner}")
                continue

            # It's a literal value — valid
            resolved.append(f"{key} = {raw_val}")

        if errors:
            msg = "\n".join(f"  • {e}" for e in errors)
            self.notify(
                f"{len(errors)} field(s) still empty:\n{msg}",
                title="VALIDATION FAILED",
                severity="error",
            )
            return

        if warnings:
            msg = "\n".join(f"  • {w}" for w in warnings)
            self.notify(
                f"{len(warnings)} warning(s):\n{msg}",
                title="WARNINGS",
                severity="warning",
            )

        # All valid — apply
        self._apply_edits()

        self.tc.needs_input = (
            _has_template_var(self.tc.path_params)
            or _has_template_var(self.tc.query_params)
            or _has_template_var(self.tc.headers)
            or _has_template_var(self.tc.body)
        )

        status = "ready" if not self.tc.needs_input else "some fields still use templates"
        count = len(resolved)

        # Auto-save plan to disk so edits persist across sessions
        self._auto_save_plan()

        self.notify(
            f"{count} field(s) saved — {status}",
            title="INTEL SAVED",
        )
        self.dismiss(None)

    def _auto_save_plan(self) -> None:
        """Persist the plan to ~/.specs-agent/plans/ so edits survive restarts."""
        try:
            from pathlib import Path
            from specs_agent.persistence import save_plan
            plan = getattr(self.app, "test_plan", None)
            if not plan:
                return
            save_dir = Path.home() / ".specs-agent" / "plans"
            safe_name = plan.name.replace(" ", "_").lower()[:40]
            path = str(save_dir / f"{safe_name}.yaml")
            save_plan(plan, path)
        except Exception:
            pass  # Don't block on save failure

    def _apply_edits(self) -> None:
        """Write current Input values back to the test case without dismissing."""
        for input_id, (section, key) in self._edit_fields.items():
            try:
                inp = self.query_one(f"#{input_id}", Input)
            except Exception:
                continue
            raw_val = inp.value.strip()
            if not raw_val:
                continue
            if raw_val.lower() in _GENERATORS or raw_val.lstrip("$").lower() in _GENERATORS:
                clean = raw_val.lstrip("$")
                raw_val = f"{{{{${clean}}}}}"
            if section == "path_params":
                self.tc.path_params[key] = raw_val
            elif section == "query_params":
                self.tc.query_params[key] = raw_val
            elif section == "headers":
                self.tc.headers[key] = raw_val
            elif section == "body" and isinstance(self.tc.body, dict):
                self.tc.body[key] = raw_val

    def action_try_request(self) -> None:
        """Open the retry editor modal to edit and send the request."""
        self._apply_edits()

        # Build a stub TestResult from the test case to populate the editor
        from specs_agent.models.results import TestResult, TestStatus
        from specs_agent.templating.variables import resolve_value

        base_url = "http://localhost"
        if hasattr(self.app, "test_plan") and self.app.test_plan:
            base_url = self.app.test_plan.base_url
        if hasattr(self.app, "run_config") and self.app.run_config.base_url:
            base_url = self.app.run_config.base_url

        # Resolve template variables for the URL
        path = self.tc.endpoint_path
        path_params = resolve_value(dict(self.tc.path_params))
        for k, v in path_params.items():
            path = path.replace(f"{{{k}}}", str(v))
        url = f"{base_url.rstrip('/')}{path}"

        stub_result = TestResult(
            test_case_id=self.tc.id,
            test_case_name=self.tc.name,
            endpoint=f"{self.tc.method} {self.tc.endpoint_path}",
            method=self.tc.method,
            status=TestStatus.SKIPPED,
            request_url=url,
            request_headers=dict(self.tc.headers),
            request_body=self.tc.body,
            test_type=self.tc.test_type,
        )

        from specs_agent.screens.retry_editor_modal import RetryEditorModal
        self.app.push_screen(
            RetryEditorModal(stub_result, test_case=self.tc),
            callback=self._on_retry_editor_closed,
        )

    def _on_retry_editor_closed(self, _result) -> None:
        """Refresh Input fields from the (possibly updated) test case."""
        for input_id, (section, key) in self._edit_fields.items():
            try:
                inp = self.query_one(f"#{input_id}", Input)
            except Exception:
                continue
            if section == "path_params":
                val = self.tc.path_params.get(key, "")
            elif section == "query_params":
                val = self.tc.query_params.get(key, "")
            elif section == "headers":
                val = self.tc.headers.get(key, "")
            elif section == "body" and isinstance(self.tc.body, dict):
                val = self.tc.body.get(key, "")
            else:
                continue
            inp.value = _strip_braces(str(val))

    def action_copy_curl(self) -> None:
        from specs_agent.curl_builder import build_curl
        self._apply_edits()
        base_url = "http://localhost"
        auth_type = "none"
        auth_value = ""
        if hasattr(self.app, "test_plan") and self.app.test_plan:
            base_url = self.app.test_plan.base_url
            auth_type = self.app.test_plan.auth_type
            auth_value = self.app.test_plan.auth_value
        curl = build_curl(self.tc, base_url, auth_type, auth_value)
        try:
            import subprocess
            process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            process.communicate(curl.encode())
            self.notify("cURL copied to clipboard", title="COPIED")
        except Exception:
            self.notify(curl[:200], title="cURL")

    def action_close_or_dismiss_suggest(self) -> None:
        if self._current_suggestions:
            self._current_suggestions = []
            self._suggest_index = -1
            if self._active_input_id:
                suggest_id = self._suggest_map.get(self._active_input_id)
                if suggest_id:
                    try:
                        self.query_one(f"#{suggest_id}", Static).update("")
                    except Exception:
                        pass
        else:
            self.dismiss(None)

    @on(Button.Pressed, "#close-btn")
    def on_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#try-btn")
    def on_try(self) -> None:
        self.action_try_request()

    @on(Button.Pressed, "#curl-btn")
    def on_curl(self) -> None:
        self.action_copy_curl()

    @on(Button.Pressed, "#save-btn")
    def on_save(self) -> None:
        self.action_save_intel()
