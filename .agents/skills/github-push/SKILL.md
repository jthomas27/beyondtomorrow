---
name: github-push
description: "Commit and push explicitly requested repository changes to origin/main with reviewed staging and credential protection."
---

Run commands from the repository root using `.venv/bin/python`. Follow `AGENTS.md`; reuse established task authorisation and service access.

# Push repository changes

Commit and push when the user requests it; ordinary edits alone do not request a push.
Review the diff and stage the requested change with explicit file paths. Maintained
scripts/tests/docs are tracked; private archives, logs, reports, research, credentials
and dependency folders remain excluded.

Check unfamiliar/new files with `git check-ignore -q -- path` (zero means ignored).
With verbose output, a pattern starting `!` is an exclusion override, not an ignored
file. Do not force-add an ignored file without explicit user authorisation.

Use a conventional commit subject under 72 characters and a heredoc for its body.
Push to `origin/main` unless the user specifies otherwise. Do not force push.
On non-fast-forward rejection, pull with rebase, resolve relevant conflicts and push.
If authentication or a permission review rejects the action, report the blocker once.
Git's existing credential helper and the GitHub CLI can have different access;
use the required service capability rather than requiring unrelated CLI admin access.

Pushing main can trigger the connected Railway worker. For an authorised release,
coordinate schema readiness and deployment using `infra/README.md`. Do not silently
change source connections or trigger a second deployment for an already-started release.
Return the commit hash and push outcome; never claim a running deployment from a push alone.
