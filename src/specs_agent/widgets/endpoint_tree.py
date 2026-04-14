"""Tree widget for browsing API endpoints -- sector radar."""

from __future__ import annotations

from textual.widgets import Tree

from specs_agent.models.spec import Endpoint, ParsedSpec

METHOD_ICONS = {
    "GET": "[#55cc55]GET[/]",
    "POST": "[#cc9944]POST[/]",
    "PUT": "[#5599dd]PUT[/]",
    "PATCH": "[#55aacc]PATCH[/]",
    "DELETE": "[#cc4444]DEL[/]",
    "OPTIONS": "[#9977cc]OPT[/]",
    "HEAD": "[#7a7a9a]HEAD[/]",
}


class EndpointTree(Tree[Endpoint | None]):
    """Displays API endpoints grouped by tag."""

    DEFAULT_CSS = """
    EndpointTree {
        width: 1fr;
        height: 1fr;
        padding: 1;
        background: #1a1b2e;
        color: #c0c0d0;
        border: solid #333355;
    }
    """

    def __init__(self, label: str = "RADAR", **kwargs) -> None:
        super().__init__(label, data=None, **kwargs)

    def load_spec(self, spec: ParsedSpec) -> None:
        self.clear()
        self.root.label = f"[bold #55cc55]{spec.title}[/] [#7a7a9a]v{spec.version}[/]"

        by_tag = spec.endpoints_by_tag
        for tag, endpoints in sorted(by_tag.items()):
            tag_node = self.root.add(
                f"[bold #cc9944]{tag}[/] [#7a7a9a]({len(endpoints)})[/]",
                data=None,
            )
            for ep in endpoints:
                icon = METHOD_ICONS.get(ep.method.value, ep.method.value)
                label = f"{icon}  [#c0c0d0]{ep.path}[/]"
                tag_node.add_leaf(label, data=ep)

        self.root.expand_all()
