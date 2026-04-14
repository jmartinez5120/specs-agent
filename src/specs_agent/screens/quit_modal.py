"""Quit confirmation modal."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class QuitModal(ModalScreen[bool]):
    """Confirmation dialog before quitting the app."""

    DEFAULT_CSS = """
    QuitModal {
        align: center middle;
        background: transparent;
    }
    #quit-frame {
        width: 50;
        height: auto;
        border: dashed #555577;
        background: #1a1b2e;
        padding: 2 4;
    }
    #quit-title {
        text-align: center;
        color: #cc9944;
        text-style: bold;
        margin-bottom: 1;
    }
    #quit-msg {
        text-align: center;
        color: #c0c0d0;
        margin-bottom: 2;
    }
    #quit-buttons {
        align-horizontal: center;
        height: 3;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="quit-frame"):
            yield Static("ABORT MISSION?", id="quit-title")
            yield Static("Are you sure you want to quit?", id="quit-msg")
            with Horizontal(id="quit-buttons"):
                yield Button("\\[esc] CANCEL", variant="default", id="cancel-btn")
                yield Button("\\[enter] QUIT", variant="error", id="quit-btn")

    def on_mount(self) -> None:
        self.query_one("#quit-btn", Button).focus()

    @on(Button.Pressed, "#quit-btn")
    def on_quit(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_btn(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)
