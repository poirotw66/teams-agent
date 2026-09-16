# The Microsoft Teams SDK (microsoft-teams-apps) requires Python >= 3.11.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_NO_CACHE=1 \
    PATH=/app/.venv/bin:$PATH \
    PORT=8080

WORKDIR /app

RUN pip install --no-cache-dir uv==0.8.15
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra gcs

COPY src ./src
RUN uv sync --frozen --no-dev --extra gcs

# Citation originals are served through the governed Source API. The Adapter
# image contains no knowledge corpus or mutable release tree.
RUN mkdir -p /app/data/releases /app/data/sources/assets \
    && chown -R 65532:65532 /app/data

ENV RAG_SOURCE_DIR=/app/data \
    RAG_ASSET_DIR=/app/data/sources/assets

USER 65532:65532

EXPOSE 8080

CMD ["python", "-m", "teams_agent.main"]
