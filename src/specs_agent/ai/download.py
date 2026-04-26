"""Model downloader — fetches a Gemma 4 GGUF model from HuggingFace.

Called automatically on first use when AI is enabled and no model file
is found locally. Can also be run directly as a CLI:

    python -m specs_agent.ai.download              # default (medium)
    python -m specs_agent.ai.download --size small  # small preset

The download goes to `~/.specs-agent/models/` by default, or to the
path specified by `SPECS_AGENT_AI_MODEL_PATH`.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

from specs_agent.ai.models import DEFAULT_MODEL_SIZE, PRESETS

# HuggingFace direct download URL pattern
_HF_URL = "https://huggingface.co/{repo}/resolve/main/{filename}"

DEFAULT_MODEL_DIR = Path.home() / ".specs-agent" / "models"


def download_model(
    size: str = DEFAULT_MODEL_SIZE,
    dest_dir: Path | None = None,
    force: bool = False,
) -> Path:
    """Download a Gemma 4 GGUF model from HuggingFace.

    Args:
        size: Preset name ("small" or "medium") or a custom HF repo.
        dest_dir: Where to save the file. Defaults to ~/.specs-agent/models/.
        force: If True, re-download even if the file already exists.

    Returns:
        Path to the downloaded .gguf file.

    Raises:
        ValueError: If the size preset is unknown.
        RuntimeError: If the download fails.
    """
    preset = PRESETS.get(size)
    if not preset:
        raise ValueError(
            f"Unknown model size '{size}'. Available: {', '.join(PRESETS.keys())}"
        )

    dest_dir = dest_dir or DEFAULT_MODEL_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / preset.filename

    if dest_path.exists() and not force:
        print(f"Model already exists: {dest_path}")
        return dest_path

    url = _HF_URL.format(repo=preset.hf_repo, filename=preset.filename)
    print(f"Downloading {preset.description}")
    print(f"  From: {url}")
    print(f"  To:   {dest_path}")
    print(f"  Size: ~{preset.size_gb} GB")
    print()

    try:
        _download_with_progress(url, dest_path)
    except Exception as exc:
        # Clean up partial file
        if dest_path.exists():
            dest_path.unlink()
        raise RuntimeError(f"Download failed: {exc}") from exc

    print(f"\nDone. Model saved to {dest_path}")
    return dest_path


def ensure_model(
    size: str = DEFAULT_MODEL_SIZE,
    dest_dir: Path | None = None,
) -> Path | None:
    """Ensure a model exists locally. Download if missing.

    Non-interactive: prints progress but doesn't prompt. Returns the path
    to the model, or None if download fails.
    """
    from specs_agent.ai.models import resolve_model_path

    # Check if already available
    existing = resolve_model_path(model_size=size)
    if existing:
        return existing

    try:
        return download_model(size=size, dest_dir=dest_dir)
    except Exception as exc:
        print(f"Warning: could not download model: {exc}", file=sys.stderr)
        return None


def _download_with_progress(url: str, dest: Path) -> None:
    """Download a URL to a file with a simple progress indicator."""
    req = urllib.request.Request(url, headers={"User-Agent": "specs-agent/0.1"})
    with urllib.request.urlopen(req) as response:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 1024 * 1024  # 1 MB chunks

        with open(dest, "wb") as f:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    bar = "#" * int(pct // 2) + "-" * (50 - int(pct // 2))
                    mb_done = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    print(
                        f"\r  [{bar}] {pct:.1f}% ({mb_done:.0f}/{mb_total:.0f} MB)",
                        end="",
                        flush=True,
                    )
                else:
                    mb_done = downloaded / (1024 * 1024)
                    print(f"\r  Downloaded {mb_done:.0f} MB...", end="", flush=True)


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download a Gemma 4 GGUF model")
    parser.add_argument(
        "--size", default=DEFAULT_MODEL_SIZE, choices=list(PRESETS.keys()),
        help=f"Model preset (default: {DEFAULT_MODEL_SIZE})",
    )
    parser.add_argument(
        "--dest", default=None, type=Path,
        help=f"Destination directory (default: {DEFAULT_MODEL_DIR})",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if exists")
    args = parser.parse_args()

    try:
        download_model(size=args.size, dest_dir=args.dest, force=args.force)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
