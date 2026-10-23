"""Restore unchanged release assets omitted to fit Railway upload limits."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import httpx

BASE_URL = "https://raw.githubusercontent.com/jthomas27/beyondtomorrow/8a0fe2a85cab3e9011fb2ab702938e172227109b/"

root = Path(__file__).resolve().parents[1]
manifest_path = root / "release-manifest.json"
if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text())
    def restore(item):
        name, expected = item
        target = root / name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
            return
        response = httpx.get(BASE_URL + name, timeout=90, follow_redirects=True)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != expected:
            raise RuntimeError("Asset hash mismatch: " + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
    assets = [(name, digest) for name, digest in manifest.items() if name.startswith("assets/")]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(restore, assets))
    print(f"Verified {len(assets)} release assets")
