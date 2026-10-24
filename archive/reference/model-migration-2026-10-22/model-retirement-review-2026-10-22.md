# OpenAI model retirement review — BeyondTomorrow.World

> Implementation update: the migration is now deployed to the production email-worker. This review
> preserves the original findings and proposed plan; see
> [implementation and validation results](migration-validation-2026-10-22.md)
> for completed work, validation evidence, costs and production deployment details.

Review date: **22 October 2026**. Scope: repository inspection and current official OpenAI documentation. The original proposal below is preserved for context; the linked validation record describes subsequent authorized implementation and deployment.

## Decision and urgency

**Address the nano fallback immediately, then migrate the primary models before January.** The retirement schedule relevant to this repository is:

| Model found | Use in this project | API shutdown | Priority |
|---|---|---|---|
| `gpt-4.1-nano` | Last-resort runtime fallback | **23 October 2026 — tomorrow** | Immediate |
| `gpt-4.1` | Researcher, Writer, Editor; fallback-chain entry | **14 January 2027** | Plan migration now |
| `gpt-4.1-mini` | Orchestrator, Publisher, Indexer; direct title repair; fallback entry | **14 January 2027** | Plan migration now |

OpenAI's October notice names the dated GPT-4.1 and mini snapshots; the model pages also mark the families deprecated. This code uses their undated aliases, so treat those aliases as migration work rather than assuming they survive the underlying snapshot. The nano notice explicitly includes its alias and dated snapshot. These are API deadlines, independently of ChatGPT UI retirements. [Official retirement schedule](https://developers.openai.com/api/docs/deprecations).

**Recommended destination, reflecting your quality preference:** use **Sol for Researcher, Writer, and Editor**, with **Luna for Orchestrator, Publisher, Indexer, and title repair**. Accept higher content-generation costs where they produce better evidence, analysis, and prose. Do not make an all-Luna trial a prerequisite. No benchmark of this project's outputs was performed, so quality improvements remain to be verified.

**Preferred quality target:** `gpt-6.1-sol` on Responses, starting at low reasoning. Evaluate medium reasoning selectively for difficult research or factual editing if low misses important issues. **Compatibility alternative:** `gpt-6-sol` with reasoning disabled on the existing Chat Completions endpoint. Use that alternative if it meets the quality bar and materially simplifies delivery; avoid migrating through both versions without a demonstrated reason. Keep Luna on routine roles, where extra reasoning is unlikely to improve the article itself.

## What the repository actually uses

The active provider is native OpenAI: `pipeline/setup.py:37–42` creates an OpenAI client and explicitly selects **Chat Completions**. The GitHub Models/Copilot language at the top of `config/models.yaml` is stale commentary, not the configured provider.

| Surface | Evidence and migration implication |
|---|---|
| Primary assignments | `config/models.yaml:31–66`: three GPT-4.1 roles and three mini roles. Researcher currently has **2,000** output tokens, despite the 8,000 shown in AGENTS.md. Writer and Editor each have 4,000. |
| Built-in agent defaults | `pipeline/definitions.py:109,177,219,264,288,338` repeats the old models as defaults when configuration is absent. |
| Runtime fallback | `pipeline/degradation.py:25–29` owns a hard-coded chain: GPT-4.1 → mini → nano. This is what `select_model()` actually walks. |
| Other chain definitions | `config/models.yaml:90–93` and `pipeline/config_loader.py:71–77` also define the old chain. Editing YAML alone does **not** update the runtime constant. |
| Direct LLM call | `pipeline/main.py:773–776` uses mini for title repair, outside the agent configuration, with `max_tokens=30` and temperature 0.3. |
| Rate/budget policy | `pipeline/guardrails.py:31–50` keys daily and RPM limits by model name. New names have no limits under the current unknown-model behavior (`check_model_budget` / `check_rpm`). |
| Parameter adapter | `pipeline/definitions.py:41–69` special-cases GPT-5/o-series only. GPT-6 falls through to legacy `max_tokens` and temperature settings, without an explicit reasoning choice. |
| Retry settings | `pipeline/main.py:323–343` rebuilds settings on a 413 retry with just temperature/max_tokens. A future model-aware adapter must also cover this path. |
| Usage attribution | `pipeline/main.py:414–417` restores the configured model before callers record usage. Fallback usage can therefore be attributed to the original model. Record the actual executed model and preserve visibility of retries before relying on cost comparisons. |
| Editor evidence | `pipeline/main.py:1019` limits the Editor's research context to 1,200 characters. `_compact_research()` puts the source list last, so truncation can remove evidence. A stronger Editor needs sufficient claim/source context to verify the draft. |
| CLI override | `pipeline/main.py:2009–2017`: prefixed BLOG/RESEARCH/REPORT/PUBLISH/INDEX dispatches do not pass `args.model` through. `--model` is not a reliable way to A/B test those workflows. |
| Legacy helper | `scripts/_resume_pipeline.py:22–23` hard-codes `openai/gpt-4.1-mini`, including the forbidden provider prefix. Treat this as a separate helper repair if it is still used. |
| Tests and guidance | `tests/test_degradation.py`, `tests/test_config_loader.py`, and `tests/test_guardrails.py` encode old model names. AGENTS.md, `.github/copilot-instructions.md`, and `.github/workflows/agents.yml` contain old guidance/examples. Update active contracts and operational examples during implementation; historical comments need not be rewritten indiscriminately. |

