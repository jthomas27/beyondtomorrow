"""scripts/clean_research_file.py

Sanitise LLM punctuation artefacts in an existing research file on disk.

Applies the same _clean_llm_text() pass used at write_research_file() time,
fixing garbled characters that were written before the guardrail was added:

    \x0026mdash;  → —  (em dash)
    \x0027        → '  (apostrophe)
    \x1a          → '  (contraction) or , (clause separator)
    &nbsp;        → space

Usage:
    .venv/bin/python scripts/clean_research_file.py <filename>

    <filename> can be:
      - a bare filename:       2026-04-05-my-post-edited.md
      - a relative path:       research/2026-04-05-my-post-edited.md
      - an absolute path:      /full/path/to/file.md
      - 'all'                  to process every .md file in research/
"""

import sys
from pathlib import Path

# Allow running from the project root without installing the package
sys.path.insert(0, str(Path(__file__).parents[1]))

from pipeline.tools.files import _clean_llm_text

RESEARCH_DIR = Path(__file__).parents[1] / "research"


def _resolve(filename: str) -> list[Path]:
    if filename.lower() == "all":
        return sorted(RESEARCH_DIR.glob("*.md"))
    p = Path(filename)
    if p.is_absolute():
        return [p]
    # Strip leading research/ prefix if given
    for prefix in ("research/", "research\\"):
        if filename.lower().startswith(prefix):
            return [RESEARCH_DIR / filename[len(prefix):]]
    # Try research/ first, then as-is
    candidate = RESEARCH_DIR / filename
    return [candidate if candidate.exists() else p]


def clean_file(path: Path) -> bool:
    if not path.exists():
        print(f"  SKIP  {path} — not found")
        return False
    original = path.read_bytes()
    text = original.decode("utf-8", errors="replace")
    cleaned = _clean_llm_text(text)
    cleaned_bytes = cleaned.encode("utf-8")
    if cleaned_bytes == original:
        print(f"  OK    {path.name} — no changes needed")
        return False
    path.write_bytes(cleaned_bytes)
    # Count improvements
    em = cleaned.count("\u2014")
    apos = cleaned.count("'")
    removed = len(original) - len(cleaned_bytes)
    print(f"  FIXED {path.name} — em dashes: {em}, apostrophes: {apos}, bytes removed: {removed}")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    filename = sys.argv[1]
    paths = _resolve(filename)

    changed = 0
    for p in paths:
        if clean_file(p):
            changed += 1

    print(f"\nDone. {changed}/{len(paths)} file(s) modified.")


if __name__ == "__main__":
    main()
