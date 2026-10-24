# Prompt Engineering Guide

A high-level, generic guide to writing effective LLM prompts. Use this for any
agent, system prompt, task instruction, or one-shot completion. Specific examples
throughout draw on lessons from the BeyondTomorrow.World pipeline.

---

## 1. Core principles

Effective prompts share five properties. If a prompt is underperforming, check
these before tuning anything else.

1. **Clear role.** State who the model is and the domain it operates in. A
   role anchors vocabulary, judgement, and defaults.
2. **One purpose.** Each prompt does one job. If you need two outputs, write two
   prompts (or two agents). Mixed objectives produce mediocre results on both.
3. **Explicit output contract.** Define the exact shape, format, and boundaries
   of the output — schema, length, sections, what to include, what to exclude.
4. **Operational rules, not preferences.** Replace "try to" / "where possible"
   with concrete, checkable rules. "Cite every statistic" is enforceable;
   "use good citations" is not.
5. **Fail-loud contracts.** Specify what the model should return when it
   cannot complete the task (e.g. `MISSING: [...]`), instead of letting it
   silently produce a degraded result.

---

## 2. Structure

A reliable prompt structure, in order:

1. **Role & domain** — one or two sentences.
2. **Inputs** — what the model will receive and in what form.
3. **Sequence** — the steps to perform, numbered, in execution order.
4. **Rules** — non-negotiable constraints, grouped by theme.
5. **Output format** — the exact shape of the response (schema, frontmatter,
   length, sections).
6. **Failure modes** — what to return when an input is missing or a rule
   cannot be satisfied.

Put the most important constraints **first** and **last**. Models attend most
strongly to the beginning and end of a prompt; middle content gets diluted.

### Section ordering tip

If your prompt has both a **sequence** (do A, then B, then C) and **standing
rules** (always avoid X, always include Y), keep them separate. Mixing them
makes the sequence harder to follow and the rules harder to enforce.

---

## 3. Length and density

- **Shorter is usually better.** Long system prompts dilute attention. Aim
  for the minimum needed to constrain behaviour.
- **Every line should earn its place.** If removing a line wouldn't change
  output quality, remove it.
- **Repetition has diminishing returns.** Stating a rule twice rarely doubles
  compliance; it often signals the model that the rule is negotiable.
- **Hoist shared rules.** If two agents need the same style guide, factor
  it out (YAML anchors, includes, or named references) rather than copying.
- **Watch for "kitchen-sink drift."** Prompts accrete rules over time. Audit
  periodically and delete rules that are no longer relevant.

A useful test: read the prompt aloud. If you lose the thread, the model will too.

---

## 4. Specificity

Replace vague language with measurable constraints.

| Vague | Specific |
|---|---|
| "Be concise" | "150–250 words" |
| "Use good sources" | "Cite peer-reviewed studies or primary data sources from the last 2 years" |
| "Engaging tone" | "Conversational; use 'you' and 'we'; vary sentence length; one surprising insight per section" |
| "Don't hallucinate" | "Only assert claims supported by the provided sources. Flag unsupported claims with `<!-- UNVERIFIED: ... -->`" |
| "Properly formatted" | Provide a literal schema or example |

When in doubt, give a literal example of correct output. One concrete example
outperforms three abstract rules.

---

## 5. Positive vs negative instructions

LLMs follow the patterns embedded in the prompt — including the ones you tell
them to avoid. Phrase rules positively where possible.

| Avoid | Prefer |
|---|---|
| "NEVER begin with 'Picture' or 'Imagine'" | "Open with one of: a hard statistic, a contradiction, a sharp question, or a real moment described directly." |
| "Don't use jargon" | "If a technical term is unavoidable, define it in the same sentence." |
| "Avoid filler" | "Every sentence must add a fact, an argument, or a transition. Cut anything else." |

If a negative instruction is unavoidable (e.g. "never link to X"), pair it
with the positive alternative immediately afterwards.

---

## 6. Output contracts

Models honour explicit output contracts far more reliably than prose
descriptions.

- **Provide a literal schema.** For JSON output, include a minimal skeleton:
  ```json
  {"findings": [{"claim": "", "confidence": "high|medium|low", "sources": []}],
   "gaps": [], "total_sources": 0}
  ```
- **State the boundaries.** "Output ONLY the JSON. No preamble, no
  explanation, no markdown fences."
- **Define field semantics.** What does `confidence: medium` mean? What goes
  in `gaps`? Ambiguity in the schema becomes drift in the output.
- **Length is part of the contract.** "1200–1800 words" is enforceable;
  "medium length" is not.

For Markdown output, specify required sections, heading hierarchy, and
frontmatter fields explicitly.

---

## 7. Few-shot examples

A single high-quality example is worth pages of rules. Use examples when:

- The output format is unusual or strict.
- A common failure mode needs to be ruled out.
- The desired tone is hard to describe abstractly.

Best practice:

- **Bad / Good pairs** for narrow rules (e.g. citation style, link text).
- **Full reference outputs** for complex formats.
- **Keep examples short.** Long examples eat the context window.
- **Watch for over-fitting.** If you give one example, the model may mimic
  its specifics. Give two or three varied examples, or note "the example
  illustrates structure, not content."

