# Migration Plan — Cline + OpenAI API

**Goal:** Move off GitHub (Copilot + GitHub Models API) to:

1. **OpenAI API** as the pipeline's runtime LLM provider (replacing GitHub Models).
2. **Cline** (VS Code extension) as the coding assistant (replacing GitHub Copilot).

Both run on a **single `OPENAI_API_KEY`**, so one account and one bill cover the whole workflow.

---

## Summary (TL;DR)

| Item | Today | After migration |
|---|---|---|
| Pipeline LLM provider | GitHub Models (`models.github.ai`) via `GITHUB_TOKEN` | OpenAI API (`api.openai.com/v1`) via `OPENAI_API_KEY` |
| Coding assistant | GitHub Copilot (Pro+) | Cline extension (BYO key) |
| Auth secret | `GITHUB_TOKEN` | `OPENAI_API_KEY` |
| Model strings | `openai/gpt-4.1` (prefixed) | `gpt-4.1` (bare — OpenAI rejects the `openai/` prefix) |
| Editor 8k-token workarounds | Required (GitHub Models hard limit) | No longer forced (native OpenAI has generous limits) |
| Monthly cost | Copilot Pro+ **$39** (inference "free" but rate-limited) | Pipeline **~$4–17** + Cline usage **~$5–30** (Cline extension itself is free) |

**Why this is low-risk:** you stay in the **same model family** (`gpt-4.1` / `gpt-5`), so your prompts and the `_clean_llm_text` sanitiser in `pipeline/tools/files.py` remain valid. Native OpenAI also removes the GitHub Models 8,000-token request cap that forced the Editor's `max_tokens=2500` and caused the C1 / `\x1e` / `\x14` / `\x15` punctuation corruption via `gpt-4.1-mini` fallback.

---

## Cost Estimates

### Pipeline runtime (OpenAI API)


OpenAI list prices (per 1M tokens):

| Model | Input | Output |
|---|---|---|
| `gpt-4.1` | $2.00 | $8.00 |
| `gpt-4.1-mini` | $0.40 | $1.60 |
| `gpt-5` | $1.25 | $10.00 |
| `gpt-5-mini` | $0.25 | $2.00 |

| Configuration | ~ per post | ~ per month (45 runs) |
|---|---|---|
| **Conservative** — keep `gpt-4.1` for Researcher/Writer/Editor, `gpt-4.1-mini` for Orchestrator/Publisher/Indexer | ~$0.30 | **~$14** |
| **Optimised** — `gpt-4.1` for Writer/Editor only, `gpt-5-mini` for the rest | ~$0.09 | **~$4** |

> Batch API (50% cheaper) is available for non-real-time work (indexing/research), but your email-triggered publishes stay real-time, so treat batch as optional upside.

### Coding assistant (Cline)

- **Extension: free** (open-source).
- You pay only for API usage against your `OPENAI_API_KEY`. Typical solo usage: **~$5–30/month** depending on how heavily you use the agent. Highly variable — set a spend limit (see Part A, Step 4).

### Total

**~$9–47/month**, versus the flat **$39/month** Copilot Pro+ today — with the pipeline gaining proper rate limits and you gaining pay-as-you-go control.

---

## Part A — Set up OpenAI API

**Step A1 — Create/verify an OpenAI Platform account**
- Go to <https://platform.openai.com> and sign in (separate from ChatGPT consumer billing).

**Step A2 — Add billing and prepaid credits**
- Settings → Billing → add a payment method.
- Add an initial credit balance (minimum $5). This also raises you to **usage Tier 1**, which unlocks workable rate limits (well above the GitHub Models 8k cap).

**Step A3 — Create an API key**
- Settings → API keys → **Create new secret key**.
- Name it (e.g. `beyondtomorrow-pipeline`), copy the `sk-...` value once, and store it securely.

**Step A4 — Set a monthly spend limit (safety net)**
- Settings → Limits → set a **monthly budget cap** and a **usage alert** (e.g. cap $50, alert at $25). This protects against runaway Cline or pipeline usage.

**Step A5 — Record the key locally**
- Add to `.env` at the project root (gitignored):
  ```dotenv
  OPENAI_API_KEY=sk-...
  ```
