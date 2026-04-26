"""Content-addressed disk cache for AI-generated values.

Keys are SHA-256 hashes of (schema + endpoint context). Values are JSON
files stored in a two-level directory structure to avoid flat-dir perf
issues on filesystems with slow readdir on large directories.

Layout:
    {cache_dir}/ab/ab3f7c9d...a1.json

Each entry stores:
    {
        "value": <generated value>,
        "schema_hash": <hex digest of just the schema>,
        "model": <model filename that produced this>,
        "created_at": <ISO timestamp>
    }

Invalidation is automatic: schema changes produce a different hash → miss.
Manual clear via `clear_all()` or the API `POST /ai/cache/clear`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AICache:
    """Disk-backed content-addressed cache for LLM-generated test values."""

    def __init__(self, cache_dir: str | Path = "~/.specs-agent/ai-cache") -> None:
        self.root = Path(cache_dir).expanduser()

    # ------------------------------------------------------------------ #
    # Key generation
    # ------------------------------------------------------------------ #

    @staticmethod
    def cache_key(
        fields: list[dict[str, Any]],
        endpoint_method: str,
        endpoint_path: str,
    ) -> str:
        """Build a stable hash key for a batch of fields + endpoint identity.

        The key covers the structural identity of the request (field names,
        schemas, endpoint method/path) but not informational fields like
        endpoint description — those affect prompt quality but not cache
        identity.
        """
        canonical = json.dumps(
            {
                "endpoint": {"method": endpoint_method, "path": endpoint_path},
                "fields": fields,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def schema_hash(schema: dict) -> str:
        """Hash just the raw schema dict — used inside entries for diagnostics."""
        return hashlib.sha256(
            json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    def _entry_path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached entry dict, or None on miss."""
        path = self._entry_path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def get_value(self, key: str) -> Any:
        """Convenience: return just the `value` field, or None on miss."""
        entry = self.get(key)
        if entry is None:
            return None
        return entry.get("value")

    def put(
        self,
        key: str,
        value: Any,
        *,
        schema_hash: str = "",
        model: str = "",
    ) -> Path:
        """Store a value under the given key. Returns the file path."""
        path = self._entry_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "value": value,
            "schema_hash": schema_hash,
            "model": model,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(entry, indent=2, default=str))
        return path

    def invalidate(self, key: str) -> bool:
        """Delete a single entry. Returns True if it existed."""
        path = self._entry_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def clear_all(self) -> int:
        """Delete every cached entry. Returns the number of entries removed."""
        if not self.root.exists():
            return 0
        count = 0
        for p in self.root.rglob("*.json"):
            p.unlink(missing_ok=True)
            count += 1
        # Clean up empty subdirectories
        for d in sorted(self.root.iterdir(), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        return count

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        if not self.root.exists():
            return {"entries": 0, "size_bytes": 0, "cache_dir": str(self.root)}
        entries = list(self.root.rglob("*.json"))
        total_bytes = sum(p.stat().st_size for p in entries)
        return {
            "entries": len(entries),
            "size_bytes": total_bytes,
            "cache_dir": str(self.root),
        }
