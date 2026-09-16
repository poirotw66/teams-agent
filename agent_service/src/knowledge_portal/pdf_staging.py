"""Durable staging storage for PDF imports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from .settings import PortalSettings

_STAGING_PREFIX = "knowledge-portal/pdf-staging"


@dataclass(frozen=True)
class StagedOriginal:
    payload: bytes
    metadata: dict[str, Any]


class OriginalStagingStore(Protocol):
    def store(self, token: str, payload: bytes, metadata: dict[str, Any]) -> None: ...

    def load(self, token: str) -> StagedOriginal: ...

    def delete(self, token: str) -> None: ...


class GcsPdfStagingStore:
    """Store pending originals and conversion payloads in a private GCS bucket."""

    def __init__(
        self,
        *,
        bucket_name: str,
        tenant_id: str,
        client: Any,
    ) -> None:
        if not bucket_name:
            raise ValueError("A GCS bucket is required for durable PDF staging.")
        if client is None:
            raise ValueError("A GCS client is required for durable PDF staging.")
        self._bucket = client.bucket(bucket_name)
        self._tenant_id = tenant_id

    def _original_prefix(self, token: str) -> str:
        return f"{_STAGING_PREFIX}/{self._tenant_id}/originals/{token}"

    def _job_payload_key(self, job_id: str) -> str:
        return f"{_STAGING_PREFIX}/{self._tenant_id}/jobs/{job_id}/payload"

    def _job_result_key(self, job_id: str) -> str:
        return f"{_STAGING_PREFIX}/{self._tenant_id}/jobs/{job_id}/result.json"

    def store(self, token: str, payload: bytes, metadata: dict[str, Any]) -> None:
        prefix = self._original_prefix(token)
        payload_blob = self._bucket.blob(f"{prefix}/payload")
        payload_blob.metadata = {"sha256": hashlib.sha256(payload).hexdigest()}
        payload_blob.upload_from_string(
            payload,
            content_type=str(metadata.get("content_type") or "application/pdf"),
        )
        try:
            self._bucket.blob(f"{prefix}/metadata.json").upload_from_string(
                json.dumps(metadata, ensure_ascii=False),
                content_type="application/json",
            )
        except Exception:
            payload_blob.delete()
            raise

    def load(self, token: str) -> StagedOriginal:
        prefix = self._original_prefix(token)
        try:
            metadata_payload = self._bucket.blob(f"{prefix}/metadata.json").download_as_bytes()
            payload = self._bucket.blob(f"{prefix}/payload").download_as_bytes()
        except Exception as exc:
            raise ValueError("Original asset upload has expired or is unavailable.") from exc
        metadata = json.loads(metadata_payload.decode("utf-8"))
        if not isinstance(metadata, dict) or metadata.get("token") != token:
            raise ValueError("Original asset metadata is invalid.")
        expected_hash = str(metadata.get("sha256") or "")
        if expected_hash and hashlib.sha256(payload).hexdigest() != expected_hash:
            raise ValueError("Original asset payload failed integrity verification.")
        return StagedOriginal(payload=payload, metadata=metadata)

    def delete(self, token: str) -> None:
        prefix = self._original_prefix(token)
        for suffix in ("payload", "metadata.json"):
            blob = self._bucket.blob(f"{prefix}/{suffix}")
            try:
                blob.delete()
            except Exception as exc:
                if not _is_not_found(exc):
                    raise

    def store_job_payload(self, job_id: str, payload: bytes) -> None:
        blob = self._bucket.blob(self._job_payload_key(job_id))
        blob.metadata = {"sha256": hashlib.sha256(payload).hexdigest()}
        blob.upload_from_string(payload, content_type="application/pdf")

    def load_job_payload(self, job_id: str) -> bytes:
        blob = self._bucket.blob(self._job_payload_key(job_id))
        payload = blob.download_as_bytes()
        expected_hash = str((getattr(blob, "metadata", None) or {}).get("sha256") or "")
        if expected_hash and hashlib.sha256(payload).hexdigest() != expected_hash:
            raise ValueError("PDF conversion payload failed integrity verification.")
        return payload

    def delete_job_payload(self, job_id: str) -> None:
        try:
            self._bucket.blob(self._job_payload_key(job_id)).delete()
        except Exception as exc:
            if not _is_not_found(exc):
                raise

    def store_job_result(self, job_id: str, result: dict[str, Any]) -> None:
        payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
        blob = self._bucket.blob(self._job_result_key(job_id))
        blob.metadata = {"sha256": hashlib.sha256(payload).hexdigest()}
        blob.upload_from_string(
            payload,
            content_type="application/json",
        )

    def load_job_result(self, job_id: str) -> dict[str, Any]:
        blob = self._bucket.blob(self._job_result_key(job_id))
        payload = blob.download_as_bytes()
        expected_hash = str((getattr(blob, "metadata", None) or {}).get("sha256") or "")
        if expected_hash and hashlib.sha256(payload).hexdigest() != expected_hash:
            raise ValueError("PDF conversion result failed integrity verification.")
        result = json.loads(payload.decode("utf-8"))
        if not isinstance(result, dict):
            raise TypeError("Persisted PDF conversion result must be an object.")
        return result


def build_gcs_pdf_staging_store(
    settings: PortalSettings,
    *,
    client: Any | None = None,
) -> GcsPdfStagingStore:
    bucket = settings.artifact_gcs_bucket
    if not bucket:
        raise ValueError(
            "KNOWLEDGE_PORTAL_ARTIFACT_GCS_BUCKET (or AI_OPS_ARTIFACT_GCS_BUCKET) "
            "is required for GCS PDF staging."
        )
    if client is None:
        from agent_service.artifact_storage import build_gcs_storage_client

        client = build_gcs_storage_client()
    return GcsPdfStagingStore(
        bucket_name=bucket,
        tenant_id=settings.default_tenant_id or "default",
        client=client,
    )


def _is_not_found(error: Exception) -> bool:
    return (
        error.__class__.__name__ in {"NotFound", "NoSuchKey"} or getattr(error, "code", None) == 404
    )
