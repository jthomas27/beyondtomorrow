
# Agent workflow — ✅ Complete

1. ✅ Create a GitHub Personal Access Token (PAT)

   a. Go to [github.com](https://github.com) and sign in.
   b. Click your **profile photo** (top-right corner) → **Settings**.
   c. In the left sidebar, scroll to the bottom → click **Developer settings**.
   d. Click **Personal access tokens** → **Fine-grained tokens**.
   e. Click **Generate new token** (top-right).
   f. Fill in the form:
      - **Token name:** `beyondtomorrow-models` (or anything memorable)
      - **Expiration:** choose how long you want it valid (90 days is a safe default)
      - **Resource owner:** your GitHub username
      - **Repository access:** "Public Repositories (read-only)" is fine
      - **Permissions → Account permissions:** scroll to **Models** → set to **Read**
   g. Click **Generate token** at the bottom.
   h. **Copy the token immediately** — GitHub only shows it once. Save it somewhere safe (e.g. a password manager).

2. ✅ Set secrets in Railway and GitHub Actions

   **Part A — Railway** (you need the token from step 1 and your Ghost Admin key)

   a. Go to [railway.app](https://railway.app) and open your project.
   b. Click the **beyondtomorrow** service (not the pgvector service).
   c. Click the **Variables** tab.
   d. Add each variable below using **New Variable** → type the name → paste the value → **Add**:

   | Variable | Value |
   |---|---|
   | `GITHUB_TOKEN` | the PAT you copied in step 1 |
   | `DATABASE_URL` | `postgresql://postgres:<pass>@pgvector.railway.internal:5432/railway` |
   | `GHOST_URL` | `https://beyondtomorrow.world` |
   | `GHOST_ADMIN_KEY` | see Part C below for how to get this |

   > For `DATABASE_URL`, replace `<pass>` with the pgvector password from Railway → pgvector service → Variables → `PGPASSWORD`.
   > This uses the **private** internal Railway URL — keeps traffic on Railway's private network.

   **Part B — GitHub Actions**

   a. Go to your repository on [github.com](https://github.com): `github.com/jthomas27/beyondtomorrow`.
   b. Click the **Settings** tab (top of the repo page).
   c. In the left sidebar → **Secrets and variables** → **Actions**.
   d. Click **New repository secret** for each of the following:

   | Secret name | Value |
   |---|---|
   | `AGENT_GITHUB_TOKEN` | the same PAT from step 1 |
   | `DATABASE_URL` | `postgresql://postgres:<pass>@caboose.proxy.rlwy.net:21688/railway` |
   | `GHOST_URL` | `https://beyondtomorrow.world` |
   | `GHOST_ADMIN_KEY` | same value as in Part A |

   > For GitHub Actions, `DATABASE_URL` uses the **TCP proxy** URL (external access), not the internal one.

   **Part C — Get your Ghost Admin Key** (if you don't have it yet)

   a. Go to `https://beyondtomorrow.world/ghost` and sign in.
   b. Click the **Settings** gear icon (bottom-left).
   c. Click **Integrations** → scroll to **Custom integrations** → click **Add custom integration**.
   d. Name it `beyondtomorrow-agent` → click **Create**.
   e. Copy the **Admin API key** shown — use this as `GHOST_ADMIN_KEY` in both Railway and GitHub Actions.



**Running locally** — fill in `.env` (gitignored, already created) then:
```bash
# Fill in GITHUB_TOKEN and GHOST_ADMIN_KEY in .env first, then:
python -m pipeline.main status              # verify all vars + DB connection
python -m pipeline.main "BLOG: your topic"  # run the full blog pipeline
```
> `.env` is auto-loaded by `pipeline/main.py`. Code lives in `pipeline/` (not `agents/`).
> The `openai-agents` SDK installs as the `agents` Python package — `pipeline/` avoids the clash.


# Testing and Verification

### Unit Tests

| Module | What to Test |
|---|---|
| `pipeline/setup.py` | GitHub Models client init, `set_default_openai_client` works |
| `pipeline/embeddings.py` | Model loads, produces 384-dim vectors, similarity score is correct |
| `pipeline/tools/search.py` | DuckDuckGo + Brave return results, `fetch_page` extracts text |
| `pipeline/tools/corpus.py` | `search_corpus` returns relevant chunks, `index_document` stores + deduplicates correctly |
| `pipeline/tools/ghost.py` | `publish_to_ghost` creates draft with correct metadata |
| `pipeline/tools/quality.py` | `score_credibility` returns expected domain scores |
| `pipeline/db.py` | asyncpg pool connects, `rate_limit_log` writes succeed |

### Integration Tests

| Test | What It Verifies |
|---|---|
| CLI → Research | `python -m pipeline.main "topic"` → `Runner.run()` → structured output |
| Research → Corpus | Research output chunked, embedded via `index_document`, stored in pgvector |
| Research → Blog Pipeline | `python -m pipeline.main "BLOG: topic"` → researcher → writer → editor → Ghost published post |
| Agent Handoffs | Orchestrator → researcher → writer chain completes without error |
| Agent Sessions | `agent_sessions` table records state for each agent in a run |

### Quality Checks

- Manually review 3–5 research outputs for:
  - Accuracy of findings vs. source material
  - Source citations match the provided sources
  - Confidence labels match source count/credibility
  - No hallucinated information beyond provided sources

### Cost Verification

- Run 10 research tasks over a week
- Verify $0 charged beyond existing subscriptions
- Review `rate_limit_log` table to confirm usage is within GitHub Models limits
- Confirm Brave Search usage stays under 2,000/month free tier