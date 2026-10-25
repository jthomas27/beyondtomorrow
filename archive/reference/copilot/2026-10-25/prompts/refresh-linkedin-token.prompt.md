---
description: "Refresh the LinkedIn OAuth access token. Use when: LinkedIn publishing fails with 401, token is expired or expiring soon, or after re-running linkedin_auth.py."
name: "Refresh LinkedIn Token"
argument-hint: "Optional: describe the issue (e.g. '401 error', 'token expiring')"
agent: "agent"
---

Run the LinkedIn OAuth refresh flow and verify the new token works.

## Steps

1. Run the OAuth flow to get a new token:
   ```bash
   .venv/bin/python scripts/linkedin_auth.py
   ```
   This opens a browser for OAuth authorization and saves `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN`, and `LINKEDIN_TOKEN_EXPIRES` to `.env`.

2. After the script completes, verify the new token by running the auth check:
   ```bash
   source .venv/bin/activate && python3 scripts/auth_check.py linkedin
   ```

3. Report the new token expiry date from `LINKEDIN_TOKEN_EXPIRES` in `.env` and confirm the check passed.

> **Note**: `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` must already be set in `.env`. The token is valid for 60 days.
