"""Cloud-backed PDF conversion jobs for multi-instance Portal deployments."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from .original_assets import OriginalAssetStore
from .pdf_convert_jobs import (
    PdfConvertJob,
    PdfConvertJobStore,
    conversion_to_import_dict,
    convert_pdf_bytes,
)
from .pdf_staging import GcsPdfStagingStore, build_gcs_pdf_staging_store
from .settings import PortalSettings

logger = logging.getLogger(__name__)
_JOB_ID_PATTERN = re.compile(r"^pdfjob-[0-9a-f]{12}$")


class PersistentPdfConvertJobStore:
    """Persist job state in Firestore and large payloads/results in GCS."""

    def __init__(
        self,
        settings: PortalSettings,
        *,
        firestore_client: Any,
        staging_store: GcsPdfStagingStore,
    ) -> None:
        self.settings = settings
        self._client = firestore_client
        self._staging = staging_store
        self._collection = self._client.collection(f"{settings.config_collection}_pdf_jobs")
        self._scheduled: set[str] = set()
        self._lock = threading.Lock()

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
        self._staging.store_job_payload(job.job_id, payload)
        try:
            self._save(job)
        except Exception:
            self._staging.delete_job_payload(job.job_id)
            raise
        return job

    def get(self, job_id: str) -> PdfConvertJob | None:
        if not _JOB_ID_PATTERN.fullmatch(job_id):
            return None
        snapshot = self._collection.document(job_id).get()
        payload = snapshot.to_dict() if snapshot.exists else None
        if payload is None:
            return None
        has_result = bool(payload.pop("has_result", False))
        job = PdfConvertJob(**payload)
        if has_result and job.status == "COMPLETED":
            job.result = self._staging.load_job_result(job.job_id)
        return job

    @staticmethod
    def to_public_dict(job: PdfConvertJob) -> dict[str, Any]:
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
        if not _JOB_ID_PATTERN.fullmatch(job_id):
            return
        if not self._mark_scheduled(job_id):
            return
        if background_tasks is not None:
            background_tasks.add_task(self._run_and_unmark, job_id)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._run_and_unmark(job_id))
            return
        loop.create_task(self._run_and_unmark(job_id))

    def resume(
        self,
        job: PdfConvertJob,
        background_tasks: Any | None = None,
    ) -> None:
        if job.status == "QUEUED" or self._is_stale(job):
            self.schedule(job.job_id, background_tasks)

    async def _run_and_unmark(self, job_id: str) -> None:
        try:
            await self._run(job_id)
        finally:
            with self._lock:
                self._scheduled.discard(job_id)

    async def _run(self, job_id: str) -> None:
        job = self._claim(job_id)
        if job is None:
            return
        try:
            payload = self._staging.load_job_payload(job_id)
            result = await convert_pdf_bytes(
                self.settings,
                payload,
                filename=job.filename,
            )
            public_result = conversion_to_import_dict(
                result,
                filename=job.filename,
                owner_unit_id=self.settings.default_owner_unit_id,
                original_asset=job.original_asset,
            )
            self._staging.store_job_result(job_id, public_result)
            job.status = "COMPLETED"
            job.updated_at = datetime.now(UTC).isoformat()
            job.page_count = public_result.get("page_count") or job.page_count
            job.mode = str(public_result.get("conversion_mode") or job.mode)
            job.result = public_result
            self._save(job, has_result=True)
            self._delete_payload_safely(job_id)
        except Exception as exc:  # noqa: BLE001 - failure is persisted for polling
            self._discard_original_safely(job)
            job.status = "FAILED"
            job.updated_at = datetime.now(UTC).isoformat()
            job.error = str(exc)
            job.result = None
            self._save(job)
            self._delete_payload_safely(job_id)

    def _claim(self, job_id: str) -> PdfConvertJob | None:
        reference = self._collection.document(job_id)
        for _ in range(3):
            transaction = self._client.transaction()
            try:
                if hasattr(transaction, "_begin"):
                    from google.cloud import firestore

                    @firestore.transactional
                    def claim_in_firestore(active_transaction: Any) -> PdfConvertJob | None:
                        return self._claim_in_transaction(active_transaction, reference)

                    return claim_in_firestore(transaction)
                job = self._claim_in_transaction(transaction, reference)
                transaction.commit()
                return job
            except Exception as exc:  # transaction conflicts are transient
                logger.warning("PDF job claim retry for %s: %s", job_id, exc)
        return None

    def _claim_in_transaction(
        self,
        transaction: Any,
        reference: Any,
    ) -> PdfConvertJob | None:
        snapshot = reference.get(transaction=transaction)
        payload = snapshot.to_dict() if snapshot.exists else None
        if payload is None:
            return None
        payload.pop("has_result", None)
        job = PdfConvertJob(**payload)
        if job.status != "QUEUED" and not self._is_stale(job):
            return None
        job.status = "RUNNING"
        job.updated_at = datetime.now(UTC).isoformat()
        transaction.set(reference, self._serialize(job))
        return job

    def _save(self, job: PdfConvertJob, *, has_result: bool = False) -> None:
        self._collection.document(job.job_id).set(self._serialize(job, has_result=has_result))

    @staticmethod
    def _serialize(
        job: PdfConvertJob,
        *,
        has_result: bool = False,
    ) -> dict[str, Any]:
        payload = asdict(job)
        payload["result"] = None
        payload["has_result"] = has_result
        return payload

    def _is_stale(self, job: PdfConvertJob) -> bool:
        if job.status != "RUNNING":
            return False
        try:
            updated_at = datetime.fromisoformat(job.updated_at)
        except ValueError:
            return True
        threshold = timedelta(seconds=max(60.0, self.settings.pdf_converter_timeout_seconds + 30.0))
        return datetime.now(UTC) - updated_at > threshold

    def _mark_scheduled(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._scheduled:
                return False
            self._scheduled.add(job_id)
            return True

    def _discard_original_safely(self, job: PdfConvertJob) -> None:
        token = (job.original_asset or {}).get("original_asset_token")
        try:
            OriginalAssetStore(self.settings).discard_pending(token)
        except Exception as exc:  # cleanup must not hide converter failure
            logger.warning("Failed to discard original for PDF job %s: %s", job.job_id, exc)

    def _delete_payload_safely(self, job_id: str) -> None:
        try:
            self._staging.delete_job_payload(job_id)
        except Exception as exc:
            logger.warning("Failed to delete PDF payload for job %s: %s", job_id, exc)


def build_pdf_convert_job_store(
    settings: PortalSettings,
    *,
    firestore_client: Any | None = None,
    staging_store: GcsPdfStagingStore | None = None,
) -> PdfConvertJobStore | PersistentPdfConvertJobStore:
    is_cloud_backed = (
        settings.repository_mode.upper() == "FIRESTORE"
        and settings.artifact_storage_backend.upper() == "GCS"
    )
    if not is_cloud_backed:
        return PdfConvertJobStore(settings)
    if firestore_client is None:
        from agent_service.operations.stores.firestore_store import (
            build_sync_firestore_client,
        )

        firestore_client = build_sync_firestore_client(
            settings.firestore_project_id,
            settings.firestore_database_id,
        )
    return PersistentPdfConvertJobStore(
        settings,
        firestore_client=firestore_client,
        staging_store=staging_store or build_gcs_pdf_staging_store(settings),
    )
