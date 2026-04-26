"""Gemma 4 model presets and path resolution.

Presets map a size name ("small" / "medium") to a HuggingFace repo and
a specific GGUF filename. `resolve_model_path()` checks env vars and
config to find the actual .gguf file on disk.

Users can also set a custom absolute path as the model_size, bypassing
presets entirely (e.g., for fine-tuned models or non-Gemma GGUFs).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelPreset:
    """A known model configuration."""
    name: str
    hf_repo: str
    filename: str
    description: str
    size_gb: float
    ram_needed_gb: int


# ------------------------------------------------------------------ #
# Preset registry
# ------------------------------------------------------------------ #

PRESETS: dict[str, ModelPreset] = {
    "small": ModelPreset(
        name="small",
        hf_repo="unsloth/gemma-4-E4B-it-GGUF",
        filename="gemma-4-E4B-it-Q4_K_M.gguf",
        description="Gemma 4 E4B-it (Q4_K_M) — fast, runs on 8GB RAM",
        size_gb=3.0,
        ram_needed_gb=8,
    ),
    "medium": ModelPreset(
        name="medium",
        hf_repo="unsloth/gemma-4-26B-A4B-it-GGUF",
        filename="gemma-4-26B-A4B-it-UD-Q4_K_M.gguf",
        description="Gemma 4 26B-A4B-it (Q4_K_M) — better quality, needs 16GB+ RAM",
        size_gb=10.0,
        ram_needed_gb=16,
    ),
}

DEFAULT_MODEL_SIZE = "medium"

# Standard model search paths (checked in order)
MODEL_SEARCH_PATHS = [
    Path("/models"),           # Docker volume mount
    Path.home() / ".specs-agent" / "models",  # User local
    Path("./models"),          # Relative to CWD
]


# ------------------------------------------------------------------ #
# Resolution
# ------------------------------------------------------------------ #


def resolve_model_path(
    model_size: str = "",
    model_path: str = "",
) -> Path | None:
    """Find the GGUF model file on disk.

    Resolution order:
    1. `model_path` — explicit path from config / env. If set and exists, use it.
    2. `model_size` — "small" or "medium" preset name. Look for the
       preset's filename in MODEL_SEARCH_PATHS.
    3. Env overrides: `SPECS_AGENT_AI_MODEL_PATH`, `SPECS_AGENT_AI_MODEL_SIZE`.

    Returns the Path to the .gguf file, or None if not found.
    """
    # 1. Explicit path (env → config)
    explicit = os.environ.get("SPECS_AGENT_AI_MODEL_PATH", model_path).strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p
        # Maybe they set a custom path that doesn't exist yet — skip

    # 2. Preset lookup
    size = os.environ.get("SPECS_AGENT_AI_MODEL_SIZE", model_size or DEFAULT_MODEL_SIZE).strip().lower()

    # If size is an absolute path, treat it as explicit
    if size.startswith("/") or size.startswith("~"):
        p = Path(size).expanduser()
        if p.exists():
            return p

    preset = PRESETS.get(size)
    if not preset:
        return None

    # Search known paths for the preset's filename
    for search_dir in MODEL_SEARCH_PATHS:
        candidate = search_dir / preset.filename
        if candidate.exists():
            return candidate

    return None


def get_download_command(size: str = DEFAULT_MODEL_SIZE) -> str:
    """Return the huggingface-cli command to download a preset model."""
    preset = PRESETS.get(size)
    if not preset:
        return f"# Unknown preset: {size}"
    return (
        f"huggingface-cli download {preset.hf_repo} {preset.filename} "
        f"--local-dir ./models"
    )


def get_preset_info() -> list[dict[str, Any]]:
    """Return info about all available presets for display in the UI."""
    return [
        {
            "name": p.name,
            "hf_repo": p.hf_repo,
            "filename": p.filename,
            "description": p.description,
            "size_gb": p.size_gb,
            "ram_needed_gb": p.ram_needed_gb,
            "download_command": get_download_command(p.name),
        }
        for p in PRESETS.values()
    ]
