FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPPORT_WEB_HOST=0.0.0.0 \
    SUPPORT_WEB_PORT=8080 \
    SUPPORT_AGENT_DB=/app/runtime/support_agent.db \
    SUPPORT_AGENT_CORPUS=/app/support_agent/demo/corpus.jsonl

WORKDIR /app

COPY pyproject.toml README.md ./
COPY support_agent ./support_agent

RUN pip install --no-cache-dir --no-deps . \
    && mkdir -p /app/runtime

EXPOSE 8080

VOLUME ["/app/runtime"]

CMD ["python", "-m", "support_agent.web"]
