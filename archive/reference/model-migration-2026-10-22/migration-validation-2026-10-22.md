# Model migration validation — 22 October 2026

Status: **complete — deployed and verified in production**.

## Final configuration

Researcher, Writer and Editor use `gpt-6.1-sol` with low reasoning. Orchestrator, Publisher, Indexer and title repair use `gpt-6-luna` with reasoning disabled. Researcher/Writer/Editor output caps are 4,000 tokens each, including reasoning. Responses is used throughout. Existing SDK versions support the migration; no SDK upgrade was required.

Content agents retain Sol during retries. Exhausted budgets defer work rather than silently reducing editorial quality. Publisher attempts are not automatically replayed after ambiguous failures. Usage hooks attribute completed calls to their actual model and agent, avoiding duplicate stage totals. Cancelled requests without responses still require billing reconciliation.

Research must contain valid JSON; malformed caches are ignored. BLOG generation requires at least three external HTTPS sources and a finding associated with those sources. This checks evidence presence, not factual entailment. Editor context retains up to 8,000 characters of evidence and uncertainty. Prompts distinguish timeless science from current events and request concrete, clear prose.

## Validation

| Check | Result |
|---|---|
| Complete test suite, including live embeddings and browser integration | **228 passed**, eight warnings from short JWT keys in test fixtures |
| Subsequent targeted checks after worker startup logging | **67 passed** |
| Final Railway authentication fallback tests | **2 passed** |
| Live SDK tool calls for all six configured roles | **Passed** |
| Live Luna → Sol handoff | **Passed** |
| Environment/database and CLI dry-run | **Passed**; external PostgreSQL proxy retained |
| Live NOAA research | **7 findings, 6 sources**, valid JSON and evidence gate passed |
| Dependency consistency, compilation, whitespace | **Passed** |

The initial failures were resolved: search now filters and deduplicates a larger candidate pool before applying the fetch cap, distinguishes rejected sources from extraction failures, and extracts primary PDF/plaintext evidence without treating snippets as full sources. The enabled arXiv provider now has its pinned dependency. Raising only the research cap from 2,000 to 4,000 resolved observed truncated JSON. Embedding normalization fixes the measured unit-vector failure without changing the embedding model, dimensions or database schema. Stale corpus, database, LinkedIn and browser test expectations were aligned with existing behavior; browser tests block write requests.

Full-suite evidence: `/tmp/btw-migration-suite-complete.txt`. Live research: `research/2026-10-22-noaa-sea-level-rise-research.json`.

## Editorial acceptance cases

Writer and Editor ran with local file tools only, without publishing, database, messaging tools or handoffs. Climate cases used the successful live research packet; technical cases used an explicit official-documentation fixture. Source associations, important numbers and uncertainty distinctions were reviewed.

| Case | Edited words | Input/output tokens | Estimated uncached Writer + Editor cost |
|---|---:|---:|---:|
| Ordinary | 1,521 | 35,761 / 4,886 | $0.1204 |
| Conflicting evidence | 1,492 | 35,617 / 4,780 | $0.1190 |
| Numerical claims | 1,366 | 28,509 / 4,569 | $0.1027 |
| Long evidence | 1,568 | 36,998 / 5,304 | $0.1270 |
| Difficult reasoning | 1,493 | 28,621 / 4,631 | $0.1036 |

All five completed with cited articles. Estimated combined editorial cost: **$0.5727**, excluding research and caching adjustments; these are estimates, not billing reconciliation. The cases retained forecast-versus-observation distinctions, avoided turning map water heights into dated predictions, and rejected unsupported claims that price ratios imply quality ratios.

Artifacts: `research/migration-validation-<case>-draft-edited.md`, matching draft and metrics JSON files, and `research/migration-validation-case-<case>.json`; case labels are `ordinary`, `conflicting`, `numerical`, `long`, `difficult`. These are review samples, not published articles.

Readability remains technical (Flesch approximately 29–40). These checks demonstrate working routing, source fidelity and useful handling of uncertainty; they do not establish general superiority over the previous models. Review the first real articles for site voice and density. Increase reasoning only if a recurring failure justifies the added cost.

## Production deployment

The saved Railway CLI login works; a rejected legacy token is bypassed by the authentication checker without changing credentials. Required worker variables are present, its OpenAI key matches the validated local key, and DATABASE_URL retains the external proxy. The deployment artifact excludes secrets, logs and research outputs, retains Python 3.11 and includes a SHA-256 runtime manifest. Railway rejected the original image-inclusive upload (413). The build now restores all 84 unchanged image assets from the pinned GitHub revision `8a0fe2a85cab3e9011fb2ab702938e172227109b` and verifies each SHA-256 hash before startup. Source deployments with images already present require no restoration. Future asset changes must update the pinned revision/manifest together; network or hash failures stop the build rather than ship missing images.

Previous successful deployment for rollback: `b4801509-c9ea-4b92-b94b-0e047aecd867`. Rollback restores previous model assignments, so assess retirement availability before using it; otherwise defer jobs rather than falling back to retired models.

