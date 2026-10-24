"""Back up and remove the identified malicious script through Ghost Admin API.

Default mode is read-only. --apply removes script elements whose src hostname
is exactly the known indicator; it does not clear unrelated code injection.
Backups and reports are private local files under gitignored logs/.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import unescape
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

import httpx
import jwt
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
INDICATOR = "aniyara.icu"
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
SRC = re.compile(r"\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)


def script_host(tag: str) -> str:
    opening = tag.split(">", 1)[0]
    match = SRC.search(opening)
    if not match:
        return ""
    url = unescape(next(v for v in match.groups() if v is not None)).strip()
    return (urlsplit(url if not url.startswith("//") else "https:" + url).hostname or "").lower()


def remove_indicator(text: str) -> str:
    return SCRIPT.sub(lambda m: "" if script_host(m.group()) == INDICATOR else m.group(), text)


def clean_lexical(value):
    if isinstance(value, dict):
        return {key: clean_lexical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_lexical(item) for item in value]
    if isinstance(value, str):
        return remove_indicator(value)
    return value


def changes_for(post: dict) -> dict:
    changes = {}
    for key in ("codeinjection_head", "codeinjection_foot"):
        value = post.get(key) or ""
        cleaned = remove_indicator(value)
        if cleaned != value:
            changes[key] = cleaned
    lexical = post.get("lexical")
    if lexical and INDICATOR in lexical.lower():
        parsed = json.loads(lexical)
        cleaned = clean_lexical(parsed)
        if cleaned != parsed:
            changes["lexical"] = json.dumps(cleaned, ensure_ascii=False)
    return changes


def has_indicator(post: dict) -> bool:
    return any(INDICATOR in (post.get(key) or "").lower() for key in
               ("codeinjection_head", "codeinjection_foot", "lexical", "html"))


def private_json(path: Path, value) -> None:
    with open(path, "x", encoding="utf-8", opener=lambda name, flags: os.open(name, flags, 0o600)) as out:
        json.dump(value, out, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    base = os.environ["GHOST_URL"].rstrip("/")
    key_id, secret = os.environ["GHOST_ADMIN_KEY"].split(":", 1)

    def request(client, method, path, **kwargs):
        now = int(time.time())
        token = jwt.encode({"iat": now, "exp": now + 240, "aud": "/admin/"},
                           bytes.fromhex(secret), algorithm="HS256", headers={"kid": key_id})
        response = client.request(method, base + "/ghost/api/admin/" + path,
                                  headers={"Authorization": "Ghost " + token}, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"Ghost {method} {path.split('?')[0]} returned HTTP {response.status_code}")
        return response.json()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = ROOT / "logs" / ("ghost-security-" + stamp)
    destination.mkdir(parents=True, mode=0o700)
    with httpx.Client(timeout=30) as client:
        collections = {}
        for kind in ("posts", "pages"):
            collections[kind] = request(client, "GET", kind + "/", params={"limit": "all", "formats": "html,lexical"})[kind]
        private_json(destination / "before.json", collections)
        plan = [(kind, post, changes_for(post)) for kind, posts in collections.items() for post in posts if has_indicator(post)]
        print(json.dumps({"backup": str(destination / "before.json"),
                          "counts": {k: len(v) for k, v in collections.items()}, "affected": len(plan)}), flush=True)
        inventory = Counter(script_host(tag) or "inline" for posts in collections.values() for post in posts
                            for field in ("codeinjection_head", "codeinjection_foot")
                            for tag in SCRIPT.findall(post.get(field) or ""))
        print("Per-article injection script inventory: " + json.dumps(dict(inventory)), flush=True)
        if not args.apply:
            return 0
        results = []
        for kind, post, changes in plan:
            if not changes:
                results.append({"id": post["id"], "status": "needs_manual_review"})
                continue
            payload = {"id": post["id"], "updated_at": post["updated_at"], **changes}
            try:
                request(client, "PUT", kind + "/" + post["id"] + "/", json={kind: [payload]})
                results.append({"id": post["id"], "status": "cleaned", "fields": list(changes)})
            except RuntimeError as exc:
                results.append({"id": post["id"], "status": "failed", "error": str(exc)})
            if len(results) % 20 == 0:
                print(f"Processed {len(results)}/{len(plan)} affected articles", flush=True)
        after = {}
        remaining = []
        invariants = []
        for kind, before in collections.items():
            after[kind] = request(client, "GET", kind + "/", params={"limit": "all", "formats": "html,lexical"})[kind]
            previous = {post["id"]: post for post in before}
            current = {post["id"]: post for post in after[kind]}
            if previous.keys() != current.keys():
                invariants.append(kind + ": article IDs changed")
            for post in after[kind]:
                if has_indicator(post):
                    remaining.append(post["id"])
                old = previous.get(post["id"])
                if old and any(old.get(field) != post.get(field) for field in
                               ("title", "slug", "status", "visibility", "published_at", "lexical")):
                    if not (changes_for(old).get("lexical") and
                            all(old.get(f) == post.get(f) for f in ("title", "slug", "status", "visibility", "published_at"))):
                        invariants.append(post["id"] + ": content/publication metadata changed")
        private_json(destination / "after.json", after)
        report = {"results": results, "remaining_indicator_ids": remaining, "invariant_failures": invariants}
        private_json(destination / "report.json", report)
        print(json.dumps({"cleaned": sum(r["status"] == "cleaned" for r in results),
                          "remaining": len(remaining), "invariant_failures": len(invariants),
                          "report": str(destination / "report.json")}), flush=True)
        return int(bool(remaining or invariants or any(r["status"] != "cleaned" for r in results)))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Ghost cleanup stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
