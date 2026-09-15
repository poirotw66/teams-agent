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
# Portal-active Hybrid citations use releases/<id>/sources/doc--*.md paths.
# Without the release tree, Adapter mints OpenUrl links that 404 on open.
COPY data/releases ./data/releases

ENV RAG_SOURCE_DIR=/app/data \
    RAG_ASSET_DIR=/app/data/sources/assets

RUN pip install --no-cache-dir ".[gcs]"

USER 65532:65532

EXPOSE 8080

CMD ["python", "-m", "teams_agent.main"]
