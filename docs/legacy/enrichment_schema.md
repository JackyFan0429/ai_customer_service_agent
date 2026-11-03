# Case enrichment schema

The enrichment layer is conservative by design. Historical support statements
are stored as candidates, not authoritative facts.

## Quality tiers

- `verified_case`: contains an actionable historical support response and an
  explicit user-authored resolution confirmation. This is evidence of a useful
  historical case, not proof that the advice is current.
- `reference_case`: contains useful problem/support evidence but lacks strong
  resolution proof.
- `archive_only`: incomplete, low-information, test-like, or otherwise unsuitable
  for routine retrieval.

## Retrieval status

- `eligible`: may enter the initial case-summary retrieval index.
- `review_required`: structurally or temporally risky; excluded until reviewed.
- `excluded`: archive-only; retained for audit.

Content containing script execution patterns or prompt-injection language is
forced into `archive_only` and the review queue. It must not enter retrieval
without sanitization and explicit review.

## Evidence rules

- Input messages use the channel-neutral `message_id`, `role`, and `content` fields.
- Candidate solutions must point to support-authored message IDs.
- Resolution confirmation must point to user-authored message IDs.
- A `/close` status alone never proves resolution.
- Suggested diagnostic questions are generated workflow prompts, not claims that
  those questions appeared in the historical conversation.
- Official conflict status remains `not_checked_no_official_kb` until an official
  knowledge source exists.
