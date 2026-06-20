#!/usr/bin/env python3
"""
scripts/tag_existing_posts.py — Audit and backfill primary category tags on Ghost posts.

Ghost's category tab bar (injected via Code Injection) links to /tag/climate/,
/tag/technology/, /tag/geopolitics/, and /tag/economics/.  Every published post
must have at least one of the six primary category tags so those tag pages are
never empty.

Primary category tags (must use exact casing):
    Climate, Technology, Geopolitics, Economics, AI, Futures

Usage
-----
Dry-run (audit only — no changes made):
    .venv/bin/python scripts/tag_existing_posts.py

Apply inferred tags to posts that are missing a primary category:
    .venv/bin/python scripts/tag_existing_posts.py --apply

Requires GHOST_URL and GHOST_ADMIN_KEY in .env (or environment).
"""

import argparse
import os
import sys
import time
import httpx
import jwt
from dotenv import load_dotenv

load_dotenv()

# ── Primary category tags ──────────────────────────────────────────────────
PRIMARY_TAGS = {"Climate", "Technology", "Geopolitics", "Economics", "AI", "Futures"}

# ── Inference map: keyword (lowercase) → primary category ────────────────
# Matched case-insensitively against each tag name and (as fallback) the post
# title.  The first match wins — most specific patterns listed first.
INFERENCE_MAP = [
    # AI — check before Technology so "ai" tags hit AI first
    ("ai agent",            "AI"),
    ("ai model",            "AI"),
    ("artificial intellig", "AI"),
    ("machine learning",    "AI"),
    ("deep learning",       "AI"),
    ("large language",      "AI"),
    ("llm",                 "AI"),
    ("generative ai",       "AI"),
    # Climate
    ("climate",             "Climate"),
    ("net zero",            "Climate"),
    ("carbon",              "Climate"),
    ("emissions",           "Climate"),
    ("decarboni",           "Climate"),
    ("fossil fuel",         "Climate"),
    ("renewable",           "Climate"),
    ("energy transition",   "Climate"),
    ("energy security",     "Climate"),
    ("stranded asset",      "Climate"),
    ("transition risk",     "Climate"),
    ("sustainability",      "Climate"),
    # Technology
    ("technology",          "Technology"),
    ("cybersecur",          "Technology"),
    ("semiconductor",       "Technology"),
    ("data centre",         "Technology"),
    ("data center",         "Technology"),
    ("automation",          "Technology"),
    ("governance",          "Technology"),
    ("infrastructure",      "Technology"),
    ("tech ethic",          "Technology"),
    # Geopolitics
    ("geopolit",            "Geopolitics"),
    ("supply chain",        "Geopolitics"),
    ("sanction",            "Geopolitics"),
    ("critical mineral",    "Geopolitics"),
    ("food security",       "Geopolitics"),
    ("trade war",           "Geopolitics"),
    ("emerging market",     "Geopolitics"),
    ("developed market",    "Geopolitics"),
    ("india",               "Geopolitics"),
    ("china",               "Geopolitics"),
    ("europe",              "Geopolitics"),
    ("uk economy",          "Economics"),   # UK economy is Economics not Geopolitics
    # Economics — after UK economy rule above
    ("econom",              "Economics"),
    ("investment",          "Economics"),
    ("financial",           "Economics"),
    ("monetary policy",     "Economics"),
    ("fiscal policy",       "Economics"),
    ("inflation",           "Economics"),
    ("stagflat",            "Economics"),
    ("credit risk",         "Economics"),
    ("finance",             "Economics"),
    ("commodity",           "Economics"),
    ("factor invest",       "Economics"),
    ("equity",              "Economics"),
    ("market",              "Economics"),
]


# ── Ghost JWT helper ───────────────────────────────────────────────────────

def _make_token(admin_key: str) -> str:
    key_id, secret = admin_key.split(":", 1)
    iat = int(time.time())
    return jwt.encode(
        {"iat": iat, "exp": iat + 300, "aud": "/admin/"},
        bytes.fromhex(secret),
        algorithm="HS256",
        headers={"alg": "HS256", "typ": "JWT", "kid": key_id},
    )


def _auth_headers(admin_key: str) -> dict:
    return {
        "Authorization": f"Ghost {_make_token(admin_key)}",
        "Content-Type": "application/json",
    }


# ── Fetch all published posts with their tags ──────────────────────────────

