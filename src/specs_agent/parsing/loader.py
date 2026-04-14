"""Load and validate OpenAPI/Swagger specs from files or URLs."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import prance
import yaml

log = logging.getLogger(__name__)


class SpecLoadError(Exception):
    """Raised when a spec cannot be loaded or validated."""


class SpecLoadWarning:
    """Holds warnings from spec loading (e.g. unresolved refs)."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def add(self, msg: str) -> None:
        self.warnings.append(msg)
        log.warning(msg)


# Module-level warnings from the last load
last_warnings = SpecLoadWarning()


def load_spec(source: str) -> dict:
    """Load and resolve an OpenAPI spec from a file path or URL.

    Tries prance.ResolvingParser first for full $ref resolution.
    Falls back to basic parsing (no resolution) if $ref targets are missing,
    so specs with broken/incomplete references still load.

    Args:
        source: File path or URL to the OpenAPI spec.

    Returns:
        Spec as a dict (resolved if possible, raw otherwise).

    Raises:
        SpecLoadError: If the spec cannot be loaded at all.
    """
    global last_warnings
    last_warnings = SpecLoadWarning()

    if source.startswith(("http://", "https://")):
        return _load_url(source)
    return _load_file(source)


def _load_file(source: str) -> dict:
    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise SpecLoadError(f"File not found: {path}")

    # Try full resolution first
    try:
        parser = prance.ResolvingParser(
            str(path), backend="openapi-spec-validator"
        )
        return parser.specification
    except Exception as resolve_err:
        last_warnings.add(
            f"Full $ref resolution failed: {resolve_err}. Loading without resolution."
        )

    # Fall back: parse without resolving — still validates structure
    try:
        parser = prance.BaseParser(str(path), backend="openapi-spec-validator")
        return parser.specification
    except Exception as base_err:
        last_warnings.add(
            f"Validation failed: {base_err}. Loading as raw YAML/JSON."
        )

    # Final fallback: raw load with no validation
    try:
        return _load_raw(path)
    except Exception as exc:
        raise SpecLoadError(f"Failed to load spec from {source}: {exc}") from exc


def _clear_prance_cache() -> None:
    """Clear prance's internal URL fetch cache to force fresh loads."""
    try:
        from prance.util.url import fetch_url, fetch_url_text
        # These use mutable default args as cache — clear them
        fetch_url.__defaults__[0].clear()  # type: ignore[union-attr]
        fetch_url_text.__defaults__[0].clear()  # type: ignore[union-attr]
    except Exception:
        pass


def _load_url(source: str) -> dict:
    _clear_prance_cache()
    try:
        parser = prance.ResolvingParser(source, backend="openapi-spec-validator")
        return parser.specification
    except Exception as resolve_err:
        last_warnings.add(
            f"Full $ref resolution failed: {resolve_err}. Trying without resolution."
        )

    try:
        parser = prance.BaseParser(source, backend="openapi-spec-validator")
        return parser.specification
    except Exception as exc:
        raise SpecLoadError(f"Failed to load spec from {source}: {exc}") from exc


def _load_raw(path: Path) -> dict:
    """Load a spec file as raw YAML/JSON with no validation."""
    text = path.read_text()
    if path.suffix in (".json",):
        return json.loads(text)
    return yaml.safe_load(text)


def load_spec_raw(source: str) -> dict:
    """Load a spec without $ref resolution — for quick inspection.

    Args:
        source: File path to the spec.

    Returns:
        Raw spec dict.
    """
    path = Path(source).expanduser().resolve()
    return _load_raw(path)
