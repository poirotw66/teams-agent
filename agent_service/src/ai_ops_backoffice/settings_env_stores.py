"""Store-section environment parsers for BackofficeSettings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .settings_env_common import env_path, resolve_store_mode, truthy


def load_export_env(ops_dir: Path, primary_store_mode: str) -> dict[str, Any]:
    return {
        "export_job_store_mode": resolve_store_mode(
            "AI_OPS_EXPORT_JOB_STORE_MODE", primary_store_mode, "FILE"
        ),
        "export_job_collection": os.environ.get(
            "AI_OPS_EXPORT_JOB_COLLECTION", "ai_ops_export_jobs"
        ),
        "export_content_backend": (
            os.environ.get("AI_OPS_EXPORT_CONTENT_BACKEND", "FILE") or "FILE"
        ).upper(),
        "export_content_path": env_path(
            "AI_OPS_EXPORT_CONTENT_PATH", ops_dir / "exports" / "content"
        ),
        "export_gcs_bucket": os.environ.get("AI_OPS_EXPORT_GCS_BUCKET") or None,
        "export_ttl_seconds": int(os.environ.get("AI_OPS_EXPORT_TTL_SECONDS", "86400")),
        "export_max_records": int(
            os.environ.get("AI_OPS_EXPORT_MAX_RECORDS", "100000")
        ),
        "export_worker_lease_seconds": int(
            os.environ.get("AI_OPS_EXPORT_WORKER_LEASE_SECONDS", "60")
        ),
        "export_worker_max_attempts": int(
            os.environ.get("AI_OPS_EXPORT_WORKER_MAX_ATTEMPTS", "3")
        ),
    }


def load_phase2_store_env(ops_dir: Path, primary_store_mode: str) -> dict[str, Any]:
    return {
        "faq_store_mode": resolve_store_mode(
            "AI_OPS_FAQ_STORE_MODE", primary_store_mode, "FILE"
        ),
        "faq_store_path": env_path(
            "AI_OPS_FAQ_STORE_PATH", ops_dir / "phase2" / "faqs.json"
        ),
        "faq_artifact_dir": env_path(
            "AI_OPS_FAQ_ARTIFACT_DIR", ops_dir / "phase2" / "faq-artifacts"
        ),
        "faq_firestore_collection_prefix": os.environ.get(
            "AI_OPS_FAQ_FIRESTORE_COLLECTION_PREFIX", "ai_ops_faq"
        ),
        "example_store_mode": resolve_store_mode(
            "AI_OPS_EXAMPLE_STORE_MODE", primary_store_mode, "FILE"
        ),
        "example_store_path": env_path(
            "AI_OPS_EXAMPLE_STORE_PATH", ops_dir / "phase2" / "examples.json"
        ),
        "example_firestore_collection_prefix": os.environ.get(
            "AI_OPS_EXAMPLE_FIRESTORE_COLLECTION_PREFIX", "ai_ops_faq"
        ),
        "quality_store_mode": resolve_store_mode(
            "AI_OPS_QUALITY_STORE_MODE", primary_store_mode, "FILE"
        ),
        "quality_store_path": env_path(
            "AI_OPS_QUALITY_STORE_PATH", ops_dir / "phase2" / "quality.json"
        ),
        "quality_firestore_collection": os.environ.get(
            "AI_OPS_QUALITY_FIRESTORE_COLLECTION", "ai_ops_quality_state"
        ),
        "sync_store_mode": resolve_store_mode(
            "AI_OPS_SYNC_STORE_MODE", primary_store_mode, "FILE"
        ),
        "sync_store_path": env_path(
            "AI_OPS_SYNC_STORE_PATH", ops_dir / "phase2" / "sync_jobs.json"
        ),
        "sync_firestore_collection": os.environ.get(
            "AI_OPS_SYNC_FIRESTORE_COLLECTION", "ai_ops_sync_state"
        ),
        "sync_adapter_url": (
            os.environ.get("AI_OPS_SYNC_ADAPTER_URL")
            or os.environ.get("KNOWLEDGE_PORTAL_INTERNAL_URL")
            or os.environ.get("KNOWLEDGE_PORTAL_PUBLIC_URL")
            or "http://127.0.0.1:8091"
        ),
    }


def load_budget_env(ops_dir: Path, primary_store_mode: str) -> dict[str, Any]:
    return {
        "budget_store_mode": resolve_store_mode(
            "AI_OPS_BUDGET_STORE_MODE", primary_store_mode, "FILE"
        ),
        "budget_store_path": env_path(
            "AI_OPS_BUDGET_STORE_PATH", ops_dir / "phase2" / "budgets.json"
        ),
        "budget_firestore_collection": os.environ.get(
            "AI_OPS_BUDGET_FIRESTORE_COLLECTION", "ai_ops_budget_state"
        ),
        "budget_notification_targets": tuple(
            item.strip()
            for item in os.environ.get(
                "AI_OPS_BUDGET_NOTIFICATION_TARGETS",
                "notification-center=NOTIFICATION_CENTER",
            ).split(",")
            if item.strip()
        ),
        "teams_webhook_url": os.environ.get("AI_OPS_TEAMS_WEBHOOK_URL", ""),
        "smtp_host": os.environ.get("AI_OPS_SMTP_HOST", ""),
        "smtp_port": int(os.environ.get("AI_OPS_SMTP_PORT", "587")),
        "smtp_user": os.environ.get("AI_OPS_SMTP_USER", ""),
        "smtp_password": os.environ.get("AI_OPS_SMTP_PASSWORD", ""),
        "smtp_from": os.environ.get("AI_OPS_SMTP_FROM", "ai-ops@example.com"),
        "budget_eval_interval_seconds": int(
            os.environ.get("AI_OPS_BUDGET_EVAL_INTERVAL_SECONDS", "300")
        ),
        "default_personal_daily_budget_enabled": truthy(
            os.environ.get("AI_OPS_DEFAULT_PERSONAL_DAILY_BUDGET_ENABLED", "true")
        ),
        "default_personal_daily_budget_threshold": float(
            os.environ.get("AI_OPS_DEFAULT_PERSONAL_DAILY_BUDGET_THRESHOLD", "50.0")
        ),
        "default_personal_daily_warning_threshold": float(
            os.environ.get("AI_OPS_DEFAULT_PERSONAL_DAILY_WARNING_THRESHOLD", "40.0")
        ),
        "api_anomaly_check_enabled": truthy(
            os.environ.get("AI_OPS_API_ANOMALY_CHECK_ENABLED", "true")
        ),
    }


def load_prompt_governance_env(
    ops_dir: Path, primary_store_mode: str
) -> dict[str, Any]:
    return {
        "prompt_poc_store_mode": resolve_store_mode(
            "AI_OPS_PROMPT_POC_STORE_MODE", primary_store_mode, "FILE"
        ),
        "prompt_poc_store_path": env_path(
            "AI_OPS_PROMPT_POC_STORE_PATH",
            ops_dir / "phase2" / "prompt_candidates.json",
        ),
        "prompt_poc_firestore_collection": os.environ.get(
            "AI_OPS_PROMPT_POC_FIRESTORE_COLLECTION", "ai_ops_prompt_poc_state"
        ),
        "prompt_masking_policy_version": os.environ.get(
            "AI_OPS_PROMPT_MASKING_POLICY_VERSION", "mask-v1"
        ),
        "prompt_active_effective_at": (
            os.environ.get("AI_OPS_PROMPT_ACTIVE_EFFECTIVE_AT") or None
        ),
        "governance_store_mode": resolve_store_mode(
            "AI_OPS_GOVERNANCE_STORE_MODE", primary_store_mode, "FILE"
        ),
        "governance_store_path": env_path(
            "AI_OPS_GOVERNANCE_STORE_PATH",
            ops_dir / "phase3" / "governance.json",
        ),
        "governance_firestore_collection": os.environ.get(
            "AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION", "ai_ops_governance_state"
        ),
        "pricing_store_mode": (
            os.environ.get("AI_OPS_PRICING_STORE_MODE", "FILE") or "FILE"
        ).upper(),
        "pricing_store_path": env_path(
            "AI_OPS_PRICING_STORE_PATH",
            ops_dir / "phase2" / "pricing_rules.json",
        ),
        "pricing_firestore_collection": os.environ.get(
            "AIOPS_PRICING_FIRESTORE_COLLECTION", "ai_ops_pricing_state"
        ),
    }


def load_evaluation_store_env(
    ops_dir: Path, primary_store_mode: str
) -> dict[str, Any]:
    return {
        "eval_store_mode": resolve_store_mode(
            "AI_OPS_EVAL_STORE_MODE", primary_store_mode, "FILE"
        ),
        "eval_store_path": env_path(
            "AI_OPS_EVAL_STORE_PATH",
            ops_dir / "evaluations" / "golden_evals.json",
        ),
        "eval_firestore_collection": os.environ.get(
            "AI_OPS_EVAL_FIRESTORE_COLLECTION", "ai_ops_evaluation_state"
        ),
        "gate_store_mode": resolve_store_mode(
            "AI_OPS_GATE_STORE_MODE", primary_store_mode, "FILE"
        ),
        "gate_store_path": env_path(
            "AI_OPS_GATE_STORE_PATH",
            ops_dir / "evaluations" / "gates",
        ),
        "gate_firestore_collection_prefix": os.environ.get(
            "AI_OPS_GATE_FIRESTORE_COLLECTION_PREFIX", "ai_ops_gate"
        ),
        "fixture_store_mode": resolve_store_mode(
            "AI_OPS_FIXTURE_STORE_MODE", primary_store_mode, "FILE"
        ),
        "fixture_store_path": env_path(
            "AI_OPS_FIXTURE_STORE_PATH",
            ops_dir / "evaluations" / "fixtures",
        ),
        "fixture_firestore_collection_prefix": os.environ.get(
            "AI_OPS_FIXTURE_FIRESTORE_COLLECTION_PREFIX", "ai_ops_fixture"
        ),
        "job_store_mode": resolve_store_mode(
            "AI_OPS_JOB_STORE_MODE", primary_store_mode, "FILE"
        ),
        "job_store_path": env_path(
            "AI_OPS_JOB_STORE_PATH",
            ops_dir / "evaluations" / "jobs",
        ),
        "job_firestore_collection": os.environ.get(
            "AI_OPS_JOB_FIRESTORE_COLLECTION", "ai_ops_execution_jobs"
        ),
    }


def load_source_artifact_env(
    ops_dir: Path, primary_store_mode: str
) -> dict[str, Any]:
    return {
        "source_store_mode": resolve_store_mode(
            "AI_OPS_SOURCE_STORE_MODE", primary_store_mode, primary_store_mode
        ),
        "source_store_path": env_path(
            "AI_OPS_SOURCE_STORE_PATH",
            ops_dir / "sources" / "records",
        ),
        "artifact_storage_backend": (
            os.environ.get("AI_OPS_ARTIFACT_STORAGE_BACKEND", "FILE") or "FILE"
        ).upper(),
        "artifact_storage_path": env_path(
            "AI_OPS_ARTIFACT_STORAGE_PATH",
            ops_dir / "sources" / "artifacts",
        ),
        "artifact_gcs_bucket": (
            os.environ.get("AI_OPS_ARTIFACT_GCS_BUCKET")
            or os.environ.get("AI_OPS_EXPORT_GCS_BUCKET")
            or None
        ),
    }
