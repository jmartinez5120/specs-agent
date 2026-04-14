"""Arrow-key navigation mixin for screens.

Screens define focusable zones as a list of widget IDs or types.
Left/right arrows move between zones horizontally.
Up/down arrows move between zones vertically when at widget boundaries.
"""

from __future__ import annotations

from textual.screen import Screen
from textual.widget import Widget


class ArrowNavMixin:
    """Mixin that adds arrow-key navigation between focusable zones.

    Subclasses set `FOCUS_ZONES` as a list of lists (rows of zone selectors):
        FOCUS_ZONES = [
            ["#tree-panel", "#detail-panel"],   # row 0: left/right
            ["#back-btn", "#generate-plan-btn"], # row 1: left/right
        ]

    Or a flat list for simple vertical navigation:
        FOCUS_ZONES = ["#spec-input", "#load-button", "#recent-list"]
    """

    FOCUS_ZONES: list = []

    def _get_zone_grid(self) -> list[list[str]]:
        """Normalize FOCUS_ZONES into a 2D grid."""
        if not self.FOCUS_ZONES:
            return []
        if isinstance(self.FOCUS_ZONES[0], list):
            return self.FOCUS_ZONES
        # Flat list → single column
        return [[z] for z in self.FOCUS_ZONES]

    def _find_current_zone(self) -> tuple[int, int] | None:
        """Find the grid position of the currently focused widget."""
        focused = self.focused  # type: ignore[attr-defined]
        if focused is None:
            return None

        grid = self._get_zone_grid()
        for row_idx, row in enumerate(grid):
            for col_idx, selector in enumerate(row):
                try:
                    widget = self.query_one(selector)  # type: ignore[attr-defined]
                    if widget is focused or focused.is_descendant_of(widget):  # type: ignore[union-attr]
                        return (row_idx, col_idx)
                except Exception:
                    continue
        return None

    def _focus_zone(self, row: int, col: int) -> bool:
        """Focus the widget at grid[row][col]. Returns True if successful."""
        grid = self._get_zone_grid()
        if not grid:
            return False
        row = max(0, min(row, len(grid) - 1))
        zone_row = grid[row]
        col = max(0, min(col, len(zone_row) - 1))

        try:
            widget = self.query_one(zone_row[col])  # type: ignore[attr-defined]
            if hasattr(widget, 'focus'):
                widget.focus()
                return True
        except Exception:
            pass
        return False

    def action_focus_left(self) -> None:
        pos = self._find_current_zone()
        if pos:
            row, col = pos
            if col > 0:
                self._focus_zone(row, col - 1)

    def action_focus_right(self) -> None:
        pos = self._find_current_zone()
        if pos:
            row, col = pos
            grid = self._get_zone_grid()
            if col < len(grid[row]) - 1:
                self._focus_zone(row, col + 1)

    def action_focus_up_zone(self) -> None:
        pos = self._find_current_zone()
        if pos:
            row, col = pos
            if row > 0:
                self._focus_zone(row - 1, col)

    def action_focus_down_zone(self) -> None:
        pos = self._find_current_zone()
        if pos:
            row, col = pos
            grid = self._get_zone_grid()
            if row < len(grid) - 1:
                self._focus_zone(row + 1, col)
