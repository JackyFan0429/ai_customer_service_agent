FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KRILL_WEB_HOST=0.0.0.0 \
    KRILL_WEB_PORT=8080 \
    KRILL_AGENT_DB=/app/runtime/krill_agent.db \
    KRILL_AGENT_CORPUS=/app/data/output/retrieval/retrieval_corpus.jsonl

WORKDIR /app

COPY pyproject.toml README.md ./
COPY krill_agent ./krill_agent
COPY data/output/retrieval/retrieval_corpus.jsonl ./data/output/retrieval/retrieval_corpus.jsonl

RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /app/runtime

EXPOSE 8080

VOLUME ["/app/runtime"]

CMD ["python", "-m", "krill_agent.web"]
