"""
pipeline/tools/tags.py — Nav-tag normalisation for published posts.

The category tab bar in the Ghost theme (theme/header.txt) is driven entirely
by five **nav tags**:

    Climate · Technology · Geopolitics · Economics · Science

A post only appears under a category tab if it carries that exact tag. The
Writer is instructed to apply one primary theme tag plus supporting tags, but
for science/psychology topics it sometimes applies only granular subtopic tags
(e.g. ``Biology``, ``Psychology``) and omits the parent nav tag — so the post
shows under "All" but no category tab.

``normalise_tags`` guarantees that every recognised subtopic's parent nav tag
is present in the final tag list, without removing the original tags. This is a
deterministic safety net independent of the LLM.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The five tags the nav bar keys on. Order is the tab order in the theme.
NAV_TAGS: tuple[str, ...] = ("Climate", "Technology", "Geopolitics", "Economics", "Science")

# Maps a supporting/subtopic tag (lower-cased) to its parent nav tag.
# Covers every canonical supporting tag in config/topics.yaml plus a curated
# set of common non-canonical aliases the Writer has emitted in practice.
# Ambiguous tags (e.g. a bare "Health") are deliberately omitted so they never
# trigger a false nav classification.
_PARENT: dict[str, str] = {
    # ── Climate & energy ──
    "energy transition": "Climate",
    "renewable energy": "Climate",
    "fossil fuels": "Climate",
    "emissions": "Climate",
    "carbon pricing": "Climate",
    "net zero": "Climate",
    "decarbonisation": "Climate",
    "decarbonization": "Climate",
    "climate risk": "Climate",
    "energy security": "Climate",
    "stranded assets": "Climate",
    "sustainability": "Climate",
    # ── AI & technology ──
    "machine learning": "Technology",
    "data centres": "Technology",
    "data centers": "Technology",
    "semiconductors": "Technology",
    "automation": "Technology",
    "cybersecurity": "Technology",
    "ai": "Technology",
    "artificial intelligence": "Technology",
    # ── Geopolitics & society ──
    "supply chains": "Geopolitics",
    "trade": "Geopolitics",
    "sanctions": "Geopolitics",
    "china": "Geopolitics",
    "united states": "Geopolitics",
    "european union": "Geopolitics",
    "critical minerals": "Geopolitics",
    "food security": "Geopolitics",
    "demographics": "Geopolitics",
    # ── Economics & investment ──
    "investment risk": "Economics",
    "financial markets": "Economics",
    "monetary policy": "Economics",
    "fiscal policy": "Economics",
    "inflation": "Economics",
    "credit risk": "Economics",
    "esg": "Economics",
    "sovereign debt": "Economics",
    "behavioral economics": "Economics",
    "behavioural economics": "Economics",
    "decision making": "Economics",
    "commodities": "Economics",
    "investment": "Economics",
    # ── Science ──
    "space science": "Science",
    "biology": "Science",
    "physics": "Science",
    "neuroscience": "Science",
    "biotechnology": "Science",
    "medicine": "Science",
    "materials science": "Science",
    "oceanography": "Science",
    "astronomy": "Science",
    "public health": "Science",
    "psychology": "Science",
    "cognitive science": "Science",
}

_NAV_LOWER = {t.lower(): t for t in NAV_TAGS}


def _split(tags_str: str) -> list[str]:
    return [t.strip() for t in tags_str.split(",") if t.strip()]


def normalise_tags(tags_str: str) -> str:
    """Ensure at least one nav tag is present, preserving the original tags.

    For every tag that maps to a parent nav tag, that nav tag is added to the
    list if not already present. Original tags and their order are preserved;
    inferred nav tags are appended. Returns a comma-separated string.

    If no tag maps to a nav parent and none is present, the input is returned
    unchanged (the publisher cannot safely guess a category).
    """
    tags = _split(tags_str)
    if not tags:
        return tags_str

    present_lower = {t.lower() for t in tags}

    # Collect parent nav tags implied by any subtopic, in nav-bar order.
    inferred: list[str] = []
    for tag in tags:
        parent = _PARENT.get(tag.lower())
        if parent and parent.lower() not in present_lower and parent not in inferred:
            inferred.append(parent)

    if not inferred:
        if not (present_lower & _NAV_LOWER.keys()):
            logger.warning(
                "Tag normalisation: no nav tag present and none inferable from %r — "
                "post will not appear under any category tab.",
                tags,
            )
        return ", ".join(tags)

    # Append inferred nav tags in canonical nav-bar order for stable output.
    ordered_inferred = [t for t in NAV_TAGS if t in inferred]
    result = tags + ordered_inferred
    logger.info("Tag normalisation: added nav tag(s) %s to %r.", ordered_inferred, tags)
    return ", ".join(result)
