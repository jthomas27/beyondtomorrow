"""
pipeline/tools/files.py — Research file I/O tools

Files are stored under research/ (drafts, edited posts, JSON findings) or
reports/ (external PDFs and reference documents) at the project root.
Paths are validated to prevent path traversal attacks.

Tools:
    read_research_file(filename)         — Read a file from research/ or reports/
    write_research_file(filename, content) — Write a file to research/
"""

import os
import pathlib
import random
from pipeline._sdk import function_tool

# Resolve research/ and reports/ directories relative to this file's location
_RESEARCH_DIR = pathlib.Path(__file__).parents[2] / "research"
_REPORTS_DIR  = pathlib.Path(__file__).parents[2] / "reports"

# Resolve assets/images/ directory relative to this file's location
_ASSETS_IMAGES_DIR = pathlib.Path(__file__).parents[2] / "assets" / "images"

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _safe_path_in(base_dir: pathlib.Path, filename: str) -> pathlib.Path:
    """Return a resolved path under base_dir, raising ValueError on traversal."""
    base_dir.mkdir(parents=True, exist_ok=True)
    resolved = (base_dir / filename).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ValueError(f"Path traversal attempt blocked: {filename}")
    return resolved


def _safe_path(filename: str) -> pathlib.Path:
    """Return a resolved path under research/ or reports/, raising ValueError on traversal.

    Strips a leading 'research/' or 'reports/' prefix that LLMs sometimes add,
    then routes to the correct base directory.  Unprefixed filenames default to
    research/.
    """
    for prefix in ("research/", "research\\"):
        if filename.lower().startswith(prefix):
            return _safe_path_in(_RESEARCH_DIR, filename[len(prefix):])
    for prefix in ("reports/", "reports\\"):
        if filename.lower().startswith(prefix):
            return _safe_path_in(_REPORTS_DIR, filename[len(prefix):])
    # No explicit prefix — default to research/
    return _safe_path_in(_RESEARCH_DIR, filename)


@function_tool
async def read_research_file(filename: str) -> str:
    """Read a file from the research/ or reports/ directory.

    Checks research/ first (respecting an explicit 'research/' prefix), then
    falls back to reports/ for unprefixed filenames not found in research/.
    Binary files such as PDFs are not readable via this tool — use the INDEX:
    pipeline command to extract and index PDF content instead.

    Args:
        filename: Name of the file to read (e.g. '2026-02-22-quantum.md' or
                  'reports/WMO-1391-2025_en.pdf').
    """
    try:
        path = _safe_path(filename)
    except ValueError as exc:
        return f"Error: {exc}"

    # If the file wasn't found and no explicit directory prefix was given,
    # also check the other directory.
    if not path.exists():
        has_prefix = any(
            filename.lower().startswith(p)
            for p in ("research/", "research\\", "reports/", "reports\\")
        )
        if not has_prefix:
            try:
                alt_path = _safe_path_in(_REPORTS_DIR, filename)
                if alt_path.exists():
                    path = alt_path
                else:
                    return f"File not found in research/ or reports/: {filename}"
            except ValueError:
                pass
        if not path.exists():
            return f"File not found: {filename}"

    if path.suffix.lower() == ".pdf":
        return (
            f"Binary PDF file — cannot read as text: {filename}. "
            "Use the pipeline INDEX: command to extract and index its content."
        )

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