def fetch_all_posts(ghost_url: str, admin_key: str) -> list[dict]:
    posts: list[dict] = []
    page = 1
    while True:
        url = (
            f"{ghost_url}/ghost/api/admin/posts/"
            f"?limit=100&page={page}&include=tags&filter=status:published"
            f"&fields=id,title,slug,updated_at"
        )
        resp = httpx.get(url, headers=_auth_headers(admin_key), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("posts", [])
        posts.extend(batch)
        meta = data.get("meta", {}).get("pagination", {})
        if page >= meta.get("pages", 1):
            break
        page += 1
    return posts


# ── Infer a primary category from a post's existing tags ──────────────────

def infer_primary_tag(existing_tag_names: list[str], title: str = "") -> str | None:
    """Return the best primary category inferred from supporting tags or title.

    Matching is case-insensitive substring search so partial keywords work
    regardless of how the tag was originally capitalised in Ghost.
    """
    candidates = [t.strip().lower() for t in existing_tag_names]
    # First pass: match against tag names
    for keyword, primary in INFERENCE_MAP:
        if any(keyword in c for c in candidates):
            return primary
    # Second pass: match against post title (last resort)
    title_lower = title.lower()
    for keyword, primary in INFERENCE_MAP:
        if keyword in title_lower:
            return primary
    return None


# ── Apply a tag to a post via Ghost Admin API ─────────────────────────────

def apply_tag(ghost_url: str, admin_key: str, post: dict, tag_name: str) -> bool:
    """Append tag_name to the post's existing tags and PUT to Ghost."""
    existing = [{"name": t["name"]} for t in post.get("tags", [])]
    existing.append({"name": tag_name})
    payload = {
        "posts": [{
            "id": post["id"],
            "updated_at": post["updated_at"],
            "tags": existing,
        }]
    }
    url = f"{ghost_url}/ghost/api/admin/posts/{post['id']}/"
    resp = httpx.put(url, json=payload, headers=_auth_headers(admin_key), timeout=20)
    if resp.status_code in (200, 201):
        return True
    print(f"    ERROR {resp.status_code}: {resp.text[:200]}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Apply inferred tags (default: dry-run audit only)")
    args = parser.parse_args()

    ghost_url = os.environ.get("GHOST_URL", "").rstrip("/")
    admin_key = os.environ.get("GHOST_ADMIN_KEY", "")

    if not ghost_url or not admin_key:
        print("ERROR: GHOST_URL and GHOST_ADMIN_KEY must be set in .env or environment.")
        sys.exit(1)
    if ":" not in admin_key:
        print("ERROR: GHOST_ADMIN_KEY must be in 'id:secret' format.")
        sys.exit(1)

    print(f"Fetching published posts from {ghost_url} …")
    posts = fetch_all_posts(ghost_url, admin_key)
    print(f"Found {len(posts)} published post(s).\n")

    needs_tag: list[tuple[dict, str | None]] = []
    for post in posts:
        tag_names = [t["name"] for t in post.get("tags", [])]
        if not any(t in PRIMARY_TAGS for t in tag_names):
            inferred = infer_primary_tag(tag_names, title=post.get("title", ""))
            needs_tag.append((post, inferred))

    if not needs_tag:
        print("All published posts already have a primary category tag.")
        return

    print(f"{'─' * 80}")
    print(f"Posts missing a primary category tag: {len(needs_tag)}\n")

    applied = 0
    skipped = 0

    for post, inferred in needs_tag:
        tag_names = [t["name"] for t in post.get("tags", [])]
        slug = post.get("slug", "")
        title = post.get("title", "(no title)")
        tags_display = ", ".join(tag_names) if tag_names else "(none)"
        inferred_display = inferred if inferred else "⚠  could not infer — manual review needed"

        print(f"  POST : {title}")
        print(f"  URL  : {ghost_url}/{slug}/")
        print(f"  TAGS : {tags_display}")
        print(f"  INFER: {inferred_display}")

        if args.apply:
            if inferred:
                ok = apply_tag(ghost_url, admin_key, post, inferred)
                if ok:
                    print(f"  → Tagged '{inferred}' ✓")
                    applied += 1
                else:
                    skipped += 1
            else:
                print(f"  → Skipped (cannot infer — add tag manually in Ghost Admin)")
                skipped += 1
        print()

    if args.apply:
        print(f"{'─' * 80}")
        print(f"Applied: {applied}  |  Skipped (manual review needed): {skipped}")
    else:
        print(f"{'─' * 80}")
        print("Dry-run complete — no changes made.")
        print("Re-run with --apply to patch inferred tags.")


if __name__ == "__main__":
    main()
