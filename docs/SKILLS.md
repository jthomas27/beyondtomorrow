# Skills Guide — BeyondTomorrow.World

This guide explains how to call operational skills and what each skill does.

## How to call a skill

Use this structure in a single message:

- Trigger: "Use skill: <Skill Name> — ..."
- Objective: What outcome you want
- Inputs: Exact files/paths, IDs, URLs, dates, limits
- Constraints: e.g., no publish, LinkedIn only, dry-run, skip newsletter
- Output: What you want returned (URL, share URN, log snippet, confirmation)

Example

- Use skill: LinkedIn Post — Personal
  - Source: latest published Ghost post
  - Do not republish to Ghost
  - Return: LinkedIn share URN

## Skill catalog

### Core publishing and distribution

- Run BLOG Pipeline
  - Research → Write → Edit → Publish → LinkedIn → Newsletter → Index (end-to-end).

- Publish Only
  - Publish an already-edited file to Ghost.
  - Optional flags: skip LinkedIn, skip newsletter.

- LinkedIn Post — Personal
  - Post a Ghost article card to the personal LinkedIn profile.
  - Inputs: title/excerpt/url (or "latest Ghost post").

- LinkedIn Post — Company
  - Post to a company page (requires LINKEDIN_COMPANY_URN).

### Research and indexing

- Research Only
  - Run the research agent; stores findings in the corpus, no Ghost publish.

- Report (Research Report)
  - Extended research deliverable; indexes results to corpus, no publish.

- Index Document
  - Chunk and embed a local text/Markdown document into the corpus.

- Index PDF Reports
  - Batch or single-PDF indexing into the corpus.

### Quality, checks, and logs

- Status Check
  - Verify environment variables, DB connectivity, Ghost/LinkedIn reachability.

- Query Pipeline Logs
  - Show recent runs, failures, or published URLs from the pipeline_logs table.

- Railway Logs
  - Tail or fetch recent logs from Ghost or the email-worker services.

- Service Authentication Check
  - Validate credentials for Railway, Ghost, Hostinger, LinkedIn (locally).

### Repo and ops

- Push to GitHub
  - Stage explicit files, commit with a conventional message, push to main.

## Ready-to-use requests (copy/paste)

1) LinkedIn personal (latest Ghost post)

- Use skill: LinkedIn Post — Personal
  - Source: latest published post on Ghost
  - Do not republish to Ghost, just cross-post
  - Return: LinkedIn share URN

2) Pipeline logs (published)

- Use skill: Query Pipeline Logs — published
  - Window: last 2 days
  - Limit: 10
  - Return: URL, feature image, LinkedIn status, newsletter status

3) Railway logs (Ghost)

- Use skill: Railway Logs
  - Service: ghost (0daf496c-e14f-41d4-b89b-3624a778c99d)
  - Environment: production (c9dfebe4-097a-4151-be37-2b1fcd414e74)
  - Lines: 200
  - Filter: @level:error OR @level:warn
  - Return: any errors with timestamps and brief explanation

4) Publish an edited file only

- Use skill: Publish Only
  - File: /Users/jeremiah/Projects/BeyondTomorrow.World/research/YYYY-MM-DD-slug-edited.md
  - Flags: no LinkedIn, no newsletter
  - Return: Ghost URL

5) Push to GitHub

- Use skill: Push to GitHub
  - Files: /abs/path1 /abs/path2
  - Commit: feat: tighten & remove Sources section
    - Normalize dates, remove Sources, keep inline links
  - Branch: main
  - Return: last commit (oneline)

## Notes and gotchas

- Always use absolute paths when providing file names.
- For Publish Only, provide the filename relative to the research directory (e.g., `2026-08-16-deep-dive-into-the-edited.md`) or an absolute path. Avoid prefixing with `research/` if you’re already passing the file within that folder to prevent duplicated paths.
- LinkedIn tokens expire ~60 days after issue. If you see warnings in Railway logs about imminent expiry, run `scripts/linkedin_auth.py` locally and update Railway service variables.
- Site policy: allow inline references but never add a "Sources" section. The pipeline strips any "## Sources" blocks during save.
- Ghost SEO guardrails: custom excerpt must be ≤ 300 chars; meta_title ≤ 60 chars.
- Formatting: every post must end with a "Just For Laughs" section.
