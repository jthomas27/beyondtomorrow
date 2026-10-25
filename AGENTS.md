# AGENTS.md — BeyondTomorrow.World

Project guidance for Codex. Read this before editing files or running commands.
Use this file for standing rules, `.agents/skills/` for reusable operational
workflows, and `docs/OPERATIONS.md` only for the service details a task needs.
Application-agent prompts remain in `config/prompts.yaml` and
`pipeline/definitions.py`; they configure the publication pipeline.

## Execution Preferences

- Carry out explicitly requested work without repeatedly asking for confirmation.
- Use the smallest set of checks relevant to the task.
- Do not run full test suites, browser tests, or unrelated integration checks
  unless explicitly requested or directly necessary.
- For deployments, run relevant tests, deploy, and perform one status check.
  If still building, report that status rather than repeatedly polling.
- Reuse existing approvals and approved command prefixes.
- Request additional approval only when required by platform permissions or
  when an action exceeds the user's authorised scope.
- If permission blocks progress, explain the blocker once. Do not repeatedly
  retry equivalent commands or trigger repeated approval prompts. An approval
  that was denied or cancelled is not permission to try another route.
- Keep progress updates and final responses concise.
- These preferences supersede broader verification recommendations in this
  project's documentation and skills, while preserving credential protection
  and required platform permission boundaries.

---

## Hard Rules — Read Before Touching Anything

1. **Always use `.venv`** — system Python 3.14 has SSL cert issues on macOS.
   ```bash
   source .venv/bin/activate
   .venv/bin/python -m pipeline.main status
   ```

2. **`DATABASE_URL` must use the external proxy** — `caboose.proxy.rlwy.net:21688`. Never overwrite with the Railway internal URL.

3. **Always use `httpx` for Ghost API calls** — Cloudflare blocks `urllib` and `requests` with 403 1010.

4. **Never commit `.env`** — it is gitignored. Contains all credentials.

5. **Never use `git add .` blindly** — stage files explicitly. Run `git check-ignore -v <file>` on any new file before staging.

6. **Agents never write to MySQL directly** — Ghost is the only service that touches the blog DB.

7. **Pipeline runtime directory is `pipeline/`** — the `openai-agents` SDK installs as the `agents` Python package; using `pipeline/` avoids the name clash.

8. **All model strings are bare** — `gpt-6.1-sol`, not `openai/gpt-6.1-sol`. The OpenAI API rejects the `openai/` prefix.

9. **Never print or log secret values** — do not echo, print, or include in command output: API keys, passwords, tokens, or the full `DATABASE_URL`. Reference them by variable name only (e.g. `$OPENAI_API_KEY`). If a command would reveal a secret in its output, mask it or skip the output entirely.

---

## Where work belongs

- `pipeline/`: application runtime; keep the established CLI/daemon entry points.
- `pipeline/workflows/`: workflow logic; `pipeline/integrations/`: service clients.
- `config/`: runtime model, prompt, source and budget settings.
- `.agents/skills/`: project-specific Codex skills, tracked with the repository.
- `scripts/`: reusable commands called by skills, CI or maintainers.
- `infra/`: service inventory, explicit PostgreSQL migrations and release runbooks.
- `tests/`: focused offline checks and explicitly marked live checks.
- `docs/`: maintained human references; `archive/`: historical material.
- `.github/workflows/`: GitHub Actions automation, independent of the coding assistant.

Use `.venv/bin/python -m pipeline.main --dry-run "BLOG: test topic"` for an offline
CLI smoke check. Choose tests for the changed component. PostgreSQL pool startup
performs no schema writes; use the explicit migration command only within an
authorised schema task. Source changes require no live publication/email test.

## Codex skills

Read a skill when the user's task matches it; do not preload all skill bodies or
run every procedure as a checklist. Natural-language requests work; `$skill-name`
selects a skill explicitly. Existing authorisation is not a reason to ask again.

| Skill | Purpose |
| --- | --- |
| [github-push](.agents/skills/github-push/SKILL.md) | Requested commits and pushes |
| [index-reports](.agents/skills/index-reports/SKILL.md) | PDF inventory/indexing |
| [query-pipeline-logs](.agents/skills/query-pipeline-logs/SKILL.md) | Read pipeline outcomes |
| [service-auth](.agents/skills/service-auth/SKILL.md) | Task-specific credential diagnostics |
| [refresh-linkedin-token](.agents/skills/refresh-linkedin-token/SKILL.md) | Requested OAuth refresh |
| [deploy-worker](.agents/skills/deploy-worker/SKILL.md) | Worker releases with one status check |

See `docs/CODEX_WORKFLOW.md` for workspace layout and `docs/SKILLS.md` for examples.
Personal Codex preferences remain in the user's own configuration; never put
credentials in project instruction files, skills or shared Codex settings.

## Authorised Ghost/MySQL recovery exception — 24 October 2026

The user explicitly approved the migration described in
`ghost-migration-validation-2026-10-24.md`, including a narrow exception to
Hard Rule 6: direct writes for an isolated MySQL 8 restore/validation and
coordinated database credential changes are authorised for this recovery.
Preserve the original MySQL 9 data. Validate the replacement before production
cutover. This does not authorise unrelated database writes.
Do not ask the user to reconfirm this scope. Platform permission boundaries
and credential protection still apply.
