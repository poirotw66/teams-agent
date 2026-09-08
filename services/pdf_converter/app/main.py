"""PDF-to-Markdown converter Cloud Run service (API-compatible shim + upstream deploy).

Production should prefer building from:
https://github.com/poirotw66/pdf-to-markdown-converter

This in-repo service provides:
- Matching POST /api/v1/convert-pdf contract for Portal integration tests
- Optional LEGACY text extraction when Gemini upstream is unavailable
- Health endpoints for Cloud Run
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

app = FastAPI(title="PDF to Markdown Converter", version="1.0.0")


def _authorize(authorization: str | None) -> None:
    expected = (os.environ.get("PDF_CONVERTER_TOKEN") or "").strip()
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "pdf-to-markdown-converter",
        "upstream": "https://github.com/poirotw66/pdf-to-markdown-converter",
        "mode": os.environ.get("PDF_CONVERTER_MODE", "legacy"),
    }


@app.post("/api/v1/convert-pdf")
async def convert_pdf(
    file: UploadFile = File(...),
    prompt_template: str = Form(default="slide"),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    del prompt_template
    _authorize(authorization)
    payload = await file.read()
    max_mb = float(os.environ.get("PDF_MAX_UPLOAD_SIZE_MB", "25"))
    if len(payload) > int(max_mb * 1024 * 1024):
        raise HTTPException(status_code=413, detail=f"PDF exceeds {max_mb} MB limit")

    mode = (os.environ.get("PDF_CONVERTER_MODE") or "legacy").lower()
    if mode == "upstream_http":
        return JSONResponse(await _forward_upstream(payload, file.filename or "document.pdf"))

    markdown, page_count, warnings = _legacy_convert(payload, file.filename or "document.pdf")
    return JSONResponse(
        {
            "markdown": markdown,
            "page_count": page_count,
            "warnings": warnings,
            "assets": [],
        }
    )


async def _forward_upstream(payload: bytes, filename: str) -> dict[str, Any]:
    import httpx

    upstream = (os.environ.get("PDF_CONVERTER_UPSTREAM_URL") or "").rstrip("/")
    if not upstream:
        raise HTTPException(status_code=500, detail="PDF_CONVERTER_UPSTREAM_URL is not set")
    headers = {}
    token = (os.environ.get("PDF_CONVERTER_UPSTREAM_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=float(os.environ.get("PDF_CONVERTER_TIMEOUT", "120"))) as client:
        response = await client.post(
            f"{upstream}/api/v1/convert-pdf",
            headers=headers,
            files={"file": (filename, payload, "application/pdf")},
            data={"prompt_template": os.environ.get("PDF_PROMPT_TEMPLATE", "slide")},
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=response.text[:500])
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        data = response.json()
        if isinstance(data, dict):
            return data
    text = response.text
    return {"markdown": text, "page_count": None, "warnings": ["upstream raw response"], "assets": []}


def _legacy_convert(payload: bytes, filename: str) -> tuple[str, int, list[str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail="pypdf is required") from exc

    reader = PdfReader(BytesIO(payload))
    page_count = len(reader.pages)
    chunks: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if text:
            chunks.append(text)
    body = "\n\n".join(chunks).strip()
    if not body:
        raise HTTPException(
            status_code=422,
            detail=(
                "No extractable text. Deploy the full upstream converter image "
                "(PyMuPDF + Gemini Vision) for scanned/visual PDFs."
            ),
        )
    stem = filename.rsplit("/", 1)[-1]
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = stem.strip() or "PDF Document"
    markdown = f"# {stem}\n\n{body}\n"
    return markdown, page_count, [
        "Converted with legacy text extraction shim.",
        "For production OCR/vision, build Cloud Run from poirotw66/pdf-to-markdown-converter.",
    ]


def create_app() -> FastAPI:
    return app
