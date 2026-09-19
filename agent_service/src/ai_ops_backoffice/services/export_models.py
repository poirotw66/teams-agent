"""Export job domain model, fingerprinting, and persistence serialization.

Kept separate from ``ExportJobService`` orchestration so store adapters and
tests can depend on the job contract without importing the full runner.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Literal

ExportJobStatus = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "EXPIRED"]
LEASE_SECONDS = 120
RECOVERY_SCAN_SECONDS = 30

from .job_payload_contracts import validate_export_request_params

__all__ = [
    "LEASE_SECONDS",
    "RECOVERY_SCAN_SECONDS",
    "ExportJob",
    "ExportJobStatus",
    "deserialize_export_job",
    "export_request_fingerprint",
    "serialize_export_job",
    "validate_export_request_params",
]


@dataclass
class ExportJob:
    job_id: str
    export_type: str
    export_format: str
    status: ExportJobStatus
    reason: str
    requested_by: str
    requested_role: str
    days: int
    created_at: str
    expires_at: str
    schema_version: int = 1
    tenant_id: str = "local-development"
    requested_owner_units: tuple[str, ...] = ()
    request_params: dict[str, Any] = field(default_factory=dict)
    request_fingerprint: str | None = None
    idempotency_key: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    lease_token: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    download_content: str | None = None
    download_bytes: bytes | None = None
    content_ref: str | None = None
    content_type: str | None = None
    error: str | None = None


def export_request_fingerprint(
    *,
    export_type: str,
    export_format: str,
    days: int,
    reason: str,
    request_params: dict[str, Any] | None,
) -> str:
    payload = {
        "export_type": export_type,
        "export_format": export_format,
        "days": days,
        "reason": reason,
        "request_params": request_params or {},
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def serialize_export_job(job: ExportJob) -> dict[str, Any]:
    payload = job.__dict__.copy()
    download_bytes = payload.pop("download_bytes", None)
    if download_bytes is not None:
        payload["download_bytes_b64"] = base64.b64encode(download_bytes).decode("ascii")
    payload["requested_owner_units"] = list(job.requested_owner_units)
    payload["request_params"] = dict(job.request_params or {})
    return payload


def deserialize_export_job(item: dict[str, Any]) -> ExportJob:
    defaults = {
        "schema_version": 1,
        "export_format": "json",
        "download_content": None,
        "download_bytes": None,
        "content_ref": None,
        "content_type": None,
        "tenant_id": "local-development",
        "requested_owner_units": (),
        "request_params": {},
        "request_fingerprint": None,
        "idempotency_key": None,
        "attempt_count": 0,
        "max_attempts": 3,
        "lease_owner": None,
        "lease_expires_at": None,
        "lease_token": None,
        "error": None,
        "result": None,
        "completed_at": None,
    }
    merged = {**defaults, **item}
    for key in ("created_at", "expires_at", "completed_at", "lease_expires_at"):
        if isinstance(merged.get(key), datetime):
            merged[key] = merged[key].isoformat()
    encoded = merged.pop("download_bytes_b64", None)
    if encoded:
        merged["download_bytes"] = base64.b64decode(encoded)
    units = merged.get("requested_owner_units") or ()
    merged["requested_owner_units"] = tuple(units)
    merged["request_params"] = dict(merged.get("request_params") or {})
    known = {item.name for item in fields(ExportJob)}
    return ExportJob(**{key: value for key, value in merged.items() if key in known})