---

## 8. Tool use guidance

When a prompt drives an agent with tools:

- **Name the tools and their cost.** "`fetch_page` returns full page text
  into the conversation — token-expensive. `search_and_index` returns a
  short receipt — token-safe."
- **Specify the sequence.** Tool order matters for both correctness and cost.
- **Specify when NOT to call.** Bound the agent. "Only call `fetch_page`
  for a single specific URL that cannot be found any other way."
- **Define inputs precisely.** Tool argument names and value formats should
  be unambiguous.

---

## 9. Failure modes

Tell the model what to do when things go wrong. Without this, it improvises —
usually badly.

- **Missing inputs:** "If the input lacks X, return `MISSING: X`. Do not
  proceed."
- **Conflicting sources:** "If two sources contradict, present both and flag
  the conflict."
- **Tool errors:** "If the tool returns an error, stop and report it verbatim.
  Do not retry, do not fabricate output."
- **Out-of-scope requests:** "If the request falls outside [scope], respond
  with `OUT_OF_SCOPE` and the reason."

Fail-loud contracts are the difference between a debuggable pipeline and a
silently degraded one.

---

## 10. Conditional rules

Mandatory rules apply to every run. Use conditional framing when a rule only
applies in some cases. This prevents the model from forcing irrelevant content
onto unrelated topics.

| Unconditional (often wrong) | Conditional (better) |
|---|---|
| "Include a financial angle in every post" | "**If the topic has a financial dimension**, include a financial angle" |
| "Always cite peer-reviewed research" | "**For scientific claims**, cite peer-reviewed research" |

---

## 11. Voice and tone

Tone is the hardest thing to specify and the easiest thing to over-specify.

- **One sentence of voice direction is usually enough.** "Sharp college
  professor — conversational, insightful, occasionally witty."
- **Anchor with audience.** "Curious generalists who want big-picture
  understanding without academic prose." Audience constrains tone far better
  than adjectives.
- **Give one or two voice rules, not ten.** "Use 'you' and 'we'. Vary
  sentence length. One surprising insight per section." That's enough.
- **Show, don't list.** A short example paragraph in the desired voice
  outperforms a long list of tonal adjectives.

---

## 12. Constraints on the model itself

Some constraints belong outside the prompt (in code or config), not inside it:

- **Token limits, temperature, model choice** — set as parameters, not prose.
- **Retry logic and fallback chains** — handle in code, not by asking the
  model to retry itself.
- **Hard validation** (e.g. word count, required sections) — verify
  post-hoc in code. Don't trust the model to self-validate.

The prompt should describe **what** to produce, not enforce constraints the
runtime can enforce more reliably.

---

## 13. Common anti-patterns

- **Mixing role and task.** "You are an expert X. Now do Y, Z, and also
  consider A, B, C." Split into role + task sections.
- **Hedging rules.** "Try to avoid…", "where appropriate…", "if possible…".
  These read as optional and are treated as optional.
- **Over-stuffed numbered lists.** A 12-step sequence with nested sub-bullets
  is unparseable. Hoist sub-rules into their own labelled sections.
- **Redundant negation.** "Do not be vague. Do not be unclear. Do not be
  imprecise." One precise positive rule beats three negations.
- **Self-contradicting rules.** "Be factual" and "be dramatic" can coexist
  only with an explicit reconciliation. Spell it out.
- **Stale references.** Tool names, file paths, env vars in the prompt
  drift from the codebase. Audit prompts against actual tool signatures
  periodically.
- **Prompt as documentation.** If a rule is for human maintainers, put it
  in a comment, not in the system message sent to the model.

---

## 14. Iteration and evaluation

Prompts should be treated like code:

- **Version them.** Track changes in source control.
- **Test with a held-out set.** Keep 5–10 representative inputs and re-run
  them after every prompt change.
- **Measure what matters.** Word count, citation count, format compliance,
  schema validity — automate the checks you care about.
- **One change at a time.** If you change three things and quality drops,
  you won't know which one caused it.
- **Diagnose before tuning.** When output is bad, ask: is this a prompt
  problem, a model problem, a tool problem, or a data problem? Tuning the
  wrong layer wastes effort.

---

## 15. Quick checklist

Before shipping a prompt, verify:

- [ ] Role and domain stated in one or two sentences.
- [ ] Single, clear purpose.
- [ ] Sequence and rules are separated.
- [ ] Every rule is specific and checkable.
- [ ] Output format is defined with a literal schema or example.
- [ ] Failure modes are explicit.
- [ ] No vague hedging language ("try to", "where possible").
- [ ] No stale tool names, paths, or references.
- [ ] No duplicated rules across related prompts.
- [ ] Length is justified — every line earns its place.
- [ ] Positive framing preferred over negative.
- [ ] Tested against a representative input set.

---

## 16. Further reading

- OpenAI: [Prompt engineering best practices](https://platform.openai.com/docs/guides/prompt-engineering)
- Anthropic: [Prompt engineering overview](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- "The Prompt Report" (Schulhoff et al., 2024) — survey of prompting techniques.

---

*Last updated: 2026-05-23*
