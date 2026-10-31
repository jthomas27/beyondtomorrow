# Primary research and narrative depth

The October capex rerun exposed discovery, extraction and retrieval failures.
Source availability was not the same as usable evidence in the research packet.
A live read of the failing Meta SEC exhibit returned an SGML-wrapped HTML
document. The previous extractor returned zero characters; unwrapping the HTML
recovered 28,109 characters with revenue and capex content. An offline regression
also caught financial tables being dropped by article extraction.

## Research sequence

1. Translate the question into named subjects, reporting periods and comparable
   metrics. Group aliases in the approved registry make issuer sources visible
   for topics such as Big Tech. The researcher chooses relevant group members;
   aliases are discovery aids rather than evidence or a required company list.
2. Search each major subject separately, normally fetching three results per
   query. Read the indexed originals by exact URL before searching again.
3. Seek the mechanism, relevant counter-evidence and an observation that could
   distinguish competing interpretations. Issuer claims and independent primary
   evidence serve different purposes; repeating one report does not add variety.
4. Repair important gaps by changing document format or approved host: filing,
   issuer release, PDF or regulator/repository copy. Record an access failure
   separately from a metric that a successfully read source does not disclose.
5. Synthesize an evidence map through question_coverage and key_findings, carrying
   periods, units, definitions and counter-evidence into the writer's context.

## Access and retrieval changes

- SEC document envelopes are removed before HTML extraction. Omitted financial
  tables are retained in source order with their cells and headers.
- Long documents yield query-relevant passages from throughout the document,
  including the opening for context. Excerpt boundaries are marked. This remains
  a bounded selection, not an assurance that the whole filing was read.
- Recently stored documents marked with the old prefix-truncation marker are
  re-fetched when rediscovered, rather than being kept solely by the seven-day cache.
- read_indexed_source reads a known original directly without a global ranking
  contest or another embedding request. It enforces the approved-source policy.
- search_corpus(evidence_only=True) excludes generated research and internal
  documents in SQL before ranking limits. General corpus use remains available.
- fetch_page accepts section/metric query terms when stored excerpts are insufficient.
- Stored dates are explicitly labelled as potentially ingestion dates. Source
  dates still require verification against the source text.

## Bounded effort, permissive publication

BLOG, RESEARCH and REPORT share task guidance and a 20-turn researcher ceiling.
The prompt permits up to six discovery calls, six original-document reads, two
external corpus searches and two direct fetches. These are soft planning ceilings,
not required calls or runtime-enforced individual quotas. Existing timeouts and
budget controls still apply. Tool-internal recovery searches can add fetches.
The researcher output cap is 6,000 tokens to accommodate comparative evidence.

There is no new source-count gate. One relevant approved source supporting a
finding still permits a focused article. Incomplete coverage narrows the claim;
unsupported facts remain excluded. A broad comparison should get subject-specific
search attempts before narrowing, but is not required to attain a fixed quota.

## Evaluation

Focused offline tests cover SEC envelopes and financial tables, late-document
evidence, group aliases, exact-source reads, approved-domain rejection, SQL
filtering before result limits, and existing single-source publication behaviour.
The live SEC check is a read-only extraction check, not a full article evaluation.
Subsequent drafts should be assessed for subject coverage, primary-source variety,
currency, mechanism, counter-evidence and a conclusion supported by those facts.
More searches alone do not establish a better narrative.
