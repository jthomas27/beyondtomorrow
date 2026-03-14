"""
agents/tools/files.py — Research file I/O tools

All files are stored under the research/ directory at the project root.
Paths are validated to prevent path traversal attacks.

Tools:
    read_research_file(filename)         — Read a file from research/
    write_research_file(filename, content) — Write a file to research/
"""

import os
import pathlib
import random
from pipeline._sdk import function_tool

# Resolve research/ directory relative to this file's location
_RESEARCH_DIR = pathlib.Path(__file__).parents[2] / "research"

# Resolve assets/images/ directory relative to this file's location
_ASSETS_IMAGES_DIR = pathlib.Path(__file__).parents[2] / "assets" / "images"

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _safe_path(filename: str) -> pathlib.Path:
    """Return a resolved path under research/, raising ValueError on traversal."""
    _RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    resolved = (_RESEARCH_DIR / filename).resolve()
    if not str(resolved).startswith(str(_RESEARCH_DIR.resolve())):
        raise ValueError(f"Path traversal attempt blocked: {filename}")
    return resolved


@function_tool
async def read_research_file(filename: str) -> str:
    """Read a file from the research/ directory.

    Args:
        filename: Name of the file to read (e.g. '2026-02-22-quantum.md').
                  Subdirectories are allowed (e.g. 'reports/quantum.md').
    """
    try:
        path = _safe_path(filename)
    except ValueError as exc:
        return f"Error: {exc}"

    if not path.exists():
        return f"File not found: research/{filename}"

    return path.read_text(encoding="utf-8")


@function_tool
async def write_research_file(filename: str, content: str) -> str:
    """Write content to a file in the research/ directory. Creates the file if it doesn't exist.

    Args:
        filename: Name of the file to write (e.g. '2026-02-22-quantum.md').
                  Subdirectories are created automatically.
        content: The full content to write to the file.
    """
    try:
        path = _safe_path(filename)
    except ValueError as exc:
        return f"Error: {exc}"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Written {len(content):,} characters to research/{filename}"


@function_tool
async def pick_random_asset_image() -> str:
    """Pick a random image file from the assets/images/ directory.

    Returns the absolute path to the selected image, or an error message
    if the directory is missing or contains no supported images.
    """
    if not _ASSETS_IMAGES_DIR.exists():
        return f"Error: assets/images/ directory not found at {_ASSETS_IMAGES_DIR}"

    images = [
        f for f in _ASSETS_IMAGES_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTENSIONS
    ]

    if not images:
        return "Error: No image files found in assets/images/"

    chosen = random.choice(images)
    return str(chosen)
