# Default image: lightweight API-compatible shim for Portal integration.
# For full PyMuPDF + Gemini Vision capability, use Dockerfile.upstream instead.
FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx python-multipart pypdf

ENV PORT=8080
ENV PDF_CONVERTER_MODE=legacy
ENV PYTHONPATH=/app
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
