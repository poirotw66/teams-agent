"""Release activation policy checks shared by publish, rollback, and promote.

Extracted from ``ReleaseService._require_release_allowed`` so the service
facade can delegate without changing error messages or failure modes.
"""

from __future__ import annotations

from knowledge_portal.models import ReleaseRecord
from knowledge_portal.rbac import PortalPermissionError


def require_release_allowed(
    release: ReleaseRecord,
    *,
    deployment_environment: str,
    release_gcs_bucket: str | None,
    require_verified: bool = False,
) -> None:
    """Raise ``PortalPermissionError`` when a release may not be activated."""
    if deployment_environment == "prod" and release.purpose != "PRODUCTION":
        raise PortalPermissionError(
            f"Production cannot activate {release.purpose} release '{release.release_id}'."
        )
    if not release_gcs_bucket:
        return
    if (
        not release.artifact_bucket
        or release.manifest_generation is None
        or release.index_generation is None
        or not release.index_sha256
    ):
        raise PortalPermissionError(
            f"Release '{release.release_id}' lacks immutable GCS metadata."
        )
    if release.purpose == "PRODUCTION" and (
        release.chunk_count <= 0
        or release.vector_count != release.chunk_count
        or not release.embedding_model
        or not release.embedding_dimensions
    ):
        raise PortalPermissionError(
            f"Production release '{release.release_id}' lacks a complete vector index."
        )
    if require_verified and release.verified_at is None:
        raise PortalPermissionError(
            f"Release '{release.release_id}' has not been verified by the Agent."
        )


__all__ = ["require_release_allowed"]
