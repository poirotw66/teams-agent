"""Build GCS-backed Portal artifact storage from composition.

Keeps Knowledge Portal free of Agent GCS adapter imports while preserving
production dual-write behavior when composition wires collaborators.
"""

from __future__ import annotations

from typing import Any

from agent_service.artifact_storage import GcsArtifactStorage, build_gcs_storage_client
from knowledge_portal.settings import PortalSettings


def build_portal_gcs_artifact_storage(settings: PortalSettings) -> Any | None:
    """Return GCS artifact storage when Portal is configured for GCS."""
    backend = (settings.artifact_storage_backend or "FILE").upper()
    if backend != "GCS":
        return None
    bucket = settings.artifact_gcs_bucket
    if not bucket:
        raise ValueError(
            "KNOWLEDGE_PORTAL_ARTIFACT_GCS_BUCKET (or AI_OPS_ARTIFACT_GCS_BUCKET) "
            "is required when artifact storage backend is GCS."
        )
    return GcsArtifactStorage(
        bucket_name=bucket,
        client=build_gcs_storage_client(),
        allow_memory_fallback=False,
    )
