"""
scripts/linkedin_auth.py — One-time LinkedIn OAuth 2.0 authorisation helper.

Obtains an access token and person URN for the LinkedIn API, then saves them
to .env so the pipeline's post_to_linkedin tool can use them.

Requirements: LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env.

Usage:
    .venv/bin/python scripts/linkedin_auth.py
"""

from __future__ import annotations

import http.server
import os
import pathlib
import secrets
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Load .env (same approach as pipeline/main.py — no dotenv dependency)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent


def _load_dotenv() -> None:
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

try:
    import httpx
except ImportError:
    sys.exit("httpx is not installed. Run: .venv/bin/pip install httpx")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("LINKEDIN_REDIRECT_URL", "http://localhost:8000/callback")
CALLBACK_PORT = int(urllib.parse.urlparse(REDIRECT_URI).port or 8000)
CALLBACK_PATH = urllib.parse.urlparse(REDIRECT_URI).path or "/callback"

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

SCOPE = "openid profile w_member_social w_organization_social r_organization_social"

# Scopes that require LinkedIn product approval before they can be requested:
#   w_organization_social  — post to company pages (Marketing Developer Platform)
#   r_organization_social  — read company page data
# If the auth fails with "unauthorized_scope_error", remove them from the request
# temporarily (SCOPE_FALLBACK) and apply for access at https://www.linkedin.com/developers/apps
SCOPE_FALLBACK = "openid profile w_member_social"

# ---------------------------------------------------------------------------
# OAuth callback server
# ---------------------------------------------------------------------------

_callback_result: dict = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = dict(urllib.parse.parse_qsl(parsed.query))
        _callback_result.update(params)

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if "code" in params:
            body = (
                "<html><body style='font-family:sans-serif;padding:2rem'>"
                "<h2>✅ Authorisation successful</h2>"
                "<p>You can close this tab and return to the terminal.</p>"
                "</body></html>"
            )
        else:
            body = (
                "<html><body style='font-family:sans-serif;padding:2rem'>"
                "<h2>❌ Authorisation failed</h2>"
                f"<pre>{params}</pre>"
                "</body></html>"
            )
        self.wfile.write(body.encode())

    def log_message(self, *args):  # suppress server access logs
        pass