- Keep `GITHUB_TOKEN` in place until the pipeline migration (Part B) is verified, then remove it.

---

## Part B — Migrate the pipeline to OpenAI API

> Do this on a branch and test before deleting `GITHUB_TOKEN`.

**Step B1 — Point the SDK client at OpenAI**

Edit `pipeline/setup.py`. Change the client construction in `init_github_models()`:

```python
# BEFORE
token = os.environ.get("GITHUB_TOKEN")
client = AsyncOpenAI(
    base_url="https://models.github.ai/inference",
    api_key=token,
)

# AFTER
token = os.environ.get("OPENAI_API_KEY")
if not token:
    raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
client = AsyncOpenAI(
    base_url="https://api.openai.com/v1",
    api_key=token,
)
```

Keep `set_default_openai_api("chat_completions")` — native OpenAI supports it, and it avoids changing tool-calling behaviour. (Optional: rename the function to `init_openai()` and update its five call sites in `pipeline/main.py`.)

**Step B2 — Strip the `openai/` model prefix**

Native OpenAI rejects `openai/gpt-4.1`; it expects bare `gpt-4.1`. Update every model string:

- `config/models.yaml` — change all `openai/gpt-4.1`, `openai/gpt-4.1-mini`, `openai/gpt-4.1-nano` (and the `fallback_chain`) to their bare names.
- `pipeline/config_loader.py` — the `openai/gpt-4.1` default (~line 74).
- `pipeline/definitions.py` — the `.get("model", "openai/gpt-4.1")` defaults.
- `pipeline/degradation.py` — the `openai/gpt-4.1` reference and fallback list.
- `pipeline/guardrails.py` — the RPM dict keys (`"openai/gpt-4.1"`, `"openai/gpt-4.1-mini"`, …).

**Step B3 — Fix the model-family detection**

In `pipeline/definitions.py`, `model_settings_for()` branches on the prefix. Update the checks to match bare names:

```python
# BEFORE
if model.startswith("openai/gpt-5") or model.startswith("openai/o"):

# AFTER
if model.startswith("gpt-5") or model.startswith(("o1", "o3", "o4")):
```

This keeps the `max_completion_tokens` / no-temperature handling correct if you adopt any `gpt-5`/o-series model.

**Step B4 — Update environment checks and labels**

- `pipeline/main.py` `_check_status()` — replace the `("GITHUB_TOKEN", "GitHub Models API access")` check with `("OPENAI_API_KEY", "OpenAI API access")`.
- `pipeline/pipeline_logger.py` — rename the `has_github_token` field (and its env lookup) to `has_openai_key` / `OPENAI_API_KEY`.
- Update the docstring env-var references in `pipeline/main.py` and `pipeline/setup.py`.

**Step B5 — (Optional) Relax the Editor token cap**

The GitHub Models 8k limit no longer applies. In `config/models.yaml` you may raise the Editor's `max_tokens` (e.g. 2500 → 4000) for fuller edits. Test output first; the `_clean_llm_text` sanitiser stays as-is.

**Step B6 — (Optional) Re-tier for cost**

To hit the "Optimised" cost row, set Orchestrator/Publisher/Indexer to `gpt-5-mini` and keep `gpt-4.1` for Writer/Editor. Validate publish output before committing.

**Step B7 — Test locally**

```bash
source .venv/bin/activate
.venv/bin/python -m pipeline.main status                 # expect OPENAI_API_KEY ✓ + DB connected
.venv/bin/python -m pipeline.main --dry-run "BLOG: test topic"
.venv/bin/python -m pipeline.main "RESEARCH: a small test topic"   # cheap end-to-end check
```

Confirm: no `413` errors, correct model names in logs, and clean punctuation in a real `BLOG:` output published to Ghost.

**Step B8 — Update Railway**

- Add `OPENAI_API_KEY` to the Railway service variables (service `0daf496c-e14f-41d4-b89b-3624a778c99d`).
- Deploy the branch; run one live `BLOG:` via email trigger to confirm end-to-end.
- Once green, **remove `GITHUB_TOKEN`** from Railway and `.env`.

---

