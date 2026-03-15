#!/usr/bin/env python3
"""
Fix Ghost subscribe feature:
1. Enable portal_button (the floating subscribe button)
2. Enable portal_name (collect subscriber names)
3. Verify newsletter is active and configured

Requires session auth since Ghost settings API returns 501 for token auth.
"""

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

GHOST_URL = os.getenv("GHOST_URL", "https://beyondtomorrow.world")
ADMIN_EMAIL = "admin@beyondtomorrow.world"


def get_password():
    pw = os.getenv("GHOST_ADMIN_PASSWORD", "")
    if not pw:
        import getpass
        pw = getpass.getpass("Ghost admin password: ")
    return pw


def session_login(client, email, password):
    """Log in via Ghost session auth, returns cookie header."""
    print("Logging in via session auth...")
    r = client.post(
        f"{GHOST_URL}/ghost/api/admin/session/",
        json={"username": email, "password": password},
        headers={"Origin": GHOST_URL},
    )
    if r.status_code == 201:
        print("  Logged in successfully")
        return r.cookies
    elif r.status_code == 403:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        errors = body.get("errors", [])
        if errors and "device" in str(errors[0].get("message", "")).lower():
            print("  Device verification required!")
            print("  Check your email for the verification code.")
            code = input("  Enter verification code: ").strip()
            r2 = client.put(
                f"{GHOST_URL}/ghost/api/admin/session/verify/",
                json={"token": code},
                headers={"Origin": GHOST_URL},
                cookies=r.cookies,
            )
            if r2.status_code == 200:
                print("  Verified and logged in")
                return r2.cookies
            else:
                print(f"  Verification failed: {r2.status_code} {r2.text[:300]}")
                sys.exit(1)
        else:
            print(f"  Login failed (403): {r.text[:300]}")
            sys.exit(1)
    elif r.status_code == 429:
        print("  Rate limited. Wait a few minutes and retry.")
        sys.exit(1)
    else:
        print(f"  Login failed ({r.status_code}): {r.text[:300]}")
        sys.exit(1)


def main():
    password = get_password()

    with httpx.Client(timeout=15, follow_redirects=True) as client:
        cookies = session_login(client, ADMIN_EMAIL, password)

        # Read current settings
        print("\nReading current settings...")
        r = client.get(
            f"{GHOST_URL}/ghost/api/admin/settings/",
            headers={"Origin": GHOST_URL},
            cookies=cookies,
        )
        if r.status_code != 200:
            print(f"  Failed to read settings: {r.status_code} {r.text[:300]}")
            sys.exit(1)

        current = {s["key"]: s["value"] for s in r.json().get("settings", [])}
        print(f"  portal_button: {current.get('portal_button')}")
        print(f"  portal_name: {current.get('portal_name')}")
        print(f"  members_signup_access: {current.get('members_signup_access')}")
        print(f"  members_enabled: {current.get('members_enabled')}")

        # Update portal settings
        print("\nUpdating portal settings...")
        settings_to_update = {
            "settings": [
                {"key": "portal_button", "value": "true"},
                {"key": "portal_name", "value": "true"},
            ]
        }

        r = client.put(
            f"{GHOST_URL}/ghost/api/admin/settings/",
            json=settings_to_update,
            headers={"Origin": GHOST_URL},
            cookies=cookies,
        )

        if r.status_code == 200:
            updated = {s["key"]: s["value"] for s in r.json().get("settings", [])}
            print(f"  portal_button: {updated.get('portal_button')}")
            print(f"  portal_name: {updated.get('portal_name')}")
            print("  Portal settings updated!")
        else:
            print(f"  Failed to update: {r.status_code} {r.text[:500]}")

        # Verify newsletter
        print("\nChecking newsletter configuration...")
        r = client.get(
            f"{GHOST_URL}/ghost/api/admin/newsletters/",
            headers={"Origin": GHOST_URL},
            cookies=cookies,
        )
        if r.status_code == 200:
            newsletters = r.json().get("newsletters", [])
            for nl in newsletters:
                print(f"  Newsletter: {nl['name']}")
                print(f"    Status: {nl['status']}")
                print(f"    Subscribe on signup: {nl['subscribe_on_signup']}")
        else:
            print(f"  Failed: {r.status_code}")

        print("\nDone!")


if __name__ == "__main__":
    main()
