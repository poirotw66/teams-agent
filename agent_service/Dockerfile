FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    RAG_DATA_DIR=/app/data \
    RAG_INDEX_PATH=/app/data/index/chunks.json

WORKDIR /app

COPY agent_service/pyproject.toml agent_service/README.md ./agent_service/
COPY agent_service/src ./agent_service/src
COPY data ./data

RUN pip install --no-cache-dir ./agent_service

RUN mkdir -p /app/data/index \
    && chown -R 65532:65532 /app/data

USER 65532:65532

EXPOSE 8000

CMD ["python", "-m", "agent_service.main"]
