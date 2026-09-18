"""Backoffice adapters that implement platform_kernel ports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from platform_kernel.ports.release_gate import ReleaseGateBlockedError
from platform_kernel.ports.source_catalog import SourceCatalogEntry


class QualityGateReleaseChecker:
    """Adapts QualityGateService.verify_release_gate into ReleaseGateChecker."""

    def __init__(self, gate_service: Any) -> None:
        self._gate_service = gate_service

    def check_activation(
        self,
        *,
        target_manifest_hash: str,
        target_type: str,
        policy_id: str = "default-gate-policy",
        tenant_id: str | None = None,
        environment: str = "prod",
        policy_version: int | None = None,
    ) -> dict[str, Any]:
        from ai_ops_backoffice.evaluation_domain.gate_service import GateBlockedError

        try:
            result = self._gate_service.verify_release_gate(
                target_manifest_hash=target_manifest_hash,
                policy_id=policy_id,
                tenant_id=tenant_id,
                environment=environment,
                policy_version=policy_version,
                target_type=target_type,
            )
        except GateBlockedError as exc:
            raise ReleaseGateBlockedError(str(exc)) from exc
        return {**result, "target_type": target_type}


class BackofficeSourceCatalogWriter:
    """Adapts File/Firestore source repositories into SourceCatalogWriter."""

    def __init__(self, repository: Any) -> None:
        self._repository = repository

    async def save_entries(self, entries: Sequence[SourceCatalogEntry]) -> int:
        from ai_ops_backoffice.services.source_models import MappingStatus, SourceRecord

        records = [
            SourceRecord(
                source_ref_id=entry.source_ref_id,
                tenant_id=entry.tenant_id,
                document_id=entry.document_id,
                version_id=entry.version_id,
                release_id=entry.release_id,
                chunk_id=entry.chunk_id,
                artifact_ref=entry.artifact_ref,
                content_hash=entry.content_hash,
                mapping_status=MappingStatus(entry.mapping_status),
                source_type=entry.source_type,
                title=entry.title,
                source_path=entry.source_path,
                excerpt=entry.excerpt,
                original_asset_name=entry.original_asset_name,
                acl_groups=list(entry.acl_groups),
            )
            for entry in entries
        ]
        await self._repository.save_source_records(records)
        return len(records)


def build_source_catalog_writer_from_settings(settings: Any) -> BackofficeSourceCatalogWriter | None:
    """Compose a catalog writer from PortalSettings-like source store config."""

    from pathlib import Path

    mode = (getattr(settings, "source_store_mode", None) or "NONE").upper()
    if mode in {"", "NONE", "OFF"}:
        return None

    if mode == "FIRESTORE":
        from google.cloud import firestore

        from ai_ops_backoffice.services.source_repository import (
            FirestoreSourceRecordRepository,
        )

        project = getattr(settings, "firestore_project_id", None)
        repo = FirestoreSourceRecordRepository(
            client=firestore.Client(project=project) if project else firestore.Client(),
            project_id=project,
        )
        return BackofficeSourceCatalogWriter(repo)

    if mode == "FILE":
        from ai_ops_backoffice.services.source_repository import FileSourceRecordRepository

        root = getattr(settings, "source_store_path", None) or (
            Path(settings.data_dir) / "ops" / "sources" / "records"
        )
        return BackofficeSourceCatalogWriter(FileSourceRecordRepository(Path(root)))

    return None


def build_governance_provider_from_rag_settings(settings: Any) -> Any | None:
    mode = str(getattr(settings, "prompt_runtime_mode", "CODE_BASELINE")).upper()
    if mode == "CODE_BASELINE":
        return None
    if mode != "GOVERNED":
        raise ValueError(f"Unsupported prompt runtime mode: {mode}")

    from ai_ops_backoffice.governance_domain.service import GovernanceService
    from ai_ops_backoffice.governance_domain.store_factory import build_governance_repository

    store_mode = str(settings.prompt_governance_store_mode).upper()
    path = settings.prompt_governance_store_path or (
        settings.data_dir / "ops" / "phase3" / "governance.json"
    )
    repository = build_governance_repository(
        store_mode=store_mode,
        file_path=path,
        firestore_project=settings.prompt_governance_firestore_project,
        firestore_database=settings.prompt_governance_firestore_database,
        firestore_collection=settings.prompt_governance_firestore_collection,
    )
    return GovernanceService(repository)


def build_ops_governance_from_settings(settings: Any) -> Any | None:
    import logging
    import os
    from pathlib import Path

    logger = logging.getLogger(__name__)
    store_mode = (os.environ.get("AI_OPS_GOVERNANCE_STORE_MODE", "FILE") or "FILE").upper()
    try:
        from ai_ops_backoffice.governance_domain.service import GovernanceService
        from ai_ops_backoffice.governance_domain.store_factory import (
            SUPPORTED_GOVERNANCE_STORE_MODES,
            build_governance_repository,
        )
    except Exception:  # noqa: BLE001
        logger.warning("governance packages unavailable; policy runtime uses defaults")
        return None
    if store_mode not in SUPPORTED_GOVERNANCE_STORE_MODES:
        logger.warning("unsupported governance store mode %s; using defaults", store_mode)
        return None
    path = Path(
        os.environ.get(
            "AI_OPS_GOVERNANCE_STORE_PATH",
            str(settings.store_path.parent / "phase3" / "governance.json"),
        )
    )
    project = os.environ.get("AI_OPS_GCP_PROJECT") or settings.firestore_project
    collection = (
        os.environ.get("AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION") or "ai_ops_governance_state"
    )
    try:
        repository = build_governance_repository(
            store_mode=store_mode,
            file_path=path,
            firestore_project=project,
            firestore_collection=collection,
        )
        return GovernanceService(repository)
    except Exception:  # noqa: BLE001
        logger.warning("failed to build governance repository; using defaults", exc_info=True)
        return None


def build_governed_faq_domain_service(settings: Any) -> Any:
    from ai_ops_backoffice.faq_domain.repository import (
        FileFaqRepository,
        FirestoreFaqRepository,
    )
    from ai_ops_backoffice.faq_domain.service import FaqDomainService

    store_mode = str(settings.faq_governed_store_mode).upper()
    if store_mode == "FILE":
        path = settings.faq_governed_store_path or (
            settings.data_dir / "ops" / "phase2" / "faqs.json"
        )
        repository = FileFaqRepository(path)
    elif store_mode == "FIRESTORE":
        from google.cloud import firestore

        client_kwargs = {}
        if settings.faq_firestore_project:
            client_kwargs["project"] = settings.faq_firestore_project
        if settings.faq_firestore_database:
            client_kwargs["database"] = settings.faq_firestore_database
        repository = FirestoreFaqRepository(
            firestore.Client(**client_kwargs),
            collection_prefix=settings.faq_firestore_collection_prefix,
        )
    else:
        raise ValueError(f"Unsupported governed FAQ store mode: {store_mode}")
    return FaqDomainService(repository)


def build_and_configure_pricing_service(
    *,
    ops_store_path: Any | None = None,
    audit_store: Any | None = None,
    environment: str = "dev",
) -> Any:
    import logging
    import os

    from agent_service.pricing_bootstrap import resolve_pricing_store_path
    from agent_service.usage import configure_pricing_provider
    from ai_ops_backoffice.pricing_domain import (
        FilePricingRepository,
        FirestorePricingRepository,
        InMemoryPricingRepository,
        PricingService,
    )

    logger = logging.getLogger(__name__)
    mode = (os.environ.get("AI_OPS_PRICING_STORE_MODE", "FILE") or "FILE").upper()
    store_path = resolve_pricing_store_path(ops_store_path)
    collection = (
        os.environ.get("AIOPS_PRICING_FIRESTORE_COLLECTION")
        or os.environ.get("AI_OPS_PRICING_FIRESTORE_COLLECTION")
        or "ai_ops_pricing_state"
    )
    if mode == "FILE":
        repository = FilePricingRepository(store_path)
    elif mode == "FIRESTORE":
        from google.cloud import firestore

        project = (
            os.environ.get("AI_OPS_GCP_PROJECT")
            or os.environ.get("GCP_PROJECT_ID")
            or os.environ.get("OPS_FIRESTORE_PROJECT")
        )
        repository = FirestorePricingRepository(
            firestore.Client(project=project),
            collection=collection,
        )
    else:
        repository = InMemoryPricingRepository()

    service = PricingService(
        repository,
        audit_store=audit_store,
        environment=environment,
    )
    configure_pricing_provider(service)
    logger.info(
        "Governed pricing provider configured: mode=%s version=%s path=%s",
        mode,
        service.get_pricing_version(),
        store_path if mode == "FILE" else collection if mode == "FIRESTORE" else "memory",
    )
    return service


def build_portal_release_gate_checker(settings: Any) -> QualityGateReleaseChecker | None:
    import logging
    import os
    from pathlib import Path

    logger = logging.getLogger(__name__)
    env = (
        getattr(settings, "deployment_environment", None)
        or os.environ.get("AGENT_DEPLOYMENT_ENV")
        or os.environ.get("ENV")
        or "dev"
    ).lower()
    if env not in {"prod", "production", "staging"}:
        return None
    try:
        from ai_ops_backoffice.evaluation_domain import (
            FileQualityGateRepository,
            FirestoreQualityGateRepository,
            InMemoryEvaluationRepository,
            QualityGateService,
        )

        gate_mode = (os.environ.get("AI_OPS_GATE_STORE_MODE") or "FILE").upper()
        if gate_mode == "FIRESTORE":
            from agent_service.operations.stores.firestore_store import (
                build_sync_firestore_client,
            )

            gate_repo = FirestoreQualityGateRepository(
                build_sync_firestore_client(
                    os.environ.get("AI_OPS_GCP_PROJECT")
                    or os.environ.get("GOOGLE_CLOUD_PROJECT"),
                    None,
                ),
                prefix=os.environ.get(
                    "AI_OPS_GATE_FIRESTORE_COLLECTION_PREFIX", "ai_ops_gate"
                ),
            )
        else:
            gate_path = Path(
                os.environ.get(
                    "AI_OPS_GATE_STORE_PATH",
                    Path(settings.release_artifact_dir).parent
                    / "ops"
                    / "evaluations"
                    / "gates",
                )
            )
            gate_repo = FileQualityGateRepository(gate_path)
        gate_service = QualityGateService(
            eval_repository=InMemoryEvaluationRepository(),
            gate_repository=gate_repo,
        )
        return QualityGateReleaseChecker(gate_service)
    except Exception as exc:  # pragma: no cover - fail closed in prod
        logger.error("Failed to wire release gate for portal: %s", exc)
        raise
