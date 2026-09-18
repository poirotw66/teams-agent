"""In-process PDF conversion job store for Knowledge Portal."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .draft_assets import rewrite_local_image_refs, slug_from_title
from .ingestion_jobs import IngestionStage
from .original_assets import OriginalAssetStore
from .pdf_converter_client import PdfAsset, PdfConversionResult, PdfConverterClient
from .pdf_text import count_pdf_pages, extract_text_pdf, pdf_text_to_markdown
from .settings import PortalSettings

PdfJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
logger = logging.getLogger(__name__)


@dataclass
class PdfConvertJob:
    job_id: str
    status: PdfJobStatus
    filename: str
    created_at: str
    updated_at: str
    page_count: int | None = None
    byte_size: int = 0
    mode: str = "converter"
    error: str | None = None
    result: dict[str, Any] | None = None
    actor_id: str | None = None
    original_asset: dict[str, Any] | None = None
    ingestion_stage: IngestionStage = IngestionStage.UPLOADED
    attempt: int = 0
    correlation_id: str | None = None
    idempotency_key: str | None = None
    payload_sha256: str | None = None
    parser_version: str = "pdf-converter-v1"
    chunker_version: str = "layout-v1"
    error_code: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.ingestion_stage, str):
            self.ingestion_stage = IngestionStage(self.ingestion_stage)


@dataclass
class PdfConvertJobStore:
    settings: PortalSettings
    _jobs: dict[str, PdfConvertJob] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _payloads: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.settings.pdf_jobs_dir is not None:
            self.settings.pdf_jobs_dir.mkdir(parents=True, exist_ok=True)

    def create_job(
        self,
        *,
        payload: bytes,
        filename: str,
        actor_id: str | None,
        page_count: int | None,
        original_asset: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> PdfConvertJob:
        now = datetime.now(UTC).isoformat()
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        job_id = (
            idempotent_pdf_job_id(actor_id, idempotency_key)
            if idempotency_key
            else f"pdfjob-{uuid.uuid4().hex[:12]}"
        )
        existing = self.get(job_id) if idempotency_key else None
        if existing is not None:
            if existing.payload_sha256 != payload_sha256:
                raise ValueError("Idempotency key was reused with different PDF content.")
            OriginalAssetStore(self.settings).discard_pending(
                (original_asset or {}).get("original_asset_token")
            )
            return existing
        job = PdfConvertJob(
            job_id=job_id,
            status="QUEUED",
            filename=filename,
            created_at=now,
            updated_at=now,
            page_count=page_count,
            byte_size=len(payload),
            actor_id=actor_id,
            original_asset=original_asset,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._payloads[job.job_id] = payload
            self._persist(job)
        return job

    def get(self, job_id: str) -> PdfConvertJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return job
        return self._load(job_id)

    def cancel(self, job_id: str, *, actor_id: str) -> PdfConvertJob:
        job = self.get(job_id)
        if job is None or (job.actor_id and job.actor_id != actor_id):
            raise ValueError("PDF job not found.")
        with self._lock:
            if job.status != "QUEUED":
                raise ValueError("Only queued PDF jobs can be cancelled.")
            job.status = "FAILED"
            job.ingestion_stage = IngestionStage.CANCELLED
            job.error_code = "INGESTION_CANCELLED"
            job.error = "Ingestion was cancelled by the requester."
            job.updated_at = datetime.now(UTC).isoformat()
            self._payloads.pop(job_id, None)
            self._persist(job)
        return job

    def to_public_dict(self, job: PdfConvertJob) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jobId": job.job_id,
            "status": job.status,
            "filename": job.filename,
            "createdAt": job.created_at,
            "updatedAt": job.updated_at,
            "pageCount": job.page_count,
            "byteSize": job.byte_size,
            "mode": job.mode,
            "error": (
                "PDF conversion failed. Review the error code and retry."
                if job.status == "FAILED"
                else None
            ),
            "stage": job.ingestion_stage.value,
            "attempt": job.attempt,
            "correlationId": job.correlation_id,
            "parserVersion": job.parser_version,
            "chunkerVersion": job.chunker_version,
            "errorCode": job.error_code,
        }
        if job.status == "COMPLETED" and job.result is not None:
            payload["result"] = job.result
        return payload

    def schedule(self, job_id: str, background_tasks: Any | None = None) -> None:
        if background_tasks is not None:
            background_tasks.add_task(self._run, job_id)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._run(job_id))
            return
        loop.create_task(self._run(job_id))

    async def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            payload = self._payloads.get(job_id)
            if job is None or payload is None:
                return
            job.status = "RUNNING"
            job.ingestion_stage = IngestionStage.PARSING
            job.attempt += 1
            job.updated_at = datetime.now(UTC).isoformat()
            self._persist(job)
            filename = job.filename
            logger.info(
                "ingestion_stage job_id=%s stage=%s attempt=%s correlation_id=%s",
                job.job_id,
                job.ingestion_stage.value,
                job.attempt,
                job.correlation_id,
            )
        try:
            result = await convert_pdf_bytes(self.settings, payload, filename=filename)
            public_result = conversion_to_import_dict(
                result,
                filename=filename,
                owner_unit_id=self.settings.default_owner_unit_id,
                original_asset=job.original_asset,
            )
            with self._lock:
                job = self._jobs[job_id]
                job.status = "COMPLETED"
                job.updated_at = datetime.now(UTC).isoformat()
                job.page_count = public_result.get("page_count") or job.page_count
                job.mode = str(public_result.get("conversion_mode") or job.mode)
                job.ingestion_stage = IngestionStage.CHUNK_REVIEW
                job.result = public_result
                self._payloads.pop(job_id, None)
                self._persist(job)
                logger.info(
                    "ingestion_stage job_id=%s stage=%s attempt=%s",
                    job.job_id,
                    job.ingestion_stage.value,
                    job.attempt,
                )
        except Exception as exc:
            OriginalAssetStore(self.settings).discard_pending(
                (job.original_asset or {}).get("original_asset_token")
            )
            with self._lock:
                job = self._jobs[job_id]
                job.status = "FAILED"
                job.updated_at = datetime.now(UTC).isoformat()
                job.error = str(exc)
                job.error_code = "PDF_CONVERSION_FAILED"
                job.ingestion_stage = IngestionStage.FAILED
                self._payloads.pop(job_id, None)
                self._persist(job)
                logger.exception(
                    "ingestion_failed job_id=%s error_code=%s attempt=%s",
                    job.job_id,
                    job.error_code,
                    job.attempt,
                )

    def _persist(self, job: PdfConvertJob) -> None:
        root = self.settings.pdf_jobs_dir
        if root is None:
            return
        path = root / f"{job.job_id}.json"
        path.write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self, job_id: str) -> PdfConvertJob | None:
        root = self.settings.pdf_jobs_dir
        if root is None:
            return None
        path = root / f"{job_id}.json"
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        job = PdfConvertJob(**raw)
        with self._lock:
            self._jobs[job_id] = job
        return job


def should_convert_async(
    settings: PortalSettings,
    *,
    byte_size: int,
    page_count: int | None,
    force: str | None = None,
) -> bool:
    mode = (force or "auto").strip().lower()
    if mode in {"true", "1", "yes", "async"}:
        return True
    if mode in {"false", "0", "no", "sync"}:
        return False
    if byte_size > settings.pdf_sync_max_bytes:
        return True
    return page_count is not None and page_count > settings.pdf_sync_max_pages


def idempotent_pdf_job_id(actor_id: str | None, idempotency_key: str) -> str:
    digest = hashlib.sha256(f"{actor_id or 'anonymous'}::{idempotency_key}".encode()).hexdigest()
    return f"pdfjob-{digest[:12]}"


async def convert_pdf_bytes(
    settings: PortalSettings,
    payload: bytes,
    *,
    filename: str,
) -> PdfConversionResult:
    fallback_warning: str | None = None
    if settings.document_parser == "DOCUMENT_AI":
        from knowledge_portal.ports.document_ai import get_pdf_layout_parser_factory

        try:
            parser = get_pdf_layout_parser_factory().create(settings.document_ai_processor_name or "")
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
        except Exception as error:  # noqa: BLE001 - optional external parser boundary
            fallback_warning = (
                "Document AI parsing failed; the configured PDF converter "
                f"was used ({error.__class__.__name__})."
            )
    if settings.pdf_converter_url:
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
            },
        )
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
    asset_slug = slug_from_title(stem)
    markdown = rewrite_local_image_refs(
        _ensure_asset_references(result.markdown, result.assets),
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


def _ensure_asset_references(
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
    boundaries = _page_boundaries(markdown)
    if not boundaries:
        return _append_unplaced_evidence(markdown, missing)

    assets_by_page = {
        page_number: asset
        for asset in missing
        if (page_number := _page_number_from_asset(asset)) is not None
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
    return _append_unplaced_evidence(positioned, unplaced)


def _page_boundaries(markdown: str) -> list[tuple[int, int]]:
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


def _page_number_from_asset(asset: PdfAsset) -> int | None:
    match = re.fullmatch(r"p(\d+)\.(?:png|jpe?g|gif)", asset.filename, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _append_unplaced_evidence(
    markdown: str,
    assets: list[PdfAsset],
) -> str:
    if not assets:
        return f"{markdown.rstrip()}\n"
    evidence = "\n\n".join(
        f"## Visual Evidence — {asset.filename}\n\n"
        f"![PDF page {_page_number_from_asset(asset) or index}](assets/{asset.filename})"
        for index, asset in enumerate(assets, 1)
    )
    return f"{markdown.rstrip()}\n\n{evidence}\n"
