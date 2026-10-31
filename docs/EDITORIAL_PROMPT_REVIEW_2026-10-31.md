# Editorial prompt review — 31 October 2026

Reviewed the configured prompts, their actual use in `pipeline/definitions.py`,
the BLOG workflow, source policy and research compaction. The two Big Tech
articles provide examples of the desired and weaker behaviours. This review
identifies plausible contributors to quality loss; it does not establish the
cause of a trend across publication history.

## Agent assessment

| Agent | Strengths | Weaknesses and implications |
| --- | --- | --- |
| Researcher | Structured claim/source pairs, dates, question coverage, opposing evidence and an approved source policy. | A one-source minimum was presented as sufficient for broad articles. Two retrievals of three chunks can miss subjects in a comparison. Source ratings do not establish relevance or independence. The prompt now starts with evidence needs, original sources and comparable metrics. |
| Writer | Clear thesis, accessible voice, concrete examples, explanations, integrated citations and reader relevance. | Length pressure, a compulsory surprise per section and two levels of implications encourage repetition or unsupported interpretation. Automatic hedging and gap disclosures undermine confidence. The prompt now permits focused shorter articles, proportionate qualifications and evidence-led analysis. |
| Editor | Checks facts, structure, coherence, citations, British English and metadata. | Repeated the Writer's novelty and depth demands; suggested softening unsupported claims and leaving HTML flags in publishable copy. Cannot independently fetch fresh primary pages with its current tools. The prompt now prioritises correction/removal, relevant counter-evidence, balanced comparisons and consolidation of caveats. |
| Publisher | Predictable tool sequence, explicit edited-file input and validation errors. | Random feature imagery and mechanical checks do not assess editorial quality. Its YAML prompt is ignored: the active instructions are hardcoded in Python. Keep editorial judgement upstream; consider relevant imagery separately. |
| Indexer | Preserves document content and uses storage tools rather than inventing summaries. | Its YAML prompt is ignored. YAML requests per-finding indexing automatically; the active Python prompt makes that conditional. Uses today's date when absent, which must not be mistaken for the original publication date. |
| Orchestrator | Defines responsibilities and stage order. | Its YAML prompt is ignored. The BLOG workflow sequences stages directly; editing the routing prose alone will not improve BLOG behaviour. The orchestration prompt covers recovery, not evidence sufficiency. |

## Standards incorporated into the active editorial prompts

- Start with a specific central argument and a compelling, factual opening.
- Base core facts on retrieved original releases, filings, studies, datasets and
  official documents. CNBC and AP provide context, discovery and scrutiny.
- Match evidence coverage to every major subject and distinguish reporting periods,
  definitions, observations, management guidance and analyst forecasts.
- Explain mechanisms and concrete consequences with accessible language and
  accurate analogies. Develop a reasoned judgement and address relevant alternatives.
- Give each section a purpose and each example a distinct contribution.
- Keep supported statements direct. Explain a material limitation once; omit
  minor search failures and repeated qualifications from the article.
- Use descriptive, engaging headings and a length justified by the evidence.
- End with an answer and specific indicators that could strengthen or weaken it.
- Correct or remove unsupported claims; hidden comments and softer verbs do not
  supply evidence.

## Follow-up workflow fixes

The following changes implement the request to improve quality while keeping
source requirements permissive:

1. BLOG research instructions now prioritise original documents and comparable
   evidence. Two initial retrievals can be followed by up to two targeted repair
   calls; the turn ceiling is twelve. Research then proceeds with its supported
   scope. There is no source-count or publisher-count quota.
2. Source guidance now distinguishes a minimum usable factual base from evidence
   for a broad comparison. One supported approved source still permits writing,
   including secondary-only research or partial coverage. Existing checks for
   approved evidence and valid article citations remain in place.
3. Evidence handoffs now put complete findings first and keep source titles,
   URLs and primary/secondary roles alongside each finding. The context budget
   reserves space for uncertainty and question coverage. Oversized records are
   omitted whole with an explicit abridgement note; later useful evidence can
   still fit. Repetitive gaps cannot consume the factual evidence budget.
4. Publisher, Indexer and Orchestrator now read their configured YAML prompts,
   matching the editorial agents. Per-finding indexing remains opt-in. Indexer
   instructions distinguish source publication dates from default ingestion dates.

Runtime prompts are loaded at process startup. A worker release/restart is
required for production to use the changes. Feature imagery still uses the
existing asset pool; topical selection needs trustworthy descriptions of those
assets and is separate from source sufficiency and editorial quality.

## Validation and evaluation

Parsed the YAML and checked that all six configured agent prompts remain present.
Focused offline checks cover complete evidence under context pressure, preserved
source roles, later findings surviving oversized entries, permissive single-source
secondary research and actual configured prompt use. Existing user edits were
preserved. No live article generation or publication was performed, so an
improvement in generated output has not yet been measured.

A useful next evaluation is a draft-only comparison on the same topic and source
material: assess primary evidence coverage, comparable company treatment, repeated
caveats, unsupported causal claims, clarity of thesis and practical reader payoff.
Review the draft and edited version separately to see what the Editor improves
or weakens.
