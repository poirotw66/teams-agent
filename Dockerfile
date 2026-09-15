# The Microsoft Teams SDK (microsoft-teams-apps) requires Python >= 3.11.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
# Citation delivery reads Markdown under data/sources (and images under assets).
# Shipping only assets left Cloud Run /rag-sources 404 while local checkout worked.
COPY data/sources ./data/sources
# Release trees are optional for Adapter: originals are delivered via Backoffice
# Source API. Keep an empty releases dir so RAG_SOURCE_DIR layout stays stable.
RUN mkdir -p /app/data/releases

ENV RAG_SOURCE_DIR=/app/data \
    RAG_ASSET_DIR=/app/data/sources/assets

RUN pip install --no-cache-dir ".[gcs]"

USER 65532:65532

EXPOSE 8080

CMD ["python", "-m", "teams_agent.main"]
