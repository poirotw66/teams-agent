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

# The 'firestore' extra ships the persistent Conversation Repository
# backend (spec §10.3). It is installed here because Cloud Run is exactly
# where CONVERSATION_REPOSITORY_MODE=MEMORY loses context on scale-to-zero;
# the extra stays optional for local MEMORY/FILE runs and for the tests.
RUN pip install --no-cache-dir "./agent_service[firestore]"

RUN mkdir -p /app/data/index \
    && chown -R 65532:65532 /app/data

USER 65532:65532

EXPOSE 8000

CMD ["python", "-m", "agent_service.main"]
