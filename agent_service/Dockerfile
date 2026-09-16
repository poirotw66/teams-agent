FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_NO_CACHE=1 \
    PATH=/app/.venv/bin:$PATH \
    HOST=0.0.0.0 \
    PORT=8000 \
    RAG_DATA_DIR=/app/data \
    RAG_INDEX_PATH=/app/data/index/chunks.json

WORKDIR /app

RUN pip install --no-cache-dir uv==0.8.15
COPY agent_service/pyproject.toml agent_service/uv.lock agent_service/README.md ./agent_service/
RUN uv sync \
    --project agent_service \
    --frozen \
    --no-dev \
    --no-install-project \
    --extra firestore \
    --extra bigquery \
    --extra portal

COPY agent_service/src ./agent_service/src
RUN uv sync \
    --project agent_service \
    --frozen \
    --no-dev \
    --extra firestore \
    --extra bigquery \
    --extra portal

# Runtime configuration remains image-owned; knowledge releases are fetched
# from GCS and are intentionally excluded from this application image.
COPY data/faq.json ./data/faq.json
COPY data/ops ./data/ops
RUN mkdir -p /app/data/index \
    && chown -R 65532:65532 /app/data

USER 65532:65532

EXPOSE 8000

CMD ["python", "-m", "agent_service.main"]
