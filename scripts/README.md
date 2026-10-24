# Maintenance scripts

The application runtime is `pipeline/`. Keep reusable operational helpers here;
historical one-off repairs and diagnostics are in the private archive described
in [archive/README.md](../archive/README.md).

| Purpose | Scripts |
| --- | --- |
| Service authentication and OAuth | `auth_check.py`, `linkedin_auth.py` |
| Pipeline history | `query_logs.py` |
| Document indexing and current-model reindexing | `batch_index_reports.py`, `migrate_embeddings.py` |
| Ghost publishing and theme maintenance | `inject-code.js`, `setup-ghost-api.js`, `publish_ghost_draft.py`, `publish_test_post.py`, `upload_image.py` |
| Tags and content maintenance | `tag_existing_posts.py`, `backfill_nav_tags.py`, `clean_research_file.py`, `delete_ghost_post.py` |
| Security indicator review | `secure_ghost_articles.py` (read-only unless `--apply` is supplied) |
| CI notifications and topic selection | `notify_pipeline_result.py`, `notify_research_failure.py`, `pick_research_topics.py` |
| Deployment assets and model probes | `restore_release_assets.py`, `validate_model_migration.py` |

Other database/Railway helpers remain because package commands or existing
guides reference them. Their presence does not mean old schema migrations
should be rerun. Follow `AGENTS.md` before accessing any service.

Moving old files and clearing caches does not change a running Railway service.
