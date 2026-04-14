"""Colored HTTP method badge widget."""

from __future__ import annotations

from textual.widget import Widget
from textual.reactive import reactive


class MethodBadge(Widget):
    """Displays an HTTP method as a colored badge."""

    DEFAULT_CSS = """
    MethodBadge {
        width: auto;
        height: 1;
        min-width: 8;
        padding: 0 1;
    }
    MethodBadge.method-get { color: #55cc55; }
    MethodBadge.method-post { color: #cc9944; }
    MethodBadge.method-put { color: #5599dd; }
    MethodBadge.method-patch { color: #55aacc; }
    MethodBadge.method-delete { color: #cc4444; }
    MethodBadge.method-options { color: #9977cc; }
    MethodBadge.method-head { color: #7a7a9a; }
    """

    method: reactive[str] = reactive("GET")

    def __init__(self, method: str = "GET", **kwargs) -> None:
        super().__init__(**kwargs)
        self.method = method.upper()

    def render(self) -> str:
        return f"[bold]{self.method:<7}[/bold]"

    def watch_method(self, old: str, new: str) -> None:
        self.remove_class(f"method-{old.lower()}")
        self.add_class(f"method-{new.lower()}")

    def on_mount(self) -> None:
        self.add_class(f"method-{self.method.lower()}")
