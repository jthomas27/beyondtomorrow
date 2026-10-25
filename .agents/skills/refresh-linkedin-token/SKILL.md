---
name: refresh-linkedin-token
description: "Refresh LinkedIn OAuth credentials when explicitly requested or when an authorised repair requires resolving an expired or rejected token."
---

Run commands from the repository root using `.venv/bin/python`. Follow `AGENTS.md`; reuse established task authorisation and service access.

# Refresh LinkedIn OAuth

Confirm the task authorises refreshing credentials; a status question alone is
read-only. Use the local `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` without
printing them. Run:

```bash
.venv/bin/python scripts/linkedin_auth.py
```

The helper opens the browser for provider authorisation. If the caller requested
refreshing the token, accepting its local-save prompt is already within that scope;
do not ask the user to reconfirm saving .env. Provider consent and sandbox approvals
remain real permission boundaries. Do not bypass a rejected authorisation.

Verify identity read-only after saving; `scripts/auth_check.py linkedin` is not a
supported command. Report the saved expiry date and the verification result,
never the credential. Use the expiry returned by the helper rather than assuming
an exact lifetime.

When the user requested a production repair, sync the refreshed token, person URN,
expiry and any applicable company URN to the email-worker without exposing values.
Coordinate one worker deployment and one status check if required. Do not post a
LinkedIn test, republish a Ghost article or send a newsletter to verify a refresh.
