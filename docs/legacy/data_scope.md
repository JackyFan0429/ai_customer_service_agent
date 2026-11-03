# Legacy data scope

[Legacy guide](README.md) · [Chinese](data_scope.zh-CN.md)

This personal prototype is not an official company product. The legacy corpus uses fictional client/model labels and `.example` URLs. The current portal retains technical model/client names while using synthetic business records.

| Included path | Content |
|---|---|
| `support_agent/demo/corpus.jsonl` | 19 synthetic records with simulated source precedence |
| `evals/scenarios.jsonl` | 48 development scenarios, 63 turns |
| `evals/results/` | Executed historical before/after reports and hashes |
| `evals/baselines/pre_iteration.patch` | Historical code patch; requires a matching source snapshot |

Original customer cases, internal documents, private derived datasets and runtime databases are not included. Earlier private processing figures are not the public corpus size or results reproducible from this package.

When preparing private inputs, map message identifiers to `message_id`, redact personal data, review sources and validity, and evaluate the resulting corpus separately. Follow [knowledge preparation](operations.md). Source excerpts and private exports are not automatically uploaded.

