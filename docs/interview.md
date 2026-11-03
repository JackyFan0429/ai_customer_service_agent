# Product interview summary

[Documentation](README.md) · [Chinese](interview.zh-CN.md)

**Responsibilities:** requirements analysis, workflow design, ChatGPT-assisted development and acceptance testing.  
**AI methods:** retrieval-augmented responses, BM25 and character n-grams, evidence selection, structured model APIs, context tracking and retrieval evaluation.

## A short introduction

“I built a local AI support product to explore how routine questions can be handled faster while keeping staff in control. I translated support patterns into customer, support and admin workflows, then used ChatGPT to help implement them. My main contribution was deciding what AI could answer, what needed fresh account data and what required human approval.

Three problems shaped the work. Customers initially could not see replies automatically, so I checked the generation-to-publication flow and added live customer/staff synchronization. Real-model failures were difficult to distinguish from local responses, so I added three-stage startup checks and visible call diagnostics. Follow-ups could reuse the wrong topic or stale balance, so I preserved public conversation context and refreshed facts when the topic changed.

For retrieval, I compared BM25, character n-grams and hybrid on a separate development/holdout dataset. I found the larger issue was the coverage filter discarding relevant evidence, so I kept the existing configuration rather than claiming an algorithm win. The next step is to validate that fixing evidence coverage reduces repeated questions and human handling.”

## Defensible evidence

- 225 software checks, 29 portal scenarios and 48 legacy RAG scenarios pass locally.
- Retrieval comparison: 20 development and 10 holdout queries; labels await owner review. Final holdout Recall@4 is 68.75%, not answer accuracy.
- The published holdout was run after configuration freeze. Future fixes based on those failures need a new unseen validation set.
- No measured labor savings, revenue uplift or production resolution rate is available.

## How to assess business value

| Goal | Measure |
|---|---|
| Customer experience | Time to first useful answer, repeated-question rate, reopened tickets |
| Staff efficiency | Handling time, suggestion adoption and transfer reasons |
| Cost | Calls, retries, tokens and price per resolved ticket |
| Quality | Evidence coverage, unsupported claims and correct human escalation |

Compare like-for-like ticket categories and preserve failed cases in the denominator. Local retrieval avoids embedding API calls, but triage, generation and review still incur model costs when enabled.