def _start_callback_server() -> http.server.HTTPServer:
    server = http.server.HTTPServer(("localhost", CALLBACK_PORT), _CallbackHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

def _exchange_code(code: str) -> dict:
    resp = httpx.post(
        LINKEDIN_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _get_person_id(access_token: str) -> tuple[str, str]:
    """Fetch the member's person ID and name from /v2/userinfo (OpenID Connect). Returns (id, name)."""
    try:
        resp = httpx.get(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("sub", ""), data.get("name", "(unknown)")
    except httpx.HTTPStatusError:
        return "", "(unknown)"


def _get_admin_company_urn(access_token: str) -> tuple[str, str]:
    """Look up organisations the member admins via the LinkedIn REST API.

    Returns (company_urn, org_name) for the first admin org found,
    or ('', '') if none found or the API call fails.
    """
    try:
        resp = httpx.get(
            "https://api.linkedin.com/rest/organizationAcls",
            params={
                "q": "roleAssignee",
                "role": "ADMINISTRATOR",
                "state": "APPROVED",
                "count": 10,
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Linkedin-Version": "202503",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return "", ""
        elements = resp.json().get("elements", [])
        if not elements:
            return "", ""
        # REST API 2024+ uses 'organizationalTarget'; v2 uses 'organization'
        first = elements[0]
        org_urn = first.get("organizationalTarget") or first.get("organization", "")
        if not org_urn:
            return "", ""
        # Try to fetch the org name
        org_id = org_urn.split(":")[-1]
        name_resp = httpx.get(
            f"https://api.linkedin.com/v2/organizations/{org_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        org_name = org_urn  # fallback to URN if name fetch fails
        if name_resp.status_code == 200:
            org_name = name_resp.json().get("localizedName", org_urn)
        return org_urn, org_name
    except Exception as exc:
        print(f"  ⚠️  Could not auto-detect company URN: {exc}")
        return "", ""


# ---------------------------------------------------------------------------
# .env writer
# ---------------------------------------------------------------------------

def _write_to_dotenv(token: str, urn: str, expires: str, company_urn: str = "") -> None:
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.is_file():
        print(f"\n.env not found at {env_path} — skipping write.")
        return

    content = env_path.read_text()
    lines = content.splitlines(keepends=True)
    new_lines = []
    keys_written = set()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("LINKEDIN_ACCESS_TOKEN="):
            new_lines.append(f"LINKEDIN_ACCESS_TOKEN={token}\n")
            keys_written.add("LINKEDIN_ACCESS_TOKEN")
        elif stripped.startswith("LINKEDIN_PERSON_URN="):
            new_lines.append(f"LINKEDIN_PERSON_URN={urn}\n")
            keys_written.add("LINKEDIN_PERSON_URN")
        elif stripped.startswith("LINKEDIN_TOKEN_EXPIRES="):
            new_lines.append(f"LINKEDIN_TOKEN_EXPIRES={expires}\n")
            keys_written.add("LINKEDIN_TOKEN_EXPIRES")
        elif stripped.startswith("LINKEDIN_COMPANY_URN="):
            new_lines.append(f"LINKEDIN_COMPANY_URN={company_urn}\n" if company_urn else line)
            keys_written.add("LINKEDIN_COMPANY_URN")
        else:
            new_lines.append(line)

    # Append any keys not already in the file
    missing_keys: dict[str, str] = {
        "LINKEDIN_ACCESS_TOKEN": f"LINKEDIN_ACCESS_TOKEN={token}\n",
        "LINKEDIN_PERSON_URN": f"LINKEDIN_PERSON_URN={urn}\n",
        "LINKEDIN_TOKEN_EXPIRES": f"LINKEDIN_TOKEN_EXPIRES={expires}\n",
    }
    if company_urn:
        missing_keys["LINKEDIN_COMPANY_URN"] = f"LINKEDIN_COMPANY_URN={company_urn}\n"
    inserts = [v for k, v in missing_keys.items() if k not in keys_written]
    if inserts:
        # Insert after the last LINKEDIN_ line, or append at end
        last_linkedin_idx = -1
        for i, line in enumerate(new_lines):
            if line.strip().startswith("LINKEDIN_"):
                last_linkedin_idx = i
        insert_at = last_linkedin_idx + 1 if last_linkedin_idx >= 0 else len(new_lines)
        new_lines[insert_at:insert_at] = inserts

    env_path.write_text("".join(new_lines))
    print(f"\n✅ Saved to {env_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("LinkedIn OAuth 2.0 — BeyondTomorrow Publisher")
    print("=" * 48)

    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit(
            "\n❌ LINKEDIN_CLIENT_ID and/or LINKEDIN_CLIENT_SECRET are not set.\n"
            "   Add them to .env and re-run this script."
        )

    print(f"  Client ID    : {CLIENT_ID}")
    print(f"  Redirect URI : {REDIRECT_URI}")

    # Try full scope first; fall back to approved-only scopes if LinkedIn rejects org scopes
    active_scope = SCOPE
    _callback_result.clear()

    def _run_oauth(scope: str) -> None:
        """Open browser OAuth flow for the given scope and wait for callback."""
        global _callback_result
        _callback_result.clear()
        state = secrets.token_urlsafe(16)
        auth_params = urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": scope,
            "state": state,
        })
        auth_url = f"{LINKEDIN_AUTH_URL}?{auth_params}"
        server = _start_callback_server()
        print(f"\nOpening LinkedIn authorisation in your browser...")
        print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)
        import time
        print("Waiting for you to approve the app in the browser...", end="", flush=True)
        timeout = 120
        elapsed = 0
        while "code" not in _callback_result and "error" not in _callback_result:
            time.sleep(0.5)
            elapsed += 0.5
            if elapsed >= timeout:
                server.shutdown()
                sys.exit("\n\n❌ Timed out waiting for LinkedIn callback (120s).")
        server.shutdown()
        print(" done.")
        _callback_result["_state"] = state

    print(f"  Scope        : {active_scope}")
    print()
    _run_oauth(active_scope)

    # If org scopes were rejected, retry with fallback
    if _callback_result.get("error") == "unauthorized_scope_error":
        print()
        print("  ⚠️  LinkedIn rejected org scopes (w_organization_social / r_organization_social).")
        print("     These require 'Marketing Developer Platform' or 'Community Management API'")
        print("     product access in your LinkedIn app:")
        print("       https://www.linkedin.com/developers/apps")
        print("     Falling back to personal posting only (w_member_social)...")
        print()
        active_scope = SCOPE_FALLBACK
        print(f"  Scope        : {active_scope}")
        print()
        _run_oauth(active_scope)

    # Check for errors after final attempt
    if "error" in _callback_result:
        sys.exit(
            f"\n❌ LinkedIn returned an error:\n"
            f"   {_callback_result.get('error')}: {_callback_result.get('error_description', '')}"
        )

    # Verify state parameter (CSRF check)
    returned_state = _callback_result.get("state", "")
    expected_state = _callback_result.get("_state", "")
    if returned_state != expected_state:
        sys.exit("\n❌ State mismatch — possible CSRF. Aborting.")

    code = _callback_result["code"]
    print(f"\nReceived authorisation code (length: {len(code)})")

    # Exchange code for token
    print("Exchanging code for access token...")
    try:
        token_data = _exchange_code(code)
    except httpx.HTTPStatusError as e:
        sys.exit(f"\n❌ Token exchange failed: {e.response.status_code} — {e.response.text}")

    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", 5183944)  # LinkedIn default ~60 days
    if not access_token:
        sys.exit(f"\n❌ No access_token in response:\n{token_data}")

    # Verify granted scopes — warn if w_organization_social is missing
    print("Verifying granted scopes...")
    try:
        intro = httpx.post(
            "https://www.linkedin.com/oauth/v2/introspectToken",
            data={
                "token": access_token,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            timeout=15,
        )
        if intro.status_code == 200:
            granted = set(intro.json().get("scope", "").split(","))
            print(f"  Granted scopes: {', '.join(sorted(granted))}")
            if "w_organization_social" not in granted:
                print()
                print("  ⚠️  WARNING: w_organization_social was NOT granted.")
                print("     Company page posting will not work until this scope is approved.")
                print("     To fix:")
                print("       1. Go to https://www.linkedin.com/developers/apps")
                print("       2. Open your app → Products tab")
                print("       3. Request access to 'Share on LinkedIn' (enables w_member_social)")
                print("          and 'Marketing Developer Platform' or 'Community Management API'")
                print("          (enables w_organization_social / r_organization_social)")
                print("       4. Once approved, re-run this script.")
                print()
    except Exception as exc:
        print(f"  Could not verify scopes: {exc}")

    expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    expiry_str = expiry.strftime("%Y-%m-%d")

    # Get person URN
    print("Fetching person ID from LinkedIn userinfo...")
    person_id, name = _get_person_id(access_token)

    if not person_id:
        print()
        print("⚠️  Could not retrieve person ID automatically.")
        print("   To find it manually:")
        print("   1. Go to your LinkedIn profile in a browser")
        print("   2. Right-click → View Page Source")
        print("   3. Search for \"memberId\" or \"publicIdentifier\"")
        print("   Or run this in your browser console on your profile page:")
        print("     document.querySelector('code[id^=\"bpr-guid\"]')?.textContent")
        print()
        person_id = input("Enter your LinkedIn person ID (the alphanumeric ID, not your username): ").strip()
        if not person_id:
            sys.exit("❌ Person ID is required to post on your behalf. Aborting.")

    person_urn = f"urn:li:person:{person_id}"

    # Attempt to find the company page URN automatically
    print("Looking up admin organisations...")
    company_urn, company_name = _get_admin_company_urn(access_token)
    if company_urn:
        print(f"  Found: {company_name} ({company_urn})")
    else:
        print("  None found automatically.")
        print("  To find your company ID manually, visit:")
        print("    https://www.linkedin.com/company/beyond-tomorrow-world/")
        print("  Then view page source and search for 'urn:li:organization:' or 'fsd_company:'.")
        print("  Enter the numeric ID only (e.g. 12345678).")
        print()
        raw_id = input(
            "Enter company numeric ID (leave blank to skip company page posting): "
        ).strip()
        if raw_id:
            company_urn = f"urn:li:organization:{raw_id}"
            company_name = "(manually entered)"
            print(f"  Using: {company_urn}")

    # Print results
    print("\n" + "=" * 48)
    print("✅ LinkedIn authorisation complete!")
    print("=" * 48)
    print(f"  Name          : {name}")
    print(f"  Person URN    : {person_urn}")
    if company_urn:
        print(f"  Company       : {company_name}")
        print(f"  Company URN   : {company_urn}")
    print(f"  Token expires : {expiry_str} (in {expires_in // 86400} days)")
    print()
    print("Add these to your .env:")
    print(f"  LINKEDIN_ACCESS_TOKEN={access_token}")
    print(f"  LINKEDIN_PERSON_URN={person_urn}")
    if company_urn:
        print(f"  LINKEDIN_COMPANY_URN={company_urn}")

    # Offer to write to .env
    print()
    answer = input("Write LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN, and LINKEDIN_TOKEN_EXPIRES to .env? [y/N] ").strip().lower()
    if answer == "y":
        _write_to_dotenv(access_token, person_urn, expiry_str, company_urn)
    else:
        print("Skipped. Copy the values above into .env manually.")

    print()
    print(f"⚠️  Reminder: this token expires on {expiry_str}.")
    print("   Re-run this script before then to refresh it.")


if __name__ == "__main__":
    main()
