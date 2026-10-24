# BeyondTomorrow.World

A Ghost publication with a Python research, writing and publishing pipeline.

The Python application lives in `pipeline/`; Ghost and MySQL run as separate
Railway services. The pipeline uses OpenAI directly and PostgreSQL/pgvector for
its knowledge corpus. Ghost 6.72.0 and MySQL 8.4.13 were verified during the
October 2026 upgrade; see the migration record for operational evidence.

## Setup

Python 3.11 is the declared project/CI target. Always use the project `.venv`.
An existing environment is not recreated by a source-code refactor.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Fill `.env` locally. Required pipeline credentials are `OPENAI_API_KEY`,
`DATABASE_URL`, `GHOST_URL` and `GHOST_ADMIN_KEY`. Email polling also needs
`EMAIL_USER` and `EMAIL_PASS`. Newsletter delivery uses `RESEND_API_KEY`;
LinkedIn posting requires its separate OAuth credentials. Never commit secrets.

Retain the configured external PostgreSQL proxy
`caboose.proxy.rlwy.net:21688`. Do not replace it with a Railway internal URL.
For a fresh PostgreSQL database, review and explicitly apply the schema:

```bash
.venv/bin/python -m pipeline.storage.migrate
.venv/bin/python -m pipeline.storage.migrate --apply
```

The default command only lists migration files; `--apply` writes. Existing
incompatible schemas require a reviewed migration, not an automatic reset.
Ghost manages its own MySQL schema; the PostgreSQL command never touches it.

## Commands

```bash
.venv/bin/python -m pipeline.main --dry-run "BLOG: a topic"
.venv/bin/python -m pipeline.main "BLOG: a topic"
.venv/bin/python -m pipeline.main "RESEARCH: a topic"
.venv/bin/python -m pipeline.main "REPORT: a topic"
.venv/bin/python -m pipeline.main "INDEX: reports/document.pdf"
.venv/bin/python -m pipeline.main "PUBLISH: an-edited-article.md"
.venv/bin/python -m pipeline.email_listener
```

Commands without `--dry-run` can call paid APIs, change stored data, publish
articles or send configured emails. `python -m pipeline.cli` is an equivalent
CLI; the established `pipeline.main` entry point remains supported.

## Development

Run tests for the component being changed, for example:

```bash
.venv/bin/python -m pytest tests/test_model_migration.py tests/test_ghost.py -m "not integration"
```

Unit tests block accidental live HTTP. Live database, browser and publication
checks are separate operations; they are not prerequisites for every edit.
CI uses Python 3.11. The scheduled research workflow requires an
`OPENAI_API_KEY` GitHub Actions secret plus its configured service secrets.
Dependency installation remains requirements-based; no new package manager
or dependency upgrade is required for this restructure.

## Project guide

- [Architecture and module ownership](docs/CODEBASE_STRUCTURE.md)
- [Deployment, schema migrations and rollback](infra/README.md)
- [Service inventory](infra/services.json)
- [Operational rules](AGENTS.md)
- [Maintenance scripts](scripts/README.md)
- [Historical notes and private archive](archive/README.md)

Keep application code, tests, operational scripts and current documentation in
version control. Generated `logs/`, `research/`, `reports/`, dependency folders,
credentials and `archive/local/` remain ignored. Source-control changes should
always stage explicitly reviewed files.

Incident handoff notes and credential-bearing rollback evidence remain local.
Use the maintained infrastructure runbook for release procedures.
