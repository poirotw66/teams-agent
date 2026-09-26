"""PDF bytes conversion and import-dict assembly for Knowledge Portal."""

from __future__ import annotations

import asyncio
import base64
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .draft_assets import rewrite_local_image_refs, slug_from_title
from .pdf_converter_client import PdfAsset, PdfConversionResult, PdfConverterClient
from .pdf_text import count_pdf_pages, extract_text_pdf, pdf_text_to_markdown
from .settings import PortalSettings


async def convert_via_document_ai(
    settings: PortalSettings,
    payload: bytes,
    *,
    filename: str,
) -> PdfConversionResult | None:
    if settings.document_parser != "DOCUMENT_AI":
        return None
    from knowledge_portal.ports.document_ai import get_pdf_layout_parser_factory

    parser = get_pdf_layout_parser_factory().create(
        settings.document_ai_processor_name or ""
    )
    parsed = await asyncio.to_thread(
        parser.parse_pdf,
        payload,
        title=Path(filename).stem,
    )
    markdown = "\n\n".join(
        f"## Page {page.page_number}\n\n" + "\n\n".join(block.text for block in page.blocks)
        for page in parsed.pages
    )
    return PdfConversionResult(
        markdown=markdown,
        page_count=len(parsed.pages),
        assets=await asyncio.to_thread(render_pdf_page_assets, payload),
        warnings=(
            "Converted via Document AI Layout Parser.",
            "Rendered PDF pages as indexed image assets.",
        ),
        raw={
            "conversion_mode": "document_ai",
            "conversion_engine": parser.name,
            "parser_version": parser.version,
        },
    )


async def convert_via_converter_service(
    settings: PortalSettings,
    payload: bytes,
    *,
    filename: str,
    fallback_warning: str | None = None,
) -> PdfConversionResult | None:
    if not settings.pdf_converter_url:
        return None
    client = PdfConverterClient(
        base_url=settings.pdf_converter_url,
        auth_mode=settings.pdf_converter_auth_mode,
        token=settings.pdf_converter_token,
        timeout_seconds=settings.pdf_converter_timeout_seconds,
        prompt_template=settings.pdf_prompt_template,
    )
    result = await client.convert_pdf(payload, filename=filename)
    pages = result.page_count
    if pages is None:
        try:
            pages = count_pdf_pages(payload)
        except Exception:  # noqa: BLE001 - page count is optional metadata
            pages = None
    warnings = result.warnings + ("Converted via PDF converter Cloud Run service.",)
    if fallback_warning:
        warnings += (fallback_warning,)
    engine = (settings.pdf_converter_engine or "gemini_vision").strip() or "gemini_vision"
    from knowledge_core.gemini_backend import peek_gemini_api_backend

    return PdfConversionResult(
        markdown=result.markdown,
        page_count=pages,
        assets=result.assets or await asyncio.to_thread(render_pdf_page_assets, payload),
        warnings=warnings
        + (() if result.assets else ("Rendered PDF pages as indexed image assets.",)),
        raw={
            **result.raw,
            "conversion_mode": "converter",
            "conversion_engine": engine,
            "conversion_gemini_backend": peek_gemini_api_backend().value,
        },
    )


async def convert_via_legacy_text(
    payload: bytes,
    *,
    filename: str,
    fallback_warning: str | None = None,
) -> PdfConversionResult:
    text, page_count = extract_text_pdf(payload)
    stem = Path(filename).stem.strip() or "PDF Document"
    assets = await asyncio.to_thread(render_pdf_page_assets, payload)
    return PdfConversionResult(
        markdown=pdf_text_to_markdown(text, stem),
        page_count=page_count,
        assets=assets,
        warnings=tuple(
            warning
            for warning in (
                "PDF converter URL is not configured; used legacy text extraction.",
                "Scanned or chart-heavy PDFs need KNOWLEDGE_PORTAL_PDF_CONVERTER_URL.",
                fallback_warning,
            )
            if warning
        ),
        raw={"conversion_mode": "legacy", "conversion_engine": "legacy_text"},
    )


async def convert_pdf_bytes(
    settings: PortalSettings,
    payload: bytes,
    *,
    filename: str,
) -> PdfConversionResult:
    fallback_warning: str | None = None
    if settings.document_parser == "DOCUMENT_AI":
        try:
            document_ai_result = await convert_via_document_ai(
                settings,
                payload,
                filename=filename,
            )
            if document_ai_result is not None:
                return document_ai_result
        except Exception as error:  # noqa: BLE001 - optional external parser boundary
            fallback_warning = (
                "Document AI parsing failed; the configured PDF converter "
                f"was used ({error.__class__.__name__})."
            )
    converter_result = await convert_via_converter_service(
        settings,
        payload,
        filename=filename,
        fallback_warning=fallback_warning,
    )
    if converter_result is not None:
        return converter_result
    return await convert_via_legacy_text(
        payload,
        filename=filename,
        fallback_warning=fallback_warning,
    )


