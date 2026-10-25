---
name: deploy-worker
description: "Release authorised pipeline changes to Railway email-worker, including relevant validation, schema readiness, source deployment and one final status check."
---

Run commands from the repository root using `.venv/bin/python`. Follow `AGENTS.md`; reuse established task authorisation and service access.

# Deploy the publishing worker

Use `infra/README.md`, `infra/services.json` and `railway.toml` for the maintained
release procedure. Deploy the Python email-worker; a code release does not imply
upgrading Ghost/MySQL or changing their credentials.

Use relevant tests already passed for unchanged code. Do not repeat full suites,
browser checks, API probes or CI watches when they are not needed. A user request
to proceed without optional checks takes precedence. Keep required credential and
platform boundaries intact.

Preview/apply PostgreSQL migrations only when the release needs them and the task
authorises writes. Do not reapply a confirmed baseline merely to check it.
Preserve the configured external proxy and use the explicit migration runner.

The worker is connected to GitHub main: a push can already trigger deployment.
Choose one deployment path and avoid immediate redundant redeploys. Do not detach
service sources as a routine prerequisite. Inspect/fix a failed build only when
new evidence requires it; preserve the current working release when possible.

After deploying, perform one status check. If queued/building/deploying, report
that state and stop polling unless monitoring was requested. Do not claim startup
or database connectivity until observed. Do not send test publications/emails.
Return the commit/deployment ID, actual status and material pending work.