Deployment `678036ea-d68f-4367-b70d-e4050e54d3ec` is **SUCCESS**. At 21:21:30 UTC, worker startup logged the intended Sol/Luna assignments, established PostgreSQL logging and found no orphaned runs. All **119 deployed runtime files** matched the SHA-256 release manifest. Production API probes passed for all six configured roles, including tool calls, structured output and a Luna → Sol handoff; command: `/opt/venv/bin/python -m scripts.validate_model_migration` via Railway SSH. Evidence: `/tmp/btw-sol-luna-production-probes.txt`. The worker started its normal 300-second polling loop. Ghost service configuration was not changed. Validation has not published articles or sent newsletters/notification emails.

## Operational considerations

Monitor completed-call usage, editorial quality and actual billing on the first normal runs. Keep Sol for content work and Luna for routine tasks; avoid a broad reasoning increase or further model changes without evidence. No schema migration or corpus reindex is needed.

LinkedIn OAuth was subsequently renewed at the user’s request, verified active with personal posting permission, and synced to the production worker. The renewed token expires 21 December 2026; no test post was sent.


## Follow-up: financial-news research recovery

The first production email run (`179ba4474253`) stopped before writing because research contained no supported findings. Publisher access failures were compounded by lost query context and a stale credibility-scoring table.

Corrections:

- Preserve the full subject, industry, month/year and site restriction in pre-fetch and retry queries.
- Add Nasdaq and CNBC to the approved source configuration with explicit credibility and commercial-commentary caveats. On zero usable pages, try at most two alternative-domain queries, each capped at three fetches, without recursively retrying. Full text is required; snippets are never substituted as evidence.
- Use configured credibility scores as authoritative, including hostname-boundary matching for URLs/subdomains. Previously approved BlackRock and Nasdaq material could be marked unknown by a separate hardcoded table. Configured conservative scores for preprints and other sources are retained.
- Ignore insufficient-evidence caches when retrying BLOG jobs. Check evidence during Research before declaring that stage successful or spending the Write-stage cooldown.
- Retry GET when a publisher rejects HEAD during source validation. Search-backend exceptions permit bounded query recovery.
- Keep the same models, reasoning levels and evidence threshold. The fix addresses source availability and policy consistency rather than spending more on reasoning.

Validation: **222 non-integration tests passed**, including hostname-spoof rejection, configured financial-source scores, blocked-source recovery, query/date preservation, evidence-gap cache rejection and HEAD-to-GET recovery. Previously run embedding/browser checks remain documented above; these changes do not touch those interfaces. A first live check retrieved full-text CNBC reports but exposed the stale scoring table; it returned an evidence-gap report and was not treated as a passing editorial run. The corrected live run completed in **100.4 seconds**, with **7 findings and 4 source URLs**, and passed the unchanged BLOG evidence gate. Artifact: `research/2026-10-22-explore-equity-market-sell-research.json`; execution log: `/tmp/btw-research-recovery-live.txt`. Its findings chiefly rely on CNBC and are marked medium confidence, with independent corroboration and full-month scope explicitly listed as gaps. Four URLs do not imply four independent publishers. This validates recovery and evidence association, not independent fact-checking of every market figure. No article, LinkedIn post, newsletter or notification email was sent by validation. Production deployment `5d4fcfae-1a4c-4465-9650-4e8c939f153a` is **SUCCESS**. All 119 runtime hashes match; worker startup confirms the intended Sol/Luna assignments and PostgreSQL logging. Production tool invocation verified CNBC and the Nasdaq subdomain both score 4/5 using the configured policy. LinkedIn identity validation returned HTTP 200 with the renewed production token. The original failed email was not automatically replayed; validation was research-only. Previous deployment: `aa1a330e-f8b4-4388-a521-61e0dd868d47`.


## First full publication after recovery

User-authorized BLOG run `4519a740195f` published [Tech Selloff Exposes the Cost of AI Financing](https://beyondtomorrow.world/tech-selloff-exposes-the-cost-of-ai-financing/) using the validated research cache. Writing, editing, Ghost publication and corpus indexing completed in 243.7 seconds; newsletter delivery succeeded for all three subscribed free members. The readability check emitted a non-blocking Flesch 34.6 warning.

LinkedIn initially rejected the hardcoded March 2025 API version with HTTP 426 `NONEXISTENT_VERSION`. Updated image and post requests to `202610`, the current release documented in [LinkedIn’s official changelog](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/recent-changes?view=li-lms-2026-09). All 18 LinkedIn unit tests passed. A LinkedIn-only recovery created `urn:li:share:7519156532224180226`; Ghost publication and newsletter delivery were not repeated. Recovery was recorded against the original run, retaining its earlier error events. Public article verification returned HTTP 200 with the expected title.

Worker deployment of the API-version fix: `ad914234-3f26-4c63-bd15-5b308f0030aa` is **SUCCESS**. All 119 runtime hashes match; the worker starts normally and connects to PostgreSQL. Production confirms API version `202610` and LinkedIn identity HTTP 200.
