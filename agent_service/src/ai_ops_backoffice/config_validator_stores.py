"""Production store-mode checks for BackofficeSettings validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .settings import BackofficeSettings


def collect_production_store_errors(settings: BackofficeSettings) -> list[str]:
    errors: list[str] = []
    eval_mode = settings.eval_store_mode or settings.ops_store_mode
    gate_mode = settings.gate_store_mode or settings.ops_store_mode
    fixture_mode = settings.fixture_store_mode or settings.ops_store_mode
    job_mode = settings.job_store_mode or settings.ops_store_mode
    source_mode = (
        settings.source_store_mode
        if settings.source_store_mode != "FILE"
        else settings.ops_store_mode
    )
    domain_modes = {
        "ops_audit_store_mode": settings.ops_audit_store_mode,
        "export_job_store_mode": settings.export_job_store_mode,
        "faq_store_mode": settings.faq_store_mode,
        "example_store_mode": settings.example_store_mode,
        "quality_store_mode": settings.quality_store_mode,
        "sync_store_mode": settings.sync_store_mode,
        "budget_store_mode": settings.budget_store_mode,
        "prompt_poc_store_mode": settings.prompt_poc_store_mode,
        "governance_store_mode": settings.governance_store_mode,
        "eval_store_mode": eval_mode,
        "gate_store_mode": gate_mode,
        "fixture_store_mode": fixture_mode,
        "job_store_mode": job_mode,
        "source_store_mode": source_mode,
    }
    for name, mode in domain_modes.items():
        if mode in ("FILE", "MEMORY"):
            errors.append(
                f"{name} must not be {mode} in production; configure FIRESTORE."
            )

    artifact_backend = (settings.artifact_storage_backend or "FILE").upper()
    if artifact_backend in {"FILE", "NONE", ""}:
        errors.append(
            "artifact_storage_backend must be GCS in production; "
            f"configure AI_OPS_ARTIFACT_STORAGE_BACKEND (found '{artifact_backend}')."
        )
    elif artifact_backend == "GCS" and not settings.artifact_gcs_bucket:
        errors.append(
            "AI_OPS_ARTIFACT_GCS_BUCKET is required when artifact storage backend is GCS."
        )
    export_bucket = settings.export_gcs_bucket
    if (
        artifact_backend == "GCS"
        and settings.artifact_gcs_bucket
        and export_bucket
        and settings.artifact_gcs_bucket == export_bucket
    ):
        errors.append(
            "AI_OPS_ARTIFACT_GCS_BUCKET must differ from AI_OPS_EXPORT_GCS_BUCKET "
            "so original assets are not mixed with short-lived exports."
        )
    return errors
