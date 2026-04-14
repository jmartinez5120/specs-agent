"""Welcome screen -- mission briefing with starfield background."""

from __future__ import annotations

import tempfile
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Middle, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from specs_agent.config import RecentSpec
from specs_agent.screens.navigation import ArrowNavMixin
from specs_agent.widgets.starfield import Starfield


class NavInput(Input):
    """Input that lets up/down arrow keys bubble to the screen for navigation."""

    def _on_key(self, event) -> None:
        if event.key in ("up", "down"):
            # Don't consume — let the screen handle zone navigation
            return
        super()._on_key(event)

# Pixel-art </> logo + title + aliens
LOGO = """\
[#55cc55]
             ░█                ░█              ░█
           ░█                ░█  ░█              ░█
         ░█                ░█      ░█              ░█
       ░█                ░█          ░█          ░█░█
     ░█               ░█              ░█        ░█  ░█
   ░█░█             ░█                  ░█      ░█  ░█
     ░█               ░█              ░█        ░█  ░█
       ░█                ░█          ░█          ░█░█
         ░█                ░█      ░█              ░█
           ░█                ░█  ░█              ░█
             ░█                ░█              ░█
[/]
[bold #55cc55]          S  P  E  C  S     I  N  V  A  D  E  R  S[/]

[#55cc55]      👾  👾  👾  👾  👾  👾  👾  👾  👾[/]
[#55cc55]       👾  👾  👾  👾  👾  👾  👾  👾[/]
[#55cc55]        👾  👾  👾  👾  👾  👾  👾[/]

[#cc9944]              Defend your APIs from Bugs[/]"""


def _read_clipboard() -> str | None:
    """Read text from system clipboard. Returns None if unavailable."""
    # Try pyperclip first
    try:
        import pyperclip
        text = pyperclip.paste()
        return text if text and text.strip() else None
    except Exception:
        pass

    # macOS: pbpaste
    try:
        import subprocess
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception:
        pass

    # Linux: xclip
    try:
        import subprocess
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception:
        pass

    return None


def _looks_like_spec(text: str) -> bool:
    """Quick check if clipboard text looks like an OpenAPI/Swagger spec."""
    stripped = text.strip()
    # JSON spec
    if stripped.startswith("{"):
        return '"openapi"' in stripped or '"swagger"' in stripped or '"paths"' in stripped
    # YAML spec
    return (
        "openapi:" in stripped
        or "swagger:" in stripped
        or "paths:" in stripped
    )


