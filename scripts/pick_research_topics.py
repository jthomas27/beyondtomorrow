#!/usr/bin/env python3
"""scripts/pick_research_topics.py

Selects 3 research topics for this week's automated research run.

Reads config/topics.yaml and uses the ISO week number + year as a
deterministic seed so the same calendar week always produces the same
3 topics. The selection rotates across all 5 themes week by week, and
cycles through each theme's individual topics over successive runs.

Output:
    Writes topic1, topic2, topic3 to $GITHUB_OUTPUT when running in
    GitHub Actions, or prints them to stdout for local testing.

Usage:
    python scripts/pick_research_topics.py
"""

import datetime
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "topics.yaml"


def load_themes(path: Path) -> list[dict]:
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    with open(path) as fh:
        config = yaml.safe_load(fh)

    themes = config.get("themes", [])
    if not themes:
        print("ERROR: No themes found in config/topics.yaml", file=sys.stderr)
        sys.exit(1)

    valid = [t for t in themes if t.get("topics")]
    skipped = [t.get("name", "?") for t in themes if not t.get("topics")]
    for name in skipped:
        print(f"WARNING: Theme '{name}' has no topics — skipping", file=sys.stderr)

    return valid


def pick_topics(themes: list[dict], week_seed: int) -> list[tuple[str, str]]:
    """Return (theme_label, topic) for 3 themes, rotating each week.

    Theme rotation: starts at week_seed % n_themes, takes 3 consecutive
    themes (wrapping). Topic within each theme: week_seed % len(topics).
    """
    n = len(themes)
    theme_start = week_seed % n
    selected = [themes[(theme_start + i) % n] for i in range(min(3, n))]

    results = []
    for theme in selected:
        topics = theme["topics"]
        idx = week_seed % len(topics)
        results.append((theme["label"], topics[idx]))
    return results


def main() -> None:
    if not CONFIG_PATH.exists():
        print(f"ERROR: {CONFIG_PATH} not found", file=sys.stderr)
        sys.exit(1)

    today = datetime.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    # Unique seed per calendar week — advances topic index and theme rotation
    week_seed = iso_year * 53 + iso_week

    themes = load_themes(CONFIG_PATH)
    selections = pick_topics(themes, week_seed)

    print(f"Week {iso_week} of {iso_year} (seed={week_seed}) — selected topics:")
    for i, (label, topic) in enumerate(selections, 1):
        print(f"  {i}. [{label}] {topic}")

    # Write to $GITHUB_OUTPUT in Actions; print for local runs
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a") as fh:
            for i, (_, topic) in enumerate(selections, 1):
                fh.write(f"topic{i}={topic}\n")
    else:
        print("\nLocal run — GITHUB_OUTPUT not set.")
        print("Topics that would be passed to the pipeline:")
        for i, (_, topic) in enumerate(selections, 1):
            print(f"  RESEARCH: {topic}")


if __name__ == "__main__":
    main()
