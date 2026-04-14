"""Starfield background widget -- scattered stars on dark space."""

from __future__ import annotations

import random

from textual.widget import Widget


STAR_CHARS = ["+", "*", ".", "+", ".", ".", "."]
STAR_STYLES = ["#666688", "#8888aa", "#555577", "#7777aa", "#444466", "#9999bb", "#555566"]


class Starfield(Widget):
    """A background widget that renders scattered stars using Rich markup."""

    DEFAULT_CSS = """
    Starfield {
        width: 1fr;
        height: 1fr;
        background: #1a1b2e;
        overflow: hidden;
    }
    """

    def __init__(self, seed: int = 42, density: float = 0.008, **kwargs) -> None:
        super().__init__(**kwargs)
        self._seed = seed
        self._density = density

    def render(self) -> str:
        rng = random.Random(self._seed)
        w = max(self.size.width, 1)
        h = max(self.size.height, 1)
        lines: list[str] = []
        for _y in range(h):
            row = list(" " * w)
            for x in range(w):
                if rng.random() < self._density:
                    char = rng.choice(STAR_CHARS)
                    color = rng.choice(STAR_STYLES)
                    row[x] = f"[{color}]{char}[/]"
            lines.append("".join(row))
        return "\n".join(lines)
