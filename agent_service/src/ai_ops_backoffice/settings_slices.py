"""Domain configuration slices (Milestone 3: Nested Immutable Configuration).

Decomposes monolithic BackofficeSettings into cohesive domain slices,
following Law of Demeter and least-knowledge principles.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuthSettings:
    """Authentication and identity tenant configuration."""

    auth_mode: str
    service_token: str
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    default_owner_unit_id: str = "IT Service Desk"


@dataclass(frozen=True)
class KnowledgeBridgeSettings:
    """Knowledge Portal BFF bridge configuration."""

    enabled: bool = True
    in_process: bool = True
    portal_url: str = ""
    internal_url: str = ""
    service_token: str = ""
    delegation_secret: str = ""
    source_delegation_secret: str = ""
    auth_mode: str = "BEARER"
    timeout_seconds: float = 180.0


@dataclass(frozen=True)
class NotificationSettings:
    """Outbound alerting and notification channel configuration."""

    targets: tuple[str, ...] = ("notification-center=NOTIFICATION_CENTER",)
    teams_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ai-ops@example.com"


@dataclass(frozen=True)
class ExportJobSettings:
    """Background export job persistence and artifact storage configuration."""

    store_mode: str = "FILE"
    collection: str = "ai_ops_export_jobs"
    content_backend: str = "FILE"
    content_path: Path | None = None
    gcs_bucket: str | None = None
    ttl_seconds: int = 86400
    max_records: int = 100_000
    worker_lease_seconds: int = 60
    worker_max_attempts: int = 3
