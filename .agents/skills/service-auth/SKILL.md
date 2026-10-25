---
name: service-auth
description: "Diagnose credentials for the specific Ghost, Railway, mailbox, GitHub or LinkedIn operation being requested without printing secrets or rotating unrelated keys."
---

Run commands from the repository root using `.venv/bin/python`. Follow `AGENTS.md`; reuse established task authorisation and service access.

# Service authentication

Check only the service needed and reuse access already verified in the active task.
Available checks are:

```bash
.venv/bin/python scripts/auth_check.py ghost
.venv/bin/python scripts/auth_check.py railway
.venv/bin/python scripts/auth_check.py hostinger
```

`hostinger` checks IMAP and SMTP. The script's `github` mode probes the legacy
GitHub Models service; it is not a repository push/Actions permission check.
For repository operations use the applicable Git credential helper or GitHub CLI
capability. Do not block a Git push merely because unrelated API administration
is unavailable. `linkedin` is not currently a supported auth_check.py argument.

For LinkedIn, read the current expiry locally and use the existing user-info helper
or a read-only userinfo request with a bearer header. A successful identity probe
does not prove posting scopes. Token refresh is a separate requested operation;
use the refresh-linkedin-token skill when needed.

Railway uses its CLI, not direct GraphQL. Personal tokens use `RAILWAY_API_TOKEN`;
`RAILWAY_TOKEN` is for project tokens. A confirmed CLI browser login may remain
usable when a legacy environment token is stale. Do not change credential files
or repeatedly retry rejected authentication without an authorised fix.

Never emit tokens, passwords, JWTs, full database URLs or raw variable listings.
Use `httpx` for Ghost; generate fresh Admin JWTs. Custom integration keys cannot
perform every staff settings operation; inspect `scripts/inject-code.js` for the
existing staff-session method when a settings operation is authorised.

The runtime uses `OPENAI_API_KEY`; GitHub Models credentials are not its substitute.
Credential rotation must update the actual consumer and all authorised saved
copies. Update only relevant services; never copy worker secrets into Ghost by default.
