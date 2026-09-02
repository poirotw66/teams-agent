"""Text PDF extraction for Knowledge Portal governance."""

from __future__ import annotations

from io import BytesIO


class ScannedPdfError(ValueError):
    """Raised when a PDF has no extractable text (likely scanned)."""


def extract_text_pdf(payload: bytes, *, min_chars_per_page: int = 12) -> tuple[str, int]:
    """Extract text from a text-based PDF.

    Scanned PDFs without a text layer are rejected per Phase 1 scope (no OCR).
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("pypdf is required for PDF import") from exc

    reader = PdfReader(BytesIO(payload))
    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("PDF has no pages.")

    chunks: list[str] = []
    for page in reader.pages:
        page_text = (page.extract_text() or "").strip()
        if page_text:
            chunks.append(page_text)

    text = "\n\n".join(chunks).strip()
    if not text or len(text) < min(min_chars_per_page, min_chars_per_page * page_count):
        raise ScannedPdfError(
            "Scanned PDF is not supported. Upload a text-based PDF or convert with OCR first."
        )
    return text, page_count


def pdf_text_to_markdown(text: str, title: str) -> str:
    body = text.strip()
    return f"# {title}\n\n{body}\n"
