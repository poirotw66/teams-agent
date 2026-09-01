# The Microsoft Teams SDK (microsoft-teams-apps) requires Python >= 3.11.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY data/assets ./data/assets

RUN pip install --no-cache-dir .

USER 65532:65532

EXPOSE 8080

CMD ["python", "-m", "teams_agent.main"]
