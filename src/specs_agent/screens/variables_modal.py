"""Variables reference modal -- overlay panel showing all {{$var}} templates."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from specs_agent.templating.variables import list_variables


class VariablesModal(ModalScreen[None]):
    """Overlay panel showing all available template variables."""

    DEFAULT_CSS = """
    VariablesModal {
        align: center middle;
        background: transparent;
    }
    #vars-frame {
        width: 90%;
        height: 85%;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 1 2;
    }
    #vars-title {
        dock: top;
        width: 100%;
        text-align: center;
        color: #7a7a9a;
        text-style: bold;
        height: 1;
    }
    #vars-intro {
        color: #7a7a9a;
        margin: 1 0;
    }
    #vars-scroll {
        height: 1fr;
    }
    #vars-footer {
        dock: bottom;
        width: 100%;
        text-align: center;
        color: #555577;
        height: 1;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("v", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="vars-frame"):
            yield Static(
                "TEMPLATE VARIABLES",
                id="vars-title",
            )
            yield Static(
                "  Use in path params, query params, headers, and body.\n"
                "  Variables are resolved at runtime with random data.",
                id="vars-intro",
            )
            with VerticalScroll(id="vars-scroll"):
                yield Static(self._build_reference(), id="vars-text")
            yield Static(
                "[V] Close    [ESC] Close",
                id="vars-footer",
            )

    def _build_reference(self) -> str:
        variables = list_variables()
        lines: list[str] = []
        for var in variables:
            lines.append(
                f"    [#55cc55]{{{{${var['name']}}}}}[/]"
                f"  [#555577]→[/]  [#c0c0d0]{var['example']}[/]"
            )
        return "\n".join(lines)

    def action_close(self) -> None:
        self.dismiss(None)
