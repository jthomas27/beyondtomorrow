# Codex workspace

Codex uses the root AGENTS.md for persistent project guidance and discovers
repository skills under `.agents/skills/`. This follows the [official Codex
customisation guide](https://learn.chatgpt.com/docs/customization/overview) and
[skill discovery documentation](https://learn.chatgpt.com/docs/build-skills).

```text
AGENTS.md                  standing project rules and routing
.agents/skills/            reusable Codex workflows and on-demand references
.github/workflows/        CI and scheduled GitHub Actions
pipeline/                 publication application
config/prompts.yaml       publication-agent prompt overrides
scripts/                  reusable operational helpers
infra/                    deployment and schema procedures
docs/OPERATIONS.md        service reference, loaded when needed
archive/reference/copilot/ historical editor material
```

## Work with Codex

Open the repository root as the workspace. Ask for an outcome in natural
language, or explicitly select a skill, for example:

- `$query-pipeline-logs show the last five failures`
- `$index-reports show PDFs not yet indexed; do not index them`
- `$github-push commit and push the requested changes`
- `$refresh-linkedin-token refresh the expired production token`
- `$deploy-worker deploy these changes using the relevant tests already passed`

Skills retain automatic selection. Their names/descriptions are discoverable;
Codex loads the body/references for the selected workflow. If the skills list
has not updated after adding them, reopen the Codex session.

Keep commands in maintained scripts and detailed service information in its
reference/runbook. Avoid copying the same procedure into AGENTS.md, skill text
and editor-specific instructions. Skills follow user authorisation; invoking one
does not request unrelated publications, credential rotations or deployments.

## User settings and project files

Project skills travel with the Git repository. Personal Codex settings belong
in the user's Codex setup (for example `~/.codex/config.toml` and global
`~/.codex/AGENTS.md`); skills shared across projects can live in
`~/.agents/skills/`. Existing installation-provided system skills are left intact.
This migration does not change personal settings, sandbox permissions, approvals
or the user's selected Codex model. A project `.codex/config.toml` is unnecessary
until there is a concrete project-specific setting to share.

The application models in `config/models.yaml` are separate from the model used
to edit this repository. Application agent prompts remain in their runtime
configuration; the LinkedIn editor prompt became a real project skill.

## Preserved material

Four existing skills were adapted for Codex. The LinkedIn refresh prompt became
a fifth, and the repeatable worker release procedure became a sixth. Originals
and obsolete Copilot/Cline setup guides are archived under
`archive/reference/copilot/2026-10-25/`. Their old instructions are historical.
GitHub Actions remain in use for CI/scheduled pipeline work.

## Update and release workflow

Use the GitHub push skill for requested commits and pushes: review pending
changes, check new files against ignore rules, stage explicit paths, commit and
push to `main`. Credentials, generated research, delivery logs and private
backups stay local. Keep preserved historical instructions under `archive/`.

For application releases, reuse the affected tests already passed and apply
only pending, authorised migrations after a backup. Pushing `main` can trigger
the connected Railway worker; avoid a second manual deployment. Check its
status once and report the actual state, including a pending build.

Email jobs and delivery recovery follow [DELIVERY_RECOVERY.md](DELIVERY_RECOVERY.md).
Ghost appearance has a separate [build and deployment workflow](../theme/README.md):
edit `theme/src/`, rebuild the injection artifacts, and deploy with a private
rollback copy. A worker deployment alone does not apply Ghost appearance settings.
