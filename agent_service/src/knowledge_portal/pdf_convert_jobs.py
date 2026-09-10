"""In-process PDF conversion job store for Knowledge Portal."""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from .draft_assets import rewrite_local_image_refs, slug_from_title
from .original_assets import OriginalAssetStore
from .pdf_converter_client import PdfConversionResult, PdfConverterClient
from .pdf_text import count_pdf_pages, extract_text_pdf, pdf_text_to_markdown
from .settings import PortalSettings

PdfJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]


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
    ) -> PdfConvertJob:
        now = datetime.now(UTC).isoformat()
        job = PdfConvertJob(
            job_id=f"pdfjob-{uuid.uuid4().hex[:12]}",
            status="QUEUED",
            filename=filename,
            created_at=now,
            updated_at=now,
            page_count=page_count,
            byte_size=len(payload),
            actor_id=actor_id,
            original_asset=original_asset,
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
            "error": job.error,
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
            job.updated_at = datetime.now(UTC).isoformat()
            self._persist(job)
            filename = job.filename
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
                job.result = public_result
                self._payloads.pop(job_id, None)
                self._persist(job)
        except Exception as exc:  # noqa: BLE001 - surface to job status
            OriginalAssetStore(self.settings).discard_pending(
                (job.original_asset or {}).get("original_asset_token")
            )
            with self._lock:
                job = self._jobs[job_id]
                job.status = "FAILED"
                job.updated_at = datetime.now(UTC).isoformat()
                job.error = str(exc)
                self._payloads.pop(job_id, None)
                self._persist(job)

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
    if page_count is not None and page_count > settings.pdf_sync_max_pages:
        return True
    return False


async def convert_pdf_bytes(
    settings: PortalSettings,
    payload: bytes,
    *,
    filename: str,
) -> PdfConversionResult:
    if settings.pdf_converter_url:
        client = PdfConverterClient(
            base_url=settings.pdf_converter_url,
            token=settings.pdf_converter_token,
            timeout_seconds=settings.pdf_converter_timeout_seconds,
            prompt_template=settings.pdf_prompt_template,
        )
        result = await client.convert_pdf(payload, filename=filename)
        pages = result.page_count
        if pages is None:
            try:
                pages = count_pdf_pages(payload)
            except Exception:
                pages = None
        warnings = result.warnings + ("Converted via PDF converter Cloud Run service.",)
        engine = (settings.pdf_converter_engine or "gemini_vision").strip() or "gemini_vision"
        return PdfConversionResult(
            markdown=result.markdown,
            page_count=pages,
            assets=result.assets,
            warnings=warnings,
            raw={
                **result.raw,
                "conversion_mode": "converter",
                "conversion_engine": engine,
            },
        )
    text, page_count = extract_text_pdf(payload)
    stem = Path(filename).stem.strip() or "PDF Document"
    return PdfConversionResult(
        markdown=pdf_text_to_markdown(text, stem),
        page_count=page_count,
        assets=(),
        warnings=(
            "PDF converter URL is not configured; used legacy text extraction.",
            "Scanned or chart-heavy PDFs need KNOWLEDGE_PORTAL_PDF_CONVERTER_URL.",
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
    today = date.today().isoformat()
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
    markdown = rewrite_local_image_refs(result.markdown, asset_slug=asset_slug)
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
