"""Query-service collaborator ports and composition hooks.

Keeps ``BackofficeQueryService`` free of Agent imports while allowing wiring to
inject ``build_ops_runtime`` and GCS artifact storage builders.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from knowledge_core.artifact_ports import ArtifactStorage, LocalFileArtifactStorage
from operations_core.audit import AuditStore
from operations_core.settings import OpsSettings
from operations_core.taxonomy import TaxonomyRepository

from ..settings import BackofficeSettings
from .freshness_service import FreshnessTracker

OpsRuntimeBuilder = Callable[..., Any]
ArtifactStorageBuilder = Callable[[BackofficeSettings], ArtifactStorage]

_ops_runtime_builder: OpsRuntimeBuilder | None = None
_artifact_storage_builder: ArtifactStorageBuilder | None = None


@runtime_checkable
class OpsRuntimePort(Protocol):
    """Minimal ops runtime surface used by Backoffice query paths."""

    settings: OpsSettings
    taxonomy: TaxonomyRepository
    audit_store: AuditStore
    store: Any
    freshness_recorder: Any


def configure_query_service_collaborators(
    *,
    ops_runtime_builder: OpsRuntimeBuilder | None,
    artifact_storage_builder: ArtifactStorageBuilder | None = None,
) -> None:
    """Register composition-owned builders for Agent-backed collaborators."""
    global _ops_runtime_builder, _artifact_storage_builder
    _ops_runtime_builder = ops_runtime_builder
    _artifact_storage_builder = artifact_storage_builder


def resolve_ops_runtime(
    ops_settings: OpsSettings,
    *,
    freshness_tracker: FreshnessTracker | None,
    ops_runtime: OpsRuntimePort | None,
) -> OpsRuntimePort:
    if ops_runtime is not None:
        return ops_runtime
    if _ops_runtime_builder is None:
        raise RuntimeError(
            "Ops runtime builder is not configured. Call "
            "configure_query_service_collaborators from Backoffice wiring."
        )
    runtime = _ops_runtime_builder(ops_settings, freshness_recorder=freshness_tracker)
    if runtime is None:
        raise RuntimeError("Operational events are disabled.")
    return runtime


def resolve_artifact_storage(
    settings: BackofficeSettings,
    *,
    artifact_storage: ArtifactStorage | None,
) -> ArtifactStorage:
    if artifact_storage is not None:
        return artifact_storage
    if _artifact_storage_builder is not None:
        return _artifact_storage_builder(settings)
    artifact_path = getattr(settings, "artifact_storage_path", None) or (
        settings.ops_store_path.parent / "sources" / "artifacts"
    )
    return LocalFileArtifactStorage(artifact_path)


def build_backoffice_ops_settings(settings: BackofficeSettings) -> OpsSettings:
    """Map Backoffice settings onto the shared OpsSettings contract."""
    return replace(
        OpsSettings.from_env(),
        enabled=True,
        store_mode=settings.ops_store_mode,
        store_path=settings.ops_store_path,
        taxonomy_path=settings.ops_taxonomy_path,
        metrics_path=settings.ops_metrics_path,
        classification_rules_path=settings.ops_classification_rules_path,
        audit_store_mode=settings.ops_audit_store_mode,
        firestore_project=settings.gcp_project_id,
    )


__all__ = [
    "ArtifactStorageBuilder",
    "OpsRuntimeBuilder",
    "OpsRuntimePort",
    "build_backoffice_ops_settings",
    "configure_query_service_collaborators",
    "resolve_artifact_storage",
    "resolve_ops_runtime",
]
