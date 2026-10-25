# BeyondTomorrow.World agent guidance

Read [AGENTS.md](../AGENTS.md) before editing files or running commands. It is
the authoritative source for execution preferences, credential protection,
service access and current model assignments. User instructions take precedence.

Use [README.md](../README.md) for current setup and CLI commands,
[docs/CODEBASE_STRUCTURE.md](../docs/CODEBASE_STRUCTURE.md) for module ownership,
and [infra/README.md](../infra/README.md) for releases and schema migrations.

Keep the runtime package named `pipeline/`; the installed SDK owns `agents`.
Use `.venv`, run only relevant checks, and stage files explicitly. Secrets,
private archives, research outputs, reports and logs remain local/ignored.
Do not print credentials. Live publications, emails, database migrations and
deployments are separate actions from offline code validation.