def conversion_to_import_dict(
    result: PdfConversionResult,
    *,
    filename: str,
    owner_unit_id: str,
    original_asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stem = Path(filename).stem.strip() or "PDF Document"
    today = datetime.now(UTC).date().isoformat()
    assets = [
        {
            "filename": asset.filename,
            "content_base64": base64.b64encode(asset.content).decode("ascii"),
        }
        for asset in result.assets
    ]
    mode = str((result.raw or {}).get("conversion_mode") or "converter")
    engine = str((result.raw or {}).get("conversion_engine") or "unknown")
    backend = str((result.raw or {}).get("conversion_gemini_backend") or "").strip() or None
    asset_slug = slug_from_title(stem)
    markdown = rewrite_local_image_refs(
        ensure_asset_references(result.markdown, result.assets),
        asset_slug=asset_slug,
    )
    return {
        "title": stem,
        "owner_unit_id": owner_unit_id,
        "effective_at": today,
        "review_due_at": today,
        "audience_type": "ALL_EMPLOYEES",
        "audience_group_ids": [],
        "markdown_content": markdown,
        "asset_slug": asset_slug,
        "page_count": result.page_count or 0,
        "source_type": "PDF",
        "warnings": list(result.warnings),
        "conversion_mode": mode,
        "conversion_engine": engine,
        "conversion_gemini_backend": backend,
        "assets": assets,
        **(original_asset or {}),
    }


def render_pdf_page_assets(payload: bytes) -> tuple[PdfAsset, ...]:
    try:
        import pymupdf
    except ImportError as error:  # pragma: no cover - portal extra provides renderer
        raise RuntimeError("PyMuPDF is required to render indexed PDF images.") from error
    document = pymupdf.open(stream=payload, filetype="pdf")
    try:
        return tuple(
            PdfAsset(
                filename=f"p{page_index + 1:02d}.png",
                content=page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).tobytes(
                    "png"
                ),
            )
            for page_index, page in enumerate(document)
        )
    finally:
        document.close()


def ensure_asset_references(
    markdown: str,
    assets: tuple[PdfAsset, ...],
) -> str:
    missing = [
        asset
        for asset in assets
        if not re.search(
            rf"!\[[^\]]*\]\([^)]*{re.escape(asset.filename)}(?:\s+[^)]*)?\)",
            markdown,
        )
    ]
    if not missing:
        return markdown
    boundaries = page_boundaries(markdown)
    if not boundaries:
        return append_unplaced_evidence(markdown, missing)

    assets_by_page = {
        page_number: asset
        for asset in missing
        if (page_number := page_number_from_asset(asset)) is not None
    }
    placed: set[str] = set()
    sections = [markdown[: boundaries[0][0]].rstrip()]
    for index, (start, page_number) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(markdown)
        section = markdown[start:end].rstrip()
        asset = assets_by_page.get(page_number)
        if asset is not None:
            section = f"{section}\n\n![PDF page {page_number}](assets/{asset.filename})"
            placed.add(asset.filename)
        sections.append(section)
    positioned = "\n\n".join(section for section in sections if section)
    unplaced = [asset for asset in missing if asset.filename not in placed]
    return append_unplaced_evidence(positioned, unplaced)


def page_boundaries(markdown: str) -> list[tuple[int, int]]:
    source_maps = [
        (match.start(), int(match.group(1)) + 1)
        for match in re.finditer(
            r"<!--\s*source-map:[^>]*\bpage_index=(\d+)\b[^>]*-->",
            markdown,
            flags=re.IGNORECASE,
        )
    ]
    if source_maps:
        return source_maps
    return [
        (match.start(), int(match.group(1)))
        for match in re.finditer(
            r"(?m)^#{1,6}\s+Page\s+(\d+)\s*$",
            markdown,
            flags=re.IGNORECASE,
        )
    ]


def page_number_from_asset(asset: PdfAsset) -> int | None:
    match = re.fullmatch(r"p(\d+)\.(?:png|jpe?g|gif)", asset.filename, re.IGNORECASE)
    return int(match.group(1)) if match else None


def append_unplaced_evidence(
    markdown: str,
    assets: list[PdfAsset],
) -> str:
    if not assets:
        return f"{markdown.rstrip()}\n"
    evidence = "\n\n".join(
        f"## Visual Evidence — {asset.filename}\n\n"
        f"![PDF page {page_number_from_asset(asset) or index}](assets/{asset.filename})"
        for index, asset in enumerate(assets, 1)
    )
    return f"{markdown.rstrip()}\n\n{evidence}\n"