class WelcomeScreen(ArrowNavMixin, Screen):
    """Mission briefing: load an API spec to begin."""

    FOCUS_ZONES = [
        "#spec-input",
        ["#load-button", "#paste-button"],
        "#recent-table",
    ]

    class SpecSelected(Message):
        def __init__(self, source: str) -> None:
            self.source = source
            super().__init__()

    DEFAULT_CSS = """
    WelcomeScreen {
        background: #1a1b2e;
        layers: base ui;
    }
    #starfield {
        layer: base;
        width: 1fr;
        height: 1fr;
    }
    #ui-layer {
        layer: ui;
        width: 100%;
        height: 100%;
        align: center middle;
        background: transparent;
    }
    #welcome-box {
        width: 90%;
        max-width: 120;
        height: auto;
        max-height: 85%;
        padding: 1 2;
        background: transparent;
        align-horizontal: center;
    }
    #banner {
        text-align: center;
        width: 100%;
        content-align: center middle;
    }
    #subtitle {
        text-align: center;
        width: 100%;
        color: #7a7a9a;
        margin-bottom: 2;
    }
    .prompt-label {
        color: #7a7a9a;
        margin-bottom: 0;
        text-align: center;
        width: 100%;
    }
    #spec-input {
        margin: 1 2;
        width: 1fr;
    }
    #button-row {
        align-horizontal: center;
        height: auto;
        margin: 0 2;
        width: 1fr;
    }
    #load-button {
        width: 1fr;
    }
    #paste-button {
        width: 1fr;
    }
    .section-label {
        margin-top: 2;
        margin-bottom: 0;
        color: #7a7a9a;
        text-align: center;
        width: 100%;
    }
    #recent-table {
        height: auto;
        max-height: 14;
        margin: 0 2;
        width: 1fr;
        background: transparent;
    }
    #footer-hints {
        text-align: center;
        width: 100%;
        color: #555577;
        margin-top: 2;
    }
    """

    BINDINGS = [
        ("q", "app.request_quit", "Quit"),
        ("escape", "app.request_quit", "Quit"),
        ("ctrl+v", "paste_spec", "Paste Spec"),
    ]

    def compose(self) -> ComposeResult:
        yield Starfield(id="starfield")
        with Middle(id="ui-layer"):
            with Vertical(id="welcome-box"):
                yield Static(LOGO, id="banner")
                yield Label(
                    "ENTER TARGET COORDINATES",
                    classes="prompt-label",
                )
                yield NavInput(
                    placeholder="  /path/to/openapi.yaml  or  https://...",
                    id="spec-input",
                )
                with Horizontal(id="button-row"):
                    yield Button(
                        "\\[enter] LAUNCH SCAN",
                        variant="success",
                        id="load-button",
                    )
                    yield Button(
                        "\\[ctrl+v] PASTE SPEC",
                        variant="primary",
                        id="paste-button",
                    )
                yield Label(
                    "RECENT MISSIONS",
                    classes="section-label",
                )
                yield DataTable(id="recent-table", cursor_type="row", zebra_stripes=True)
                yield Static(
                    "[ENTER] Submit    [Ctrl+V] Paste Spec    [Q] Quit",
                    id="footer-hints",
                )
        yield Footer()

    def on_mount(self) -> None:
        self._recent_sources = []
        self._load_recent_specs()
        if hasattr(self.app, "initial_spec") and self.app.initial_spec:
            self.query_one("#spec-input", Input).value = self.app.initial_spec

    def on_screen_resume(self) -> None:
        """Refresh the recent specs list when returning to this screen."""
        self._load_recent_specs()

    def on_key(self, event) -> None:
        """Arrow key navigation between zones, smart about Input focus."""
        focused = self.focused
        is_input = isinstance(focused, Input)

        if event.key == "up":
            event.prevent_default()
            event.stop()
            self.action_focus_up_zone()
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            self.action_focus_down_zone()
        elif event.key == "left" and not is_input:
            event.prevent_default()
            event.stop()
            self.action_focus_left()
        elif event.key == "right" and not is_input:
            event.prevent_default()
            event.stop()
            self.action_focus_right()

    def _load_recent_specs(self) -> None:
        table = self.query_one("#recent-table", DataTable)
        if not table.columns:
            table.add_column("API", key="name")
            table.add_column("Source", key="source")
            table.add_column("Runs", key="runs")
            table.add_column("Last Rate", key="rate")
            table.add_column("Last Run", key="time")
        else:
            table.clear()

        self._recent_sources: list[str] = []
        config = getattr(self.app, "config", None)
        if not config or not config.recent_specs:
            return

        from specs_agent.history.storage import list_runs

        for recent in config.recent_specs[:8]:
            # Get history for this spec
            runs = []
            try:
                runs = list_runs(recent.display, "", limit=1)
                if not runs:
                    # Try with source as base_url hint
                    runs = list_runs(recent.display, recent.source, limit=1)
            except Exception:
                pass

            # Get run count
            run_count = 0
            try:
                all_runs = list_runs(recent.display, "", limit=50)
                if not all_runs:
                    all_runs = list_runs(recent.display, recent.source, limit=50)
                run_count = len(all_runs)
            except Exception:
                pass

            if runs:
                last = runs[0]
                rate = last.get("pass_rate", 0)
                rate_color = "#55cc55" if rate >= 80 else "#cc9944" if rate >= 50 else "#cc4444"
                ts = last.get("timestamp", "")[:16].replace("T", " ")
                rate_str = f"[{rate_color}]{rate:.0f}%[/]"
                time_str = ts
                runs_str = str(run_count)
            else:
                rate_str = "[#7a7a9a]--[/]"
                time_str = "[#7a7a9a]never[/]"
                runs_str = "[#7a7a9a]0[/]"

            # Truncate source for display
            src = recent.source
            if len(src) > 45:
                src = src[:42] + "..."

            table.add_row(
                f"[#55cc55]{recent.display}[/]",
                f"[#555577]{src}[/]",
                runs_str,
                rate_str,
                time_str,
                key=f"spec_{len(self._recent_sources)}",
            )
            self._recent_sources.append(recent.source)

    @on(Button.Pressed, "#load-button")
    def on_load_pressed(self) -> None:
        source = self.query_one("#spec-input", Input).value.strip()
        if source:
            self.post_message(self.SpecSelected(source))

    @on(Input.Submitted, "#spec-input")
    def on_input_submitted(self) -> None:
        source = self.query_one("#spec-input", Input).value.strip()
        if source:
            self.post_message(self.SpecSelected(source))

    @on(DataTable.RowSelected, "#recent-table")
    def on_recent_selected(self, event: DataTable.RowSelected) -> None:
        row_key = str(event.row_key.value)
        if row_key.startswith("spec_"):
            idx = int(row_key.split("_")[1])
            if idx < len(self._recent_sources):
                self.post_message(self.SpecSelected(self._recent_sources[idx]))

    @on(Button.Pressed, "#paste-button")
    def on_paste_pressed(self) -> None:
        self.action_paste_spec()

    def action_paste_spec(self) -> None:
        """Read spec from clipboard, save to temp file, and load it."""
        clipboard = _read_clipboard()
        if not clipboard:
            self.notify(
                "Clipboard is empty or unreadable",
                title="PASTE FAILED",
                severity="error",
            )
            return

        if not _looks_like_spec(clipboard):
            self.notify(
                "Clipboard does not look like an OpenAPI/Swagger spec",
                title="INVALID SPEC",
                severity="error",
            )
            return

        # Determine file extension
        stripped = clipboard.strip()
        ext = ".json" if stripped.startswith("{") else ".yaml"

        # Save to temp file in ~/.specs-agent/
        specs_dir = Path.home() / ".specs-agent" / "pasted"
        specs_dir.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            dir=specs_dir, suffix=ext, prefix="pasted_", delete=False, mode="w"
        )
        tmp.write(clipboard)
        tmp.close()

        self.notify(
            f"Spec pasted to {tmp.name}",
            title="SPEC RECEIVED",
        )
        self.post_message(self.SpecSelected(tmp.name))
