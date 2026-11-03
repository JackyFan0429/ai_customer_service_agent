# Legacy standalone RAG demo

[Current portal](../../README.md) · [Chinese](README.zh-CN.md)

This earlier entrypoint demonstrates evidence retrieval and response policy using **19 synthetic records**. It has no portal accounts, business database tools or ticket workbench. The current portal is started by `scripts/start_demo.py`.

## Run locally

From the project root, with Python 3.11+:

```bash
python3 -m support_agent.web --provider local --host 127.0.0.1 --port 8081
```

Open [http://127.0.0.1:8081](http://127.0.0.1:8081). The standalone web demo has no authentication and is intended for loopback use. Its SQLite conversations are separate from the portal database.

For one CLI query:

```bash
python3 -m support_agent.cli --provider local --json "ClientA Base URL"
```

The result should use route `answer` and cite `demo:setup`. Knowledge and replies are in Chinese. CLI history is process-local; web history persists.

## Evaluation and import

```bash
python3 scripts/evaluate_agent.py --provider local --output runtime/legacy-evaluation.json --fail-on-regression evals/results/after.json
```

Expected: **48/48 scenarios, 63/63 turns**. These are synthetic development checks, not customer-resolution statistics.

[Architecture](architecture.md) · [Knowledge preparation](operations.md) · [Evaluation](evaluation.md) · [Response policy](safety.md) · [Data scope](data_scope.md)

The root Docker Compose configuration starts the **current portal**, not this legacy server. For interactive model setup, use the [current portal guide](../operations.md#model-connection); its three-stage startup check is not a feature of this old entrypoint.

