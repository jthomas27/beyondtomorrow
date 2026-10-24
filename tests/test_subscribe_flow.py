#!/usr/bin/env python3
"""Test that the Ghost subscribe flow works end-to-end through Cloudflare."""

import os
import sys
import time

import httpx
import jwt
from dotenv import load_dotenv

load_dotenv()

ghost_url = os.getenv("GHOST_URL")
admin_key = os.getenv("GHOST_ADMIN_KEY")
key_id, secret = admin_key.split(":")

TEST_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "copilot-subscribe-test@example.com"


def build_token():
    iat = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}
    return jwt.encode(payload, bytes.fromhex(secret), algorithm="HS256", headers=header)


def main():
    # 1. Test magic-link endpoint through Cloudflare
    print("=== Test 1: POST /members/api/send-magic-link/ (via Cloudflare) ===")
    r = httpx.post(
        f"{ghost_url}/members/api/send-magic-link/",
        json={"email": TEST_EMAIL, "emailType": "subscribe"},
        headers={
            "Content-Type": "application/json",
            "Origin": ghost_url,
            "Referer": f"{ghost_url}/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        },
        timeout=15,
    )
    print(f"  Status: {r.status_code}")
    if r.status_code == 201:
        print("  PASS - Magic link sent successfully")
    elif r.status_code == 403 and "cloudflare" in r.text.lower():
        print("  FAIL - Still blocked by Cloudflare WAF")
        return
    else:
        print(f"  Body: {r.text[:300]}")

    print()

    # 2. Verify the member was created in Ghost
    print("=== Test 2: Verify member exists in Ghost ===")
    headers = {"Authorization": f"Ghost {build_token()}"}
    r = httpx.get(
        f"{ghost_url}/ghost/api/admin/members/",
        headers=headers,
        params={"filter": f"email:{TEST_EMAIL}"},
        timeout=15,
    )
    members = r.json().get("members", [])
    if members:
        m = members[0]
        print(f"  Email: {m['email']}")
        print(f"  Status: {m['status']}")
        print(f"  Created: {m['created_at']}")
        print("  PASS - Member created successfully")
    else:
        print("  FAIL - Member not found")

    print()

    # 3. Check CSP frame-src includes 'self'
    print("=== Test 3: CSP frame-src includes 'self' ===")
    r = httpx.get(
        f"{ghost_url}/",
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        timeout=15,
    )
    csp = r.headers.get("content-security-policy", "")
    if "frame-src" in csp:
        frame_src = [p for p in csp.split(";") if "frame-src" in p][0].strip()
        print(f"  {frame_src}")
        if "'self'" in frame_src:
            print("  PASS - frame-src includes 'self'")
        else:
            print("  FAIL - frame-src missing 'self' (Ghost Portal iframe will be blocked)")
    else:
        print("  No frame-src directive found in CSP")
        print(f"  Full CSP: {csp[:200]}")

    print()

    # 4. Check portal_button is still enabled
    print("=== Test 4: Portal button enabled ===")
    headers = {"Authorization": f"Ghost {build_token()}"}
    r = httpx.get(f"{ghost_url}/ghost/api/admin/settings/", headers=headers, timeout=15)
    settings = {s["key"]: s["value"] for s in r.json().get("settings", [])}
    portal_button = settings.get("portal_button")
    print(f"  portal_button: {portal_button}")
    if str(portal_button).lower() == "true":
        print("  PASS")
    else:
        print("  FAIL - Portal button is disabled")

    print()

    # 5. Clean up test member
    print("=== Cleanup: Deleting test member ===")
    headers = {"Authorization": f"Ghost {build_token()}"}
    r = httpx.get(
        f"{ghost_url}/ghost/api/admin/members/",
        headers=headers,
        params={"filter": f"email:{TEST_EMAIL}"},
        timeout=15,
    )
    for m in r.json().get("members", []):
        headers = {"Authorization": f"Ghost {build_token()}"}
        dr = httpx.delete(f"{ghost_url}/ghost/api/admin/members/{m['id']}/", headers=headers, timeout=15)
        print(f"  Deleted {m['email']}: {dr.status_code}")

    print()
    print("=== Done ===")


if __name__ == "__main__":
    main()