**Important failure mode:** with a DB pool, `select_model()` starts at the first old-chain entry when the preferred model is unknown. A YAML-only switch to GPT-6 can therefore proactively replace the new model with GPT-4.1 even before the first call. `get_fallback()` likewise directs unknown names back to the old chain. This needs a routing fix, not just a search-and-replace in YAML.

The guardrail registries also list `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, and `gpt-4o`, but these are not current primary assignments or runtime fallback entries. Their older snapshots are also scheduled for retirement (GPT-5 family on 11 December 2026; relevant GPT-4o snapshots on 14 January 2027). Do not select these as a durable migration destination. `gpt-4o-mini` in tests is a fixture, not evidence of production usage. [Retirement schedule](https://developers.openai.com/api/docs/deprecations).

## Recommended alternatives and rationale

| Workload | Candidate | Why and acceptance condition |
|---|---|---|
| Researcher | `gpt-6.1-sol`, low reasoning initially | Invest in source coverage, contradictions, and synthesis. Require valid research JSON and accurate attribution. Try medium only if it improves difficult cases enough to justify added tokens and latency. |
| Writer | `gpt-6.1-sol`, low reasoning initially | Invest in original analysis, coherent structure, and house style. Require desired length, correct frontmatter, and supported implications. Keep low unless a higher effort measurably improves the prose. |
| Editor | `gpt-6.1-sol`, low reasoning initially | Preserve a strong final content check. Require correction of planted factual/structural errors without invented citations or content loss. |
| Orchestrator, Publisher, Indexer | `gpt-6-luna`, reasoning explicitly `none` initially | Focused routing and metadata/tool tasks are appropriate for the efficient tier. Require correct tools, arguments, and handoffs. Zero temperature does not guarantee deterministic tool execution. |
| Title repair | `gpt-6-luna`, reasoning `none` | Small bounded rewrite. Require only a 5–10-word title; validate request parameters and truncation behavior separately from agent calls. |
| Fallback | Bounded retries, then a validated alternative or defer | Preserve quality requirements. Luna may serve as a content fallback only after evaluation shows it meets the same publication bar; otherwise retain the draft and defer. Routine Luna roles retry then defer. Never return to retired models. |
| Embeddings | Keep `text-embedding-3-small` | No announced retirement found in the checked schedule. Existing code defaults to 1,536 dimensions. No re-embedding or schema migration is justified by this text-model retirement. |

Luna supports structured outputs and a roughly 1M-token context, fitting the existing large-context and JSON requirements. Sol is positioned for complex work. Capability descriptions support trying these candidates; they do not establish superiority on your blog corpus. [Luna specifications](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol specifications](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [embedding model](https://developers.openai.com/api/docs/models/text-embedding-3-small).

## Compatibility: two practical migration paths

**A. Compatibility alternative: GPT-6 Sol and Luna on Chat Completions.** Both support function calling with `reasoning_effort: "none"`. Use GPT-6 Sol for the three content roles and Luna for routine roles. Validate the completion-token parameter with the pinned SDK and target API rather than assuming the existing legacy `max_tokens` branch is correct. Keep temperatures only where supported for the selected effort. This preserves the endpoint but gives up reasoning-enabled tool use; test quality rather than assuming equivalence to GPT-6.1 Sol. [GPT-6 Sol requirements](https://developers.openai.com/api/docs/models/gpt-6-sol), [Luna requirements](https://developers.openai.com/api/docs/models/gpt-6-luna).

**B. Preferred quality path: GPT-6.1 Sol and Luna on Responses.** GPT-6.1 Sol requires Responses for tool calling and supports low reasoning but not `none`. Start the three content roles at low, and routine Luna roles at none. Remove temperature for reasoning-enabled requests. Verify SDK setup, output-token mapping, tool/handoff serialization, usage extraction, and retry settings together, changing only what compatibility requires; test the direct title call separately if it stays on Chat Completions. A global endpoint change can affect every role, including roles temporarily left on GPT-4.1. [GPT-6.1 Sol requirements](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [official migration guidance](https://developers.openai.com/api/docs/guides/latest-model).

Dependencies currently pin `openai==2.26.0` and `openai-agents==0.10.5`. Their age alone does not prove incompatibility: verify their serialized request shape first, and propose a tested upgrade if necessary. No dependency installation or account-access test was performed in this review.

## Pricing comparison

USD per **1 million tokens**, Standard processing, ordinary text requests. Cached input is shown separately; it is not assumed in the examples.

| Model | Uncached input | Cached input | Output | Role |
|---|---:|---:|---:|---|
| GPT-4.1 | $2.00 | $0.50 | $8.00 | Current quality tier |
| GPT-4.1 mini | $0.40 | $0.10 | $1.60 | Current efficient tier |
| GPT-4.1 nano | $0.10 | $0.025 | $0.40 | Retiring fallback |
| GPT-6 Luna | $0.10 | $0.01 | $0.50 | Recommended efficient tier |
| GPT-6 Sol | $2.00 | $0.20 | $10.00 | Compatibility alternative for content roles |
| GPT-6.1 Sol | $2.00 | $0.10 | $10.00 | Recommended quality candidate |
| text-embedding-3-small | $0.02 | — | — | Retain |

Sources: [GPT-4.1 pricing](https://developers.openai.com/api/docs/models/gpt-4.1), [mini pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini), [nano pricing](https://developers.openai.com/api/docs/models/gpt-4.1-nano), [current pricing](https://developers.openai.com/api/docs/pricing), [embedding pricing](https://developers.openai.com/api/docs/models/text-embedding-3-small).

GPT-6 Sol and GPT-6.1 Sol have the same uncached input/output rates; GPT-6.1 Sol has cheaper cached input. Choose between them on measured quality and implementation effort, not an assumed uncached price advantage. [GPT-6 Sol pricing](https://developers.openai.com/api/docs/models/gpt-6-sol), [GPT-6.1 Sol pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

At equal token counts, Luna reduces mini's input rate by **75%** and output rate by **68.75%**. Against nano, input is unchanged and output is **25% higher**. Sol matches GPT-4.1 input pricing and raises output pricing by **25%**. These are unit-price changes, not predictions of total bills.

For a normalized call with **10,000 uncached input tokens and 2,000 billable output tokens**:

| Model | Cost per call | Cost for 1,000 such calls |
|---|---:|---:|
| GPT-4.1 | $0.0360 | $36.00 |
| GPT-4.1 mini | $0.0072 | $7.20 |
| GPT-4.1 nano | $0.0018 | $1.80 |
| GPT-6 Luna | $0.0020 | $2.00 |
| GPT-6.1 Sol | $0.0400 | $40.00 |

Illustrative six-role run, assuming exactly one normalized call per role: current three GPT-4.1 + three mini = **$0.1296**; recommended three Sol + three Luna = **$0.1260**. An Editor-only Sol option would be **$0.0500**, but the recommended three-Sol allocation deliberately spends an additional **$0.0760** in this example to strengthen research and writing too. These are arithmetic comparisons, not a savings forecast: reasoning, unequal stage sizes, retries, and multiple tool turns can make the proposed pipeline cost more than today's. Title repair and embeddings are excluded. The normal BLOG path is also explicitly staged, so a six-role example does not establish that every role makes one call per article.

Formula: `cost = (uncached_input × input_rate + cached_input × cached_rate + billable_output × output_rate) / 1,000,000`, plus applicable cache-write and tool charges. Reasoning usage can increase billable output and latency, so compare total tokens per accepted article. New-model requests above 272K input tokens have higher rates; cache writes and processing tiers can also change the bill. [Luna billing details](https://developers.openai.com/api/docs/models/gpt-6-luna), [Sol billing details](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

Actual monthly spend cannot be inferred from call-count guardrails or configured output caps. Measure representative workloads and reconcile usage against OpenAI billing before setting a dollar budget.

## Small improvements that make the model investment effective

- **Give the Editor enough evidence.** Replace the inherited 1,200-character research truncation with a bounded set of claims and associated source links, retaining contradictions and uncertainty. Allow retrieval of fuller findings where needed. Do not simply pass the entire corpus or remove all limits.
- **Keep prompts consistent.** The runtime research instruction requests one corpus search, while `config/prompts.yaml` requests two, including a contrasting angle. Resolve that specific conflict. Preserve effective style and evidence rules; avoid a wholesale prompt rewrite during migration.
- **Separate operational retries from quality repair.** Retry transient API failures within bounds. Repair only the stage that produced a content defect, using explicit feedback. Do not repeat research, writing, and editing automatically for one missing metadata field.
- **Measure the result that matters.** Track actual executed models, total tokens including available reasoning/cache details, failed attempts, latency, and manual editing effort. Compare cost per accepted article, not merely cost per successful call. Reuse existing logs where practical rather than building a new observability platform.
- **Preserve publication standards during fallback.** A weaker fallback must not silently bypass source, formatting, or editorial checks. Keep incomplete output as a draft and defer when the standard is not met. Review duplicate-publication protection before enabling whole-stage retries around publishing.

## Proposed next steps — not executed

1. **Today, before the nano shutdown:** remove nano from every active chain and terminate cleanly when remaining models are exhausted. Add a replacement only after a live API call with mocked application tools confirms account access and parameter compatibility. Mocking the API itself cannot establish access. Keeping GPT-4.1/mini temporarily is a bridge to January, not the final migration.
2. **Within one week:** create an isolated migration branch. Start with a small compatibility check for preferred path B; use path A if B introduces disproportionate work and A meets the quality bar. Implement one selected path rather than two production migrations. Make runtime routing consume one authoritative chain; define explicit behavior for unknown models. Update model-aware settings, built-in defaults, title repair, retry reconstruction, model-keyed guardrails, and actual-model usage attribution. Preserve bare model IDs. Include the bounded Editor evidence improvement and resolve the research-search instruction conflict.
3. **Evaluate the three-Sol allocation on five representative articles first:** include a straightforward topic, conflicting evidence, numerical claims, long content, and a difficult research topic. Reuse fixed research for Writer/Editor comparisons; assess the Researcher separately on matched retrieved material. Compare with existing outputs using blind review where practical. Check JSON, source fidelity, meaningful analysis, house style, frontmatter, length, and successful file/tool operations. Start at low reasoning; compare medium only on difficult research/editing cases. Use distinct evaluation filenames so existing research/draft caches cannot skip the stage under test. Expand beyond five only when failures or ambiguous results justify it. Mock publication, newsletter, and LinkedIn tools; do not build a large evaluation platform for this migration.
4. **Use a clear release gate and focused regression coverage:** require every sample to complete without request-schema errors, invalid required output, or unintended external actions; manually verify material factual/numerical claims and source links. Resolve critical defects before release. New preferred models must survive selection with a real-like pool; fallbacks must never return retired models; retries must retain required settings; logs must identify actual execution. Review the measured total cost and editing effort with the three-Sol allocation. A small sample supports rollout judgment, not a guarantee of future accuracy.
5. **Run project checks in `.venv`:** environment/DB status, pytest, and CLI dry-run, followed by a small RESEARCH run. The existing dry-run only prints dispatch information and returns; it does not validate model requests or tools. RESEARCH writes findings/index data and makes paid calls, so use a test environment where appropriate. These checks were not run for this document-only review.
6. **Roll out as soon as the checks pass, well before 14 January:** treat **15 December 2026** as the latest planned completion date, not a reason to wait. Authenticate services using the project instructions before service-touching scripts. Review and deploy the email-worker, restart long-running workers so startup-loaded configuration refreshes, and manually review the first few migrated articles before restoring unattended publication. Monitor actual model IDs, errors, total costs, and output quality. Do not use `--model` on a prefixed command as proof the migration is active.
7. **Maintain a viable rollback:** retain the prior deployment/config for rollback only while its models remain available. After shutdown, rollback must still use supported models or defer work. Periodically review OpenAI notices and account model availability.

**Keep scope narrow:** no re-embedding, database schema migration, new agent architecture, fine-tuning, caching infrastructure, blanket token-limit increases, or speculative dependency upgrades. Use existing output caps as the starting point for compatibility tests; if reasoning crowds out usable output or causes truncation, adjust only the affected role based on measured usage. Leave unrelated legacy helpers alone unless used in the migration. Broader optimization can wait until the new pipeline is stable.

## Review boundaries

Inspected pipeline code, configuration, requirements, relevant scripts/tests, workflow configuration, and project guidance. This report was revised to reflect your preference to spend more on three Sol content agents and to incorporate the follow-up quality and rollout review. No source, configuration, dependency, or deployment files were changed. No secrets were read from `.env` or printed. No API-backed pipeline, deployment, database query, publication, or notification was executed. Production overrides (including `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS`) and account-specific model access remain unverified. Pricing and retirement dates reflect the official pages checked on the review date and should be rechecked at implementation time.
