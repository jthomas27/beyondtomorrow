# Codex skill catalog

Project skills live in `.agents/skills/`. Use ordinary requests or the explicit
`$skill-name` syntax. Read [the Codex workspace guide](CODEX_WORKFLOW.md) for setup.

| Skill | Example request |
| --- | --- |
| [github-push](../.agents/skills/github-push/SKILL.md) | `$github-push commit and push the reviewed change` |
| [index-reports](../.agents/skills/index-reports/SKILL.md) | `$index-reports check pending PDFs without indexing` |
| [query-pipeline-logs](../.agents/skills/query-pipeline-logs/SKILL.md) | `$query-pipeline-logs show the latest published URLs` |
| [service-auth](../.agents/skills/service-auth/SKILL.md) | `$service-auth diagnose Ghost authentication` |
| [refresh-linkedin-token](../.agents/skills/refresh-linkedin-token/SKILL.md) | `$refresh-linkedin-token refresh the expired token` |
| [deploy-worker](../.agents/skills/deploy-worker/SKILL.md) | `$deploy-worker release the current authorised changes` |

These are the actual installed project workflows. Pipeline commands such as
BLOG:, RESEARCH: and PUBLISH: remain application commands documented in README.md.
A history/status request does not authorise replaying jobs or sending messages.
Existing user approval for a requested operation persists across its steps;
platform permission and provider-consent boundaries still apply.
