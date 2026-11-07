# Research weaknesses and improvement guide

This note records research-pipeline weaknesses discussed after the October
2026 Big Tech capex article review. It is a diagnostic and evaluation guide,
not a requirement to meet a fixed source count. Recheck implementation and
run evidence before treating any item as a current defect.

## What the capex research exposed

The research packet for “Big Tech capex plans are not revenue forecasts” said
that corpus results were dominated by internal summaries and secondary sources.
Only one directly fetched primary page survived, and that page was truncated.
The requested comparison therefore lacked primary evidence for most companies.
Issuer filings and earnings materials were available in principle, so the
failure was not evidence that those companies had made no disclosures.

The investigation identified several contributing failure modes:

- **Discovery missed issuers named only by a group label.** Source ranking
  filtered issuer domains by literal entity names. A topic phrased as “Big
  Tech” did not reliably surface the relevant company domains, and Alphabet’s
  `abc.xyz` domain was absent from the approved registry.
- **Corpus ranking crowded out original documents.** Internal research and
  derived material could consume result slots before external evidence was
  returned. A broad semantic search was also a poor way to reopen a specific
  filing already known to the pipeline.
- **Long-source retrieval lost relevant passages.** Prefix-only truncation
  preserved opening material but could remove figures and discussion later in
  a filing. Previously stored truncated documents could remain in the corpus.
- **Extraction failed on a real SEC format.** The Meta exhibit used an SGML
  wrapper around HTML. The extractor returned no text until the HTML document
  was isolated. Some compact financial tables were also omitted by article
  extraction.
- **Research effort was too rigidly sequenced.** Fixed broad searches and
  corpus calls did not reliably lead to reading each original, repairing
  access failures, and checking evidence for each subject.
- **Evidence and narrative could be thin even when sources were retrieved.**
  Findings need comparable periods, definitions and units, plus a mechanism,
  competing explanation and a meaningful test of the interpretation. A list
  of figures does not by itself create a useful argument.
- **Missing evidence can be misread.** A failed fetch or search miss must not be
  described as issuer silence or proof that a metric does not exist.

## Improvements already made

The pipeline changes committed as `2f2d00e` addressed the specific failures:

- Group aliases and the Alphabet issuer domain improve discovery of relevant
  company sources.
- Research guidance asks for subject-by-subject searches, comparable periods
  and metrics, original-source reads, access repairs, counter-evidence, and a
  supported thesis with a complication and an observable next test.
- `read_indexed_source` opens a known approved original by exact URL, without
  asking corpus-wide ranking to select it again. Evidence-only corpus search
  filters internal/generated records before applying result limits.
- SEC SGML-wrapped HTML is unwrapped before extraction, and omitted visible
  financial tables are preserved with row and cell order.
- Long-source excerpts select relevant passages across the document while
  retaining opening context. Old prefix-truncated records are eligible for
  refetch when rediscovered. Direct fetches can also be targeted by query.
- BLOG and RESEARCH share research guidance and have a 20-turn researcher
  ceiling. No source minimum or completeness gate was added.
- The active researcher output cap is 6,000 tokens. The 8,000-token value in
  `config/limits.yaml` is documentation only and is not enforced.

The fixes improve the route to evidence; they do not prove that every later
article will have strong research or narrative. The SEC check and focused
offline tests verified extraction and tool behavior, not end-to-end article
quality.

## Output-token limit: what it can and cannot solve

The 6,000-token setting limits researcher output, including reasoning and the
visible JSON response under the current configuration. It is not a word-count
target and is not the model’s maximum capacity. The response must fit source
metadata, findings, coverage, gaps and suggested angles, so broad comparisons
can use the available space quickly.

There is not yet evidence that this cap caused the weak capex research. The
capex packet identifies discovery, corpus ranking and extraction failures.
Increasing output tokens cannot recover a filing the agent never retrieved.
Incomplete or invalid JSON is rejected before it is cached as successful
research, which reduces the risk of silently accepting a cut-off response.

Recommended policy:

1. Keep 6,000 as the default while evaluating the improved retrieval workflow.
2. For a later weak article, inspect the research JSON and run logs first. Ask
   whether the needed sources were found and read, whether JSON was complete,
   and whether findings were omitted or merely compressed.
3. Consider a controlled increase (for example, 8,000) only if complete,
   retrieved evidence is repeatedly missing from the final research JSON due to
   output pressure. Compare similar tasks before and after; do not infer success
   from token use alone.
4. If changing the active cap, update the `researcher.max_tokens` entry in
   `config/models.yaml` and the unenforced explanatory value in
   `config/limits.yaml` together. Confirm the current model/API limit from
   authoritative documentation before setting a higher value.
5. Prefer concise, claim-level findings with dates, units, source URLs and
   evidence roles over longer prose. The writer, not the researcher, owns
   article-length targets.

## Further improvements to consider

These are follow-up ideas, not claims that the implementation already has
them:

- **Measure primary-source coverage in run diagnostics.** Record, for each
  major subject, whether an approved original was discovered, fetched,
  extracted, read by the researcher, and cited in a finding. Report failures
  by stage. Do not turn the measure into a hard publication threshold.
- **Make retrieval quality observable.** Keep safe metadata for source URL,
  document type, reporting period, extraction character count, excerpt status,
  and fetch outcome. This makes “not found,” “not fetched,” “empty extraction,”
  and “not disclosed in the source” distinguishable.
- **Evaluate comparative research with real examples.** For representative
  topics, check that each named subject has comparable primary evidence where
  available, that figures retain period and units, that independent primary
  perspectives are not confused with multiple outlets repeating one filing,
  and that a counter-explanation informs the conclusion.
- **Improve issuer-source maps carefully.** Maintain official investor-relations,
  filing, regulatory, and data domains for common entities. Treat aliases as
  discovery hints; have the researcher determine which entities actually belong
  in the requested scope rather than searching every company for every topic.
- **Prefer repair paths with equivalent evidence.** When HTML fails, try the
  issuer’s accessible release or PDF, then an approved regulator or repository
  copy. Preserve the reporting period and metric when switching formats.
- **Inspect writer handoff separately.** Confirm that primary findings,
  counter-evidence and material unknowns survive the research-to-writer
  transformation. Strong retrieval can still produce a weak article if the
  handoff drops the central evidence or the writer over-qualifies the prose.

## Review checklist for a future article

- Were the named subjects resolved and searched separately where necessary?
- Were relevant original documents available, retrieved, extracted and read?
- Does each important figure identify its period, units and definition?
- Are the compared figures genuinely comparable, or are differences explained?
- Does the evidence distinguish reported results from management claims and
  the article’s interpretation?
- Is there a concrete mechanism connecting the evidence to the thesis?
- Was the strongest supported counter-evidence considered?
- Are source-access failures kept distinct from facts absent in a read source?
- Did the research JSON carry the evidence and uncertainty into the draft?
- Is any weakness caused by missing research, output compression, writer
  handoff, or editorial style? Diagnose the stage before changing token caps.

Use a focused, qualified article when evidence is limited. The aim is better
retrieval and reasoning, not a brittle minimum number of sources.
