# Maintenance scripts

The application runtime is `pipeline/`. Keep reusable operational helpers here;
historical one-off repairs and diagnostics are in the private archive described
in [archive/README.md](../archive/README.md).

| Purpose | Scripts |
| --- | --- |
| Service authentication and OAuth | `auth_check.py`, `linkedin_auth.py` |
| Pipeline history | `query_logs.py` |
| Document indexing and current-model reindexing | `batch_index_reports.py`, `migrate_embeddings.py` |
| Ghost publishing and theme maintenance | `build_theme.py`, `deploy_ghost_theme.py`, `setup-ghost-api.js`, `publish_ghost_draft.py`, `upload_image.py` |
| Retained email job recovery | `retry_email_job.py` (lists by default; `--retry ID` requeues explicitly) |
| Safe Railway inventory | `railway_variables.py` (names and set/empty state only) |
| Tags and content maintenance | `tag_existing_posts.py`, `backfill_nav_tags.py`, `clean_research_file.py`, `delete_ghost_post.py` |
| Security indicator review | `secure_ghost_articles.py` (read-only unless `--apply` is supplied) |
| CI notifications and topic selection | `notify_pipeline_result.py`, `notify_research_failure.py`, `pick_research_topics.py` |
| Deployment assets and model probes | `restore_release_assets.py`, `validate_model_migration.py` |

Obsolete raw-value Railway helpers and direct database/384-dimensional schema
scripts are preserved under `archive/reference/maintenance/2026-10-25/`. Do not
rerun them. `inject-code.js` is only a compatibility wrapper for the Python theme
deployer. See [theme/README.md](../theme/README.md) and [infra/README.md](../infra/README.md).

Moving old files and clearing caches does not change a running Railway service.
