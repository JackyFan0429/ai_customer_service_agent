# Official knowledge policy

## Precedence

1. P0: live account and service-state tools
2. P1: official source-attributed knowledge within its review window
3. P2: reviewed historical case evidence
4. P3: unresolved or low-confidence historical material

P1 overrides P2 when the two conflict. High-volatility official documents must be
reviewed after their `review_after` date; they must not silently remain current.

## Required official record fields

- stable `doc_id`
- title and self-contained content
- authority (`official_public_website` or `official_internal_document`)
- source URL
- retrieval and review dates
- volatility level
- product/category/keyword metadata
- explicit claims and narrowly scoped contradiction patterns where applicable

## Conflict-check meanings

- `potential_conflict`: a historical support candidate matched an explicit
  contradiction pattern; block it pending review.
- `potentially_outdated_current_fact`: a historical answer makes a changing fact
  claim in an area covered by a volatile official document.
- `no_rule_conflict_detected`: relevant official documents exist and no configured
  rule fired. This does not prove correctness.
- `insufficient_official_coverage`: no related official source was available.

The rule checker is deliberately narrow. A later semantic entailment pass and
human review should complement it; neither may remove provenance.

## Internal PDF sources

Internal official PDFs are copied into `knowledge/official/sources/` with stable
English filenames and preserved checksums. They are not committed to Git.

Visual strike-through is authoritative for obsolescence: intersected text lines
are removed before chunking and retained only in an audit record. Extracted chunks
use three audiences:

- `customer_safe`: may support customer-facing answers within its review window.
- `agent_internal`: may inform diagnosis, routing, or escalation but must not be
  disclosed verbatim.
- `restricted_internal`: payment destinations, exact internal platform limits,
  or internal pricing; excluded from the retrieval corpus.

The original PDF and extracted internal JSONL remain local and are ignored by Git.
