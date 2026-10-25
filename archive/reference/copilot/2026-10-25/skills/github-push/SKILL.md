---
name: github-push
description: "Push files to GitHub. Use when: committing and pushing changes, staging modified or new files, writing a commit message, pushing to origin/main, or after completing a code change that should be saved to the remote repository."
argument-hint: "Optional: commit message (e.g. 'feat: add LinkedIn tool'). If omitted, a message will be inferred from the staged changes."
---

# GitHub Push

Stages, commits, and pushes changes to `origin/main` in one clean sequence.

## Procedure

### Step 1 — Review what's changed

```bash
git status
git diff --stat HEAD
```

Check:
- **Modified** files: code changes to commit
- **Untracked** files: new files that may need staging
- **Deleted** files: removals that need staging
- Any files that should NOT be committed (check `.gitignore`)

### Step 2 — Check `.gitignore` before staging

Before staging any file, verify it is not excluded by `.gitignore`:

```bash
git check-ignore -v <file>
```

- If the command returns output, the file is ignored — **do NOT stage it** unless you have an explicit reason and user approval to force-add it with `git add -f`.
- If it returns nothing, the file is safe to stage normally.

For new files in directories that may be blanket-ignored (e.g. `scripts/`, `logs/`, `reports/`), always run this check first.

Stage everything relevant:
```bash
git add <files...>
```

Do NOT stage:
- `.env` or any file containing credentials
- `research/`, `reports/`, `logs/` — runtime/output directories (gitignored)
- `scripts/` — gitignored by default in this project; individual files may be tracked via force-add, but only when explicitly requested
- `__pycache__/`, `.venv/`, `.DS_Store`

To verify what's staged:
```bash
git status
```

### Step 3 — Commit

Use a heredoc to avoid shell quoting issues with long messages:

```bash
git commit -F - << 'EOF'
<type>: <short summary>

- <detail line 1>
- <detail line 2>
EOF
```

**Commit message conventions:**

| Prefix | When to use |
|---|---|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `refactor:` | Code restructure, no behaviour change |
| `test:` | Adding or updating tests |
| `chore:` | Tooling, deps, config, gitignore |

Keep the subject line under 72 characters. Body lines optional for trivial changes.

### Step 4 — Push

```bash
git push origin main
```

Verify the push succeeded:
```bash
git log --oneline -1
```

The commit hash should appear on both `HEAD -> main` and `origin/main`.

## Fix Failures

| Error | Fix |
|---|---|
| `rejected — non-fast-forward` | Run `git pull --rebase origin main` then push again |
| `Authentication failed` | Check `GITHUB_TOKEN` in `.env`; or re-run `gh auth login` |
| `dquote>` / `heredoc>` shell stuck | Shell is waiting for closing quote — press Ctrl+C, then use the heredoc `<< 'EOF'` form |
| Nothing to commit | All changes are already committed — verify with `git log --oneline -3` |
| File not showing as staged | Check `.gitignore` — the file may be explicitly excluded |

## Rules

- **Never commit `.env`** — always in `.gitignore`; verify before `git add .`
- **Never use `git add .` blindly** — stage files explicitly to avoid committing secrets or large binaries
- **Check `.gitignore` before staging** — run `git check-ignore -v <file>` on any new or unfamiliar file; if it is ignored, do not force-add without explicit user instruction
- **Branch**: always push to `main` unless the user specifies otherwise
- **No force push** — do not use `--force` or `--force-with-lease` without explicit user instruction
