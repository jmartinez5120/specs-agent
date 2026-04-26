"""Storage abstraction for the engine.

The `Storage` protocol defines the contract for persisting specs, plans,
configs, and run history. `FileStorage` wraps the existing file-based
persistence at `~/.specs-agent/`. A future `MongoStorage` will implement
the same protocol for dockerized deployments.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from specs_agent.config import AppConfig, load_config, save_config
from specs_agent.history.storage import list_runs, load_run, save_run
from specs_agent.models.plan import TestPlan
from specs_agent.models.results import Report
from specs_agent.persistence import load_plan, save_plan


class Storage(Protocol):
    """Contract for persisting engine state.

    Implementations: `FileStorage` (default, uses `~/.specs-agent/`),
    `MongoStorage` (dockerized, planned for MVP 8).
    """

    # --- Config ---
    def load_config(self) -> AppConfig: ...
    def save_config(self, config: AppConfig) -> None: ...

    # --- Plans ---
    def save_plan(self, plan: TestPlan) -> str:
        """Save a plan and return its storage identifier (path / id)."""
        ...

    def load_plan_for_spec(self, spec_title: str) -> TestPlan | None:
        """Load the saved plan for a spec title, if any."""
        ...

    def archive_plan(self, plan: TestPlan) -> str:
        """Archive a plan before it's overwritten. Returns archive identifier."""
        ...

    # --- Specs ---
    def save_spec(self, title: str, source: str, source_type: str, raw_spec: dict) -> str:
        """Save a parsed spec for later retrieval. Returns storage identifier."""
        ...

    def list_specs(self, limit: int = 20) -> list[dict]:
        """List saved specs (newest first). Returns metadata dicts."""
        ...

    def load_spec(self, spec_id: str) -> dict | None:
        """Load a saved spec by its ID/title. Returns the full spec dict or None."""
        ...

    def delete_spec(self, spec_id: str) -> bool:
        """Delete a saved spec. Returns True if it existed."""
        ...

    # --- History ---
    def save_run(self, report: Report) -> str: ...
    def list_runs(self, spec_title: str, base_url: str, limit: int = 20) -> list[dict]: ...
    def load_run(self, spec_title: str, base_url: str, filename: str) -> Report | None: ...


class FileStorage:
    """File-based storage using `~/.specs-agent/`.

    This wraps the existing persistence modules (config.py, persistence.py,
    history/storage.py) without changing their on-disk format. Everything
    the TUI currently reads/writes lands here unchanged.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (Path.home() / ".specs-agent")

    # --- Config ---

    def load_config(self) -> AppConfig:
        return load_config()

    def save_config(self, config: AppConfig) -> None:
        save_config(config)

    # --- Specs ---

    @property
    def _specs_dir(self) -> Path:
        return self.root / "specs"

    def save_spec(self, title: str, source: str, source_type: str, raw_spec: dict) -> str:
        self._specs_dir.mkdir(parents=True, exist_ok=True)
        safe_name = title.replace(" ", "_").lower()[:40]
        path = self._specs_dir / f"{safe_name}.json"
        data = {
            "title": title,
            "source": source,
            "source_type": source_type,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "raw_spec": raw_spec,
        }
        path.write_text(json.dumps(data, indent=2, default=str))
        return str(path)

    def list_specs(self, limit: int = 20) -> list[dict]:
        if not self._specs_dir.exists():
            return []
        specs = []
        for p in sorted(self._specs_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                data = json.loads(p.read_text())
                specs.append({
                    "id": p.stem,
                    "title": data.get("title", p.stem),
                    "source": data.get("source", ""),
                    "source_type": data.get("source_type", ""),
                    "saved_at": data.get("saved_at", ""),
                })
            except Exception:
                continue
            if len(specs) >= limit:
                break
        return specs

    def load_spec(self, spec_id: str) -> dict | None:
        path = self._specs_dir / f"{spec_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def delete_spec(self, spec_id: str) -> bool:
        path = self._specs_dir / f"{spec_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- Plans ---

    @property
    def _plans_dir(self) -> Path:
        return self.root / "plans"

    def _plan_path(self, plan_name: str) -> Path:
        safe_name = plan_name.replace(" ", "_").lower()[:40]
        return self._plans_dir / f"{safe_name}.yaml"

    def save_plan(self, plan: TestPlan) -> str:
        self._plans_dir.mkdir(parents=True, exist_ok=True)
        path = self._plan_path(plan.name)
        return save_plan(plan, str(path))

    def load_plan_for_spec(self, spec_title: str) -> TestPlan | None:
        plan_name = f"{spec_title} Test Plan"
        path = self._plan_path(plan_name)
        if not path.exists():
            return None
        try:
            return load_plan(str(path))
        except Exception:
            return None

    def archive_plan(self, plan: TestPlan) -> str:
        archive_dir = self._plans_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        safe_name = plan.name.replace(" ", "_").lower()[:40]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = archive_dir / f"{safe_name}_{timestamp}.yaml"
        try:
            return save_plan(plan, str(path))
        except Exception:
            return ""

    # --- History ---

    def save_run(self, report: Report) -> str:
        return save_run(report)

    def list_runs(self, spec_title: str, base_url: str, limit: int = 20) -> list[dict]:
        return list_runs(spec_title, base_url, limit)

    def load_run(self, spec_title: str, base_url: str, filename: str) -> Report | None:
        return load_run(spec_title, base_url, filename)
