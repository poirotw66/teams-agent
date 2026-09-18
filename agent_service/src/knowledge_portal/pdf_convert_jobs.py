"""In-process PDF conversion job store for Knowledge Portal."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from .ingestion_jobs import IngestionStage
from .original_assets import OriginalAssetStore
from .pdf_convert_runner import conversion_to_import_dict, convert_pdf_bytes
from .settings import PortalSettings

PdfJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED"]
logger = logging.getLogger(__name__)

__all__ = [
    "PdfConvertJob",
    "PdfConvertJobStore",
    "PdfJobStatus",
    "conversion_to_import_dict",
    "convert_pdf_bytes",
    "idempotent_pdf_job_id",
    "should_convert_async",
]


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
