"""Settings contract for citation/asset gateway without depending on teams_agent."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class CitationGatewaySettings(Protocol):
    """Structural settings surface consumed by citation_asset_gateway."""

    api_token: str | None
    asset_dir: Path | None
    source_dir: Path | None
    public_base_url: str | None
    asset_signing_key: str | None
    asset_url_ttl_seconds: int
    asset_max_dimension: int
    asset_max_bytes: int
    asset_gcs_bucket: str | None
    asset_gcs_prefix: str
    asset_gcs_tenant_id: str
    client_id: str | None
    client_secret: str | None
    tenant_id: str | None
    allow_unauthenticated_requests: bool
    source_api_base_url: str | None
    source_api_token: str | None
    source_delegation_secret: str | None
    source_api_timeout_seconds: float

    @property
    def images_ready(self) -> bool: ...

    @property
    def sources_ready(self) -> bool: ...

    @property
    def source_api_ready(self) -> bool: ...
