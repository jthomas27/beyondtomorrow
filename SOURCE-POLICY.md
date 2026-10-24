# Research source policy

## Evidence required before publication

Search recovery uses topic overlap with configured domains, notes, categories,
primary-source flags and credibility. It does not favour a fixed news outlet.
Issuer-specific candidates such as `investors.coreweave.com` are suggested only
when that issuer is named. SEC EDGAR (`sec.gov`) is approved for financial filings.
These candidates guide research; the full approved list remains available.

Search results and corpus retrieval give different publishers an initial slot
before repeating one publisher. All webpage fetches, redirects and final
citations must respect the approved list. Missing configuration fails closed.

Research must contain at least three credible approved source URLs, with findings
supported by at least two publishers. It must also assess every requested question
in `question_coverage` and set `ready_to_write` only when essential questions are
answered. Questions needing original figures or documents require primary
evidence. Liabilities-versus-revenue comparisons cannot rely on news alone.

The rendered article must cite its supporting research across at least two
publishers and retain required primary citations. Old caches without a coverage
assessment, existing drafts, recovery edits and direct `PUBLISH:` commands cannot
bypass the gate. A standalone edited file needs its matching `*-research.json`.
Insufficient evidence stops publication and retains the files for review.

These checks validate declared coverage, citation links and publisher domains;
they cannot prove that a source entails a claim or that two publishers reported
independently. Research and editing must still assess relevance and corroboration.

