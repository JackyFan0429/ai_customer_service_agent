# Project walkthrough and interview notes

**English** | [简体中文](interview.zh-CN.md)

These notes describe the prototype as of 2026-09-19. Run the [demo tutorial](../README.md) and [evaluation](evaluation.md) before discussing the results.

## Two-minute explanation

I built a personal support prototype for an AI API platform setting. It has not been deployed to real support operations. It handles setup, request errors and common questions, with a focus on turning historical cases into knowledge with explicit usage limits.

In an earlier private processing phase, I organized 1,659 historical cases into 13 issue categories and quality tiers, separated 660 archived or review-required cases, and combined the remaining evidence with official-source checks to produce 1,086 retrieval records. The public project now demonstrates the workflow with neutral names and 19 synthetic records; the original sources are separately archived.

The runtime combines BM25 and character similarity with expiry, conflict, error-code and disclosure checks. It chooses between answering, asking for clarification and requesting human review. It does not invent account or live-status results without tools.

An audit exposed specific issues: 401 could match as a substring of 1401, short error-code updates lost the client context, and unresolved follow-ups lost the active topic. I fixed a set of 48 synthetic scenarios and 63 messages as a baseline, then addressed those mechanisms and separated general refund-policy questions from personal refund requests.

Under the same local acceptance rules, complete scenarios improved from 39/48 to 48/48 and multi-turn scenarios from 9/14 to 14/14. Separately, 59 software tests passed. These results validate known synthetic cases, not real-model accuracy or a production resolution rate. Next steps are owner review of labels, independent task samples, live-model tests and target-user feedback.

Describe your contribution accurately, particularly business rules, acceptance criteria, failure analysis and trade-offs. Do not present all AI-assisted code as independently handwritten work.

## Explain each number precisely

| Figure | Meaning |
| --- | --- |
| 660 | 331 archived/excluded plus 329 requiring review; not 660 confirmed errors. |
| 1,086 | 994 historical summaries plus 92 official records; not 1,086 currently valid customer answers. |
| 48/48 | Synthetic development scenarios meeting explicit rules; not 100% customer-support accuracy. |
| 59 | Software tests, with mock API responses. |
| 19 | Fictional knowledge records in the public demo; not any company's real policies. |

## Trade-offs and next steps

- Fixed orchestration makes response boundaries explicit; autonomous planning, live business tools and real ticket creation are absent.
- Character n-grams are lexical similarity, not embeddings. Improve retrieval based on representative task evidence.
- Citations show generation-visible material, not claim-by-claim factual verification.
- Local context uses limited rules and the latest eight messages; complex omissions, corrections and long conversations need more evaluation.
- The private snapshot still had 69 expired internal records awaiting source verification. Re-extracting an old document does not renew its policies.
- Prioritize the balance between correct and incorrect answers, required-escalation recall and human verification time in the next evaluation.
