"""Repository adapter selection for Backoffice composition root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_ops_backoffice.budget_domain import FileBudgetRepository, FirestoreBudgetRepository
from ai_ops_backoffice.evaluation_domain import (
    EvaluationRepository,
    FileEvaluationRepository,
    FileJobRepository,
    FileQualityGateRepository,
    FileToolFixtureRepository,
    FirestoreEvaluationRepository,
    FirestoreJobRepository,
    FirestoreQualityGateRepository,
    FirestoreToolFixtureRepository,
    InMemoryEvaluationRepository,
    InMemoryJobRepository,
    InMemoryQualityGateRepository,
    JobRepository,
    QualityGateRepository,
    ToolFixtureRepository,
)
from ai_ops_backoffice.example_domain import (
    FileExampleRepository,
    FirestoreExampleRepository,
)
from ai_ops_backoffice.faq_domain import FileFaqRepository, FirestoreFaqRepository
from ai_ops_backoffice.prompt_domain import FilePromptRepository, FirestorePromptRepository
from ai_ops_backoffice.quality_domain import (
    FileQualityRepository,
    FirestoreQualityRepository,
)
from ai_ops_backoffice.settings import BackofficeSettings
from ai_ops_backoffice.sync_domain import FileSyncRepository, FirestoreSyncRepository


def default_phase2_path(settings: BackofficeSettings, filename: str) -> Path:
    return settings.ops_store_path.parent / "phase2" / filename


def default_phase3_path(settings: BackofficeSettings, filename: str) -> Path:
    return settings.ops_store_path.parent / "phase3" / filename


def default_evaluations_path(settings: BackofficeSettings, *parts: str) -> Path:
    return settings.ops_store_path.parent.joinpath("evaluations", *parts)


def build_faq_repository(settings: BackofficeSettings) -> Any:
    mode = settings.faq_store_mode.upper()
    if mode == "FILE":
        path = settings.faq_store_path or default_phase2_path(settings, "faqs.json")
        return FileFaqRepository(path)
    if mode == "FIRESTORE":
        from google.cloud import firestore

        return FirestoreFaqRepository(
            firestore.Client(project=settings.gcp_project_id),
            collection_prefix=settings.faq_firestore_collection_prefix,
        )
    raise ValueError(f"Unsupported FAQ store mode: {mode}")


def build_example_repository(settings: BackofficeSettings) -> Any:
    mode = settings.example_store_mode.upper()
    if mode == "FILE":
        path = settings.example_store_path or default_phase2_path(settings, "examples.json")
        return FileExampleRepository(path)
    if mode == "FIRESTORE":
        from google.cloud import firestore

        return FirestoreExampleRepository(
            firestore.Client(project=settings.gcp_project_id),
            collection_prefix=settings.example_firestore_collection_prefix,
        )
    raise ValueError(f"Unsupported example store mode: {mode}")


def build_quality_repository(settings: BackofficeSettings) -> Any:
    mode = settings.quality_store_mode.upper()
    if mode == "FILE":
        path = settings.quality_store_path or default_phase2_path(settings, "quality.json")
        return FileQualityRepository(path)
    if mode == "FIRESTORE":
        from google.cloud import firestore

        return FirestoreQualityRepository(
            firestore.Client(project=settings.gcp_project_id),
            collection=settings.quality_firestore_collection,
        )
    raise ValueError(f"Unsupported quality store mode: {mode}")


def build_sync_repository(settings: BackofficeSettings) -> Any:
    mode = settings.sync_store_mode.upper()
    if mode == "FILE":
        path = settings.sync_store_path or default_phase2_path(settings, "sync_jobs.json")
        return FileSyncRepository(path)
    if mode == "FIRESTORE":
        from google.cloud import firestore

        return FirestoreSyncRepository(
            firestore.Client(project=settings.gcp_project_id),
            collection=settings.sync_firestore_collection,
        )
    raise ValueError(f"Unsupported sync store mode: {mode}")


def build_budget_repository(settings: BackofficeSettings) -> Any:
    mode = settings.budget_store_mode.upper()
    if mode == "FILE":
        path = settings.budget_store_path or default_phase2_path(settings, "budgets.json")
        return FileBudgetRepository(path)
    if mode == "FIRESTORE":
        from google.cloud import firestore

        return FirestoreBudgetRepository(
            firestore.Client(project=settings.gcp_project_id),
            collection=settings.budget_firestore_collection,
        )
    raise ValueError(f"Unsupported budget store mode: {mode}")


def build_prompt_poc_repository(settings: BackofficeSettings) -> Any:
    mode = settings.prompt_poc_store_mode.upper()
    if mode == "FILE":
        path = settings.prompt_poc_store_path or default_phase2_path(
            settings, "prompt_candidates.json"
        )
        return FilePromptRepository(path)
    if mode == "FIRESTORE":
        from google.cloud import firestore

        return FirestorePromptRepository(
            firestore.Client(project=settings.gcp_project_id),
            collection=settings.prompt_poc_firestore_collection,
        )
    raise ValueError(f"Unsupported Prompt POC store mode: {mode}")


def build_governance_repository(settings: BackofficeSettings) -> Any:
    from ai_ops_backoffice.governance_domain.store_factory import (
        build_governance_repository as build_from_factory,
    )

    store_path = settings.governance_store_path or default_phase3_path(
        settings, "governance.json"
    )
    return build_from_factory(
        store_mode=settings.governance_store_mode.upper(),
        file_path=store_path,
        firestore_project=settings.gcp_project_id,
        firestore_collection=settings.governance_firestore_collection,
    )


def build_evaluation_repository(settings: BackofficeSettings) -> EvaluationRepository:
    mode = (settings.eval_store_mode or settings.ops_store_mode).upper()
    if mode == "MEMORY":
        return InMemoryEvaluationRepository()
    if mode == "FIRESTORE":
        from operations_core.firestore_client import build_sync_firestore_client

        return FirestoreEvaluationRepository(
            build_sync_firestore_client(settings.gcp_project_id, None),
            collection_prefix=settings.eval_firestore_collection,
        )
    path = settings.eval_store_path or default_evaluations_path(
        settings, "golden_evals.json"
    )
    return FileEvaluationRepository(path)


def build_tool_fixture_repository(settings: BackofficeSettings) -> ToolFixtureRepository:
    mode = (settings.fixture_store_mode or settings.ops_store_mode).upper()
    if mode == "MEMORY":
        return ToolFixtureRepository()
    if mode == "FIRESTORE":
        from operations_core.firestore_client import build_sync_firestore_client

        return FirestoreToolFixtureRepository(
            build_sync_firestore_client(settings.gcp_project_id, None),
            prefix=settings.fixture_firestore_collection_prefix,
        )
    path = settings.fixture_store_path or default_evaluations_path(settings, "fixtures")
    return FileToolFixtureRepository(path)


def build_quality_gate_repository(settings: BackofficeSettings) -> QualityGateRepository:
    mode = (settings.gate_store_mode or settings.ops_store_mode).upper()
    if mode == "MEMORY":
        return InMemoryQualityGateRepository()
    if mode == "FIRESTORE":
        from operations_core.firestore_client import build_sync_firestore_client

        return FirestoreQualityGateRepository(
            build_sync_firestore_client(settings.gcp_project_id, None),
            prefix=settings.gate_firestore_collection_prefix,
        )
    path = settings.gate_store_path or default_evaluations_path(settings, "gates")
    return FileQualityGateRepository(path)


def build_job_repository(settings: BackofficeSettings) -> JobRepository:
    mode = (settings.job_store_mode or settings.ops_store_mode).upper()
    if mode == "MEMORY":
        return InMemoryJobRepository()
    if mode == "FIRESTORE":
        from operations_core.firestore_client import build_sync_firestore_client

        return FirestoreJobRepository(
            build_sync_firestore_client(settings.gcp_project_id, None),
            collection=settings.job_firestore_collection,
        )
    path = settings.job_store_path or default_evaluations_path(settings, "jobs")
    return FileJobRepository(path)