## Part C — Set up Cline (coding assistant)

**Step C1 — Install the extension**
- VS Code → Extensions (`Cmd+Shift+X`) → search **"Cline"** → Install. (Marketplace publisher: `saoudrizwan.claude-dev`.)

**Step C2 — Configure the provider**
- Open the Cline panel → Settings.
- **API Provider:** OpenAI.
- **API Key:** your `OPENAI_API_KEY` (same key as the pipeline).
- **Model:** choose a coding model — `gpt-5` for best quality, or `gpt-5-mini` to keep costs low for routine edits.

**Step C3 — Choose modes**
- Cline offers **Plan** and **Act** modes. Use **Plan** first on risky changes (it drafts a plan you approve before it edits files or runs terminal commands) — valuable since the agent can touch your live Ghost/Railway setup.

**Step C4 — Port your Copilot instructions**
- Copilot's `.github/copilot-instructions.md` and `.github/skills/*` stop working without Copilot.
- Create an **`AGENTS.md`** at the project root distilling the key rules from `copilot-instructions.md` (stack facts, `.venv` usage, `DATABASE_URL` external-proxy rule, Ghost/`httpx` rule, model assignments). Cline reads project rules and honours `AGENTS.md`-style guidance.
- Re-express the four skills (`github-push`, `index-reports`, `query-pipeline-logs`, `service-auth`) as short sections in `AGENTS.md` or as MCP tools (Step C6).

**Step C5 — Set an approval/auto-run policy**
- In Cline settings, keep **command auto-approval OFF** initially so no terminal command runs against Railway/Ghost without your confirmation. Loosen selectively once comfortable.

**Step C6 — (Optional) Wire MCP tools**
- Cline supports MCP servers. You can expose repo-specific helpers (e.g. a pipeline-logs query tool) so the agent can call them directly. Add these later once the basics work.

---

## Part D — Verification & Rollback

**Verification checklist**
- [ ] `pipeline.main status` shows `OPENAI_API_KEY ✓` and DB connected.
- [ ] A real `BLOG:` run publishes to Ghost with correct punctuation (no `it92s` / vanished dashes).
- [ ] Logs show bare model names (`gpt-4.1`, not `openai/gpt-4.1`) and **no `413` fallback**.
- [ ] Railway email-triggered run completes end-to-end.
- [ ] Cline can read/edit files and answer questions using your `OPENAI_API_KEY`.
- [ ] OpenAI dashboard shows spend within your Step A4 cap.

**Rollback**
- The change is contained to `pipeline/setup.py`, model strings, and env vars. To revert: restore `GITHUB_TOKEN`, point `setup.py` back to `models.github.ai/inference`, and restore the `openai/` prefixes (git revert of the branch). Keep the branch until a few live runs succeed.

---

## Appendix — Model mapping

| Agent | Today (`config/models.yaml`) | Bare name (OpenAI) | Optimised option |
|---|---|---|---|
| Orchestrator | `openai/gpt-4.1-mini` | `gpt-4.1-mini` | `gpt-5-mini` |
| Researcher | `openai/gpt-4.1` | `gpt-4.1` | `gpt-4.1` |
| Writer | `openai/gpt-4.1` | `gpt-4.1` | `gpt-4.1` |
| Editor | `openai/gpt-4.1` | `gpt-4.1` | `gpt-4.1` |
| Publisher | `openai/gpt-4.1-mini` | `gpt-4.1-mini` | `gpt-5-mini` |
| Indexer | `openai/gpt-4.1-mini` | `gpt-4.1-mini` | `gpt-5-mini` |

**Files touched in Part B:** `pipeline/setup.py`, `config/models.yaml`, `pipeline/config_loader.py`, `pipeline/definitions.py`, `pipeline/degradation.py`, `pipeline/guardrails.py`, `pipeline/main.py`, `pipeline/pipeline_logger.py`.

> **Note:** If you later want to keep the `openai/` prefixes untouched (zero code edits to model strings) *and* retain multi-model flexibility, OpenRouter uses exactly that `openai/model` naming convention. This plan targets OpenAI-direct as requested; OpenRouter remains a drop-in alternative for `setup.py`'s `base_url` only.
