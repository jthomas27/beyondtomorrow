"""
scripts/auth_check.py — Verify credentials for all BeyondTomorrow.World services.

Usage:
    python3 scripts/auth_check.py            # check all services
    python3 scripts/auth_check.py railway    # check one service
    python3 scripts/auth_check.py ghost
    python3 scripts/auth_check.py hostinger
    python3 scripts/auth_check.py github

Credentials are loaded exclusively from .env at the project root.
Nothing is hardcoded. Values are never printed in full.
"""

from __future__ import annotations

import imaplib
import json
import os
import smtplib
import sys
import time
from pathlib import Path

# ── Credential loader ────────────────────────────────────────────────────────

def load_env() -> None:
    """Load .env from project root into os.environ (does not overwrite existing vars)."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def require(key: str) -> str:
    """Return env var value or raise with a helpful message."""
    val = os.environ.get(key)
    if not val:
        raise ValueError(f"{key} is not set. Add it to your .env file.")
    return val


def mask(value: str) -> str:
    """Report presence without exposing any part of a credential."""
    return "[set]" if value else "[missing]"


# ── Result tracking ──────────────────────────────────────────────────────────

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
results: list[tuple[str, bool, str]] = []


def record(service: str, ok: bool, detail: str) -> None:
    results.append((service, ok, detail))
    icon = PASS if ok else FAIL
    print(f"  {icon}  {service:<22} {detail}")


# ── Service checks ───────────────────────────────────────────────────────────

def check_railway() -> None:
    """Verify Railway access with the CLI; never print account/credential output."""
    import subprocess
    env = os.environ.copy()
    if env.get("RAILWAY_API_TOKEN"):
        env.pop("RAILWAY_TOKEN", None)
    try:
        result = subprocess.run(["railway", "status", "--json"], env=env,
                                capture_output=True, text=True, timeout=30)
        # A refreshed browser login must remain usable when an old personal token
        # is still present in .env. Do not modify the user's credential file.
        if result.returncode != 0 and env.get("RAILWAY_API_TOKEN"):
            session_env = env.copy()
            session_env.pop("RAILWAY_API_TOKEN", None)
            session_env.pop("RAILWAY_TOKEN", None)
            result = subprocess.run(["railway", "status", "--json"], env=session_env,
                                    capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            record("Railway", True, "CLI project access confirmed")
            return
        diagnostic = (result.stdout + result.stderr).lower()
        if any(word in diagnostic for word in ("unauthor", "login", "log in", "token")):
            detail = "CLI authentication rejected; refresh RAILWAY_API_TOKEN or run railway login"
        elif any(word in diagnostic for word in ("connect", "dns", "resolve", "request")):
            detail = "CLI network connection failed"
        else:
            detail = "CLI project check failed; check railway link"
        record("Railway", False, detail)
    except FileNotFoundError:
        record("Railway", False, "Railway CLI not installed")
    except subprocess.TimeoutExpired:
        record("Railway", False, "CLI check timed out")


def check_ghost() -> None:
    """Verify Ghost Admin API using a fresh JWT."""
    try:
        import httpx
        import hmac
        import hashlib
        import struct
    except ImportError:
        record("Ghost", False, "httpx not installed — run: pip install httpx")
        return

    try:
        ghost_url = require("GHOST_URL")
        admin_key = require("GHOST_ADMIN_KEY")
        key_id, secret = admin_key.split(":", 1)

        iat = int(time.time())
        header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
        payload = {"iat": iat, "exp": iat + 300, "aud": "/admin/"}

        import base64

        def b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        h = b64url(json.dumps(header, separators=(",", ":")).encode())
        p = b64url(json.dumps(payload, separators=(",", ":")).encode())
        sig_input = f"{h}.{p}".encode()
        sig = hmac.new(bytes.fromhex(secret), sig_input, hashlib.sha256).digest()
        token = f"{h}.{p}.{b64url(sig)}"

        url = f"{ghost_url.rstrip('/')}/ghost/api/admin/site/"
        last_err = ""
        for attempt in range(3):
            try:
                r = httpx.get(
                    url,
                    headers={"Authorization": f"Ghost {token}"},
                    timeout=20,
                )
                if r.status_code == 200:
                    version = r.json().get("site", {}).get("version", "unknown")
                    record("Ghost", True, f"Ghost v{version} at {ghost_url}  (key: {mask(admin_key)})")
                    return
                elif r.status_code in (530, 521, 523, 524):
                    last_err = f"HTTP {r.status_code} — Railway Ghost service is down or starting up; restart it at railway.app"
                elif r.status_code == 401:
                    last_err = f"HTTP 401 — GHOST_ADMIN_KEY is wrong or expired"
                    break  # no point retrying auth failures
                else:
                    last_err = f"HTTP {r.status_code} — check GHOST_ADMIN_KEY"
                    break
            except Exception as e:
                last_err = f"timeout/connection error (attempt {attempt+1}/3): {e}"
            if attempt < 2:
                time.sleep(5)
        record("Ghost", False, last_err)
    except ValueError as e:
        record("Ghost", False, str(e))
    except Exception as e:
        record("Ghost", False, f"connection error: {e}")


def check_hostinger() -> None:
    """Verify Hostinger IMAP and SMTP credentials."""
    # IMAP
    try:
        host = os.environ.get("EMAIL_HOST", "imap.hostinger.com")
        port = int(os.environ.get("EMAIL_PORT", "993"))
        user = require("EMAIL_USER")
        password = require("EMAIL_PASS")

        conn = imaplib.IMAP4_SSL(host, port)
        conn.login(user, password)
        conn.logout()
        record("Hostinger IMAP", True, f"{user} @ {host}:{port}")
    except ValueError as e:
        record("Hostinger IMAP", False, str(e))
    except Exception as e:
        record("Hostinger IMAP", False, f"auth failed: {e}")

    # SMTP
    try:
        smtp_host = os.environ.get("SMTP_HOST", "smtp.hostinger.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER") or require("EMAIL_USER")
        smtp_pass = os.environ.get("SMTP_PASS") or require("EMAIL_PASS")

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
        record("Hostinger SMTP", True, f"{smtp_user} @ {smtp_host}:{smtp_port}")
    except ValueError as e:
        record("Hostinger SMTP", False, str(e))
    except Exception as e:
        record("Hostinger SMTP", False, f"auth failed: {e}")


def check_github() -> None:
    """Verify GitHub token has models:read scope."""
    try:
        import httpx
    except ImportError:
        record("GitHub Models", False, "httpx not installed — run: pip install httpx")
        return

    try:
        token = require("GITHUB_TOKEN")
        # Probe the GitHub Models API
        r = httpx.get(
            "https://models.github.ai/v1/models",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            body = r.json()
            # Response may be {"data": [...]} or a plain list
            model_list = body.get("data", body) if isinstance(body, dict) else body
            count = len(model_list) if isinstance(model_list, list) else "?"
            record("GitHub Models", True, f"{count} models available  (token: {mask(token)})")
        elif r.status_code == 401:
            record("GitHub Models", False, "token invalid or expired — regenerate at github.com/settings/tokens")
        elif r.status_code == 403:
            record("GitHub Models", False, "token lacks models:read scope — update scopes at github.com/settings/tokens")
        else:
            record("GitHub Models", False, f"HTTP {r.status_code}")
    except ValueError as e:
        record("GitHub Models", False, str(e))
    except Exception as e:
        record("GitHub Models", False, f"connection error: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

CHECKS = {
    "railway": check_railway,
    "ghost": check_ghost,
    "hostinger": check_hostinger,
    "github": check_github,
}

def main() -> None:
    load_env()

    targets = [a.lower() for a in sys.argv[1:]] if len(sys.argv) > 1 else []

    for t in targets:
        if t not in CHECKS:
            print(f"Unknown service '{t}'. Valid: {', '.join(CHECKS)}")
            sys.exit(1)

    services = {k: CHECKS[k] for k in targets} if targets else CHECKS

    print(f"\nBeyondTomorrow.World — Service Auth Check\n{'─' * 50}")
    for fn in services.values():
        fn()

    print(f"{'─' * 50}")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  {passed}/{total} checks passed\n")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
