"""Collaborator construction for BackofficeQueryService.__init__."""

from __future__ import annotations

from typing import Any

from knowledge_core.artifact_ports import ArtifactStorage

from ..pricing_domain import (
    FilePricingRepository,
    FirestorePricingRepository,
    InMemoryPricingRepository,
    PricingService,
)
from ..settings import BackofficeSettings
from .daily_aggregates import FileDailyAggregateStore
from .export_content import FileExportContentStore, GcsExportContentStore
from .export_job_store import FileExportJobStore, FirestoreExportJobStore
from .export_service import ExportJobService
from .freshness_service import FreshnessTracker
from .query_collaborators import OpsRuntimePort, resolve_artifact_storage
from .source_repository import (
    FileSourceRecordRepository,
    FirestoreSourceRecordRepository,
)
from .source_trace import SourceTraceResolver


def build_source_trace(
    settings: BackofficeSettings,
    *,
    artifact_storage: ArtifactStorage | None,
) -> SourceTraceResolver:
    releases_dir = getattr(settings, "knowledge_release_dir", None) or (
        settings.ops_store_path.parent.parent / "releases"
    )
    source_store_mode = (getattr(settings, "source_store_mode", None) or "FILE").upper()
    if source_store_mode == "FIRESTORE":
        from google.cloud import firestore

        source_repository = FirestoreSourceRecordRepository(
            client=firestore.Client(project=settings.gcp_project_id),
            project_id=settings.gcp_project_id,
        )
    else:
        source_path = getattr(settings, "source_store_path", None) or (
            settings.ops_store_path.parent / "sources" / "records"
        )
        source_repository = FileSourceRecordRepository(source_path)
    resolved_artifact_storage = resolve_artifact_storage(
        settings, artifact_storage=artifact_storage
    )
    return SourceTraceResolver(
        releases_dir,
        source_repository=source_repository,
        artifact_storage=resolved_artifact_storage,
        gcp_project_id=getattr(settings, "gcp_project_id", None),
        firestore_database=getattr(settings, "firestore_database", None) or "(default)",
    )


def build_freshness_tracker(
    settings: BackofficeSettings,
    *,
    runtime: OpsRuntimePort,
    freshness_tracker: FreshnessTracker | None,
) -> FreshnessTracker:
    if freshness_tracker is not None:
        return freshness_tracker
    if getattr(runtime, "freshness_recorder", None) is not None and isinstance(
        runtime.freshness_recorder, FreshnessTracker
    ):
        return runtime.freshness_recorder
    freshness_firestore_client = None
    if (
        settings.ops_store_mode == "FIRESTORE"
        or getattr(settings, "source_store_mode", "").upper() == "FIRESTORE"
    ):
        try:
            from google.cloud import firestore

            freshness_firestore_client = firestore.Client(project=settings.gcp_project_id)
        except Exception as exc:
            if settings.ops_store_mode == "FIRESTORE":
                raise RuntimeError(
                    f"Failed to initialize Firestore client for freshness tracking: {exc}"
                ) from exc
    shared_store = getattr(getattr(runtime, "freshness_recorder", None), "_store", None)
    collection = getattr(settings, "freshness_firestore_collection", "freshness_state")
    return FreshnessTracker(
        persistent_path=settings.ops_store_path.parent / "freshness" / "sync_watermarks.json",
        firestore_client=freshness_firestore_client,
        firestore_collection=collection,
        store=shared_store,
    )


def build_export_job_service(
    settings: BackofficeSettings,
    *,
    runtime: OpsRuntimePort,
    environment: str,
) -> ExportJobService:
    export_store_path = settings.ops_store_path.parent / "exports"
    if settings.export_job_store_mode == "FILE":
        export_job_store: Any = FileExportJobStore(export_store_path)
    elif settings.export_job_store_mode == "FIRESTORE":
        try:
            from google.cloud.firestore_v1.async_client import AsyncClient
        except ImportError as exc:  # pragma: no cover - optional deployment dependency
            raise RuntimeError("Firestore export jobs require google-cloud-firestore.") from exc
        firestore_client = AsyncClient(project=settings.gcp_project_id)
        export_job_store = FirestoreExportJobStore(
            firestore_client,
            settings.export_job_collection,
        )
    else:
        raise ValueError(f"Unsupported export job store mode: {settings.export_job_store_mode}")
    if settings.export_content_backend == "FILE":
        export_content_store: Any = FileExportContentStore(
            settings.export_content_path or export_store_path / "content"
        )
    elif settings.export_content_backend == "GCS":
        if not settings.export_gcs_bucket:
            raise ValueError("AI_OPS_EXPORT_GCS_BUCKET is required for GCS exports.")
        export_content_store = GcsExportContentStore(bucket_name=settings.export_gcs_bucket)
    else:
        raise ValueError(f"Unsupported export content backend: {settings.export_content_backend}")
    return ExportJobService(
        audit_store=runtime.audit_store,
        store_path=export_store_path,
        environment=environment,
        job_store=export_job_store,
        content_store=export_content_store,
        ttl_seconds=settings.export_ttl_seconds,
        max_records=settings.export_max_records,
        run_inline=(environment.lower() in {"dev", "test"} or settings.ops_store_mode == "MEMORY"),
    )


def build_pricing_service(
    settings: BackofficeSettings,
    *,
    runtime: OpsRuntimePort,
    environment: str,
) -> tuple[Any, PricingService, FileDailyAggregateStore]:
    aggregate_store = FileDailyAggregateStore(
        settings.ops_store_path.parent / "aggregates" / "daily_ops.json"
    )
    pricing_store_path = settings.pricing_store_path or (
        settings.ops_store_path.parent / "phase2" / "pricing_rules.json"
    )
    if settings.pricing_store_mode == "FILE":
        pricing_repository: Any = FilePricingRepository(pricing_store_path)
    elif settings.pricing_store_mode == "FIRESTORE":
        from google.cloud import firestore

        pricing_repository = FirestorePricingRepository(
            firestore.Client(project=settings.gcp_project_id),
            collection=settings.pricing_firestore_collection,
        )
    else:
        pricing_repository = InMemoryPricingRepository()
    pricing_service = PricingService(
        pricing_repository,
        audit_store=runtime.audit_store,
        environment=environment,
    )
    return pricing_repository, pricing_service, aggregate_store
