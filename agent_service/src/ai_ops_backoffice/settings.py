from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackofficeSettings:
    host: str
    port: int
    service_token: str
    auth_mode: str
    ops_store_mode: str
    ops_store_path: Path
    ops_taxonomy_path: Path
    ops_metrics_path: Path
    ops_classification_rules_path: Path
    ops_audit_store_mode: str
    knowledge_portal_url: str
    agent_api_url: str | None
    adapter_api_url: str | None
    ticket_service_url: str | None
    default_owner_unit_id: str
    entra_tenant_id: str | None
    entra_client_id: str | None
    gcp_project_id: str | None = None
    simulate_health_anomalies: bool = False
    # Export jobs deliberately have their own persistence and artifact knobs.
    # They must not silently inherit the operational-event store in production.
    export_job_store_mode: str = "FILE"
    export_job_collection: str = "ai_ops_export_jobs"
    export_content_backend: str = "FILE"
    export_content_path: Path | None = None
    export_gcs_bucket: str | None = None
    export_ttl_seconds: int = 86400
    export_max_records: int = 100_000
    export_worker_lease_seconds: int = 60
    export_worker_max_attempts: int = 3
    faq_store_mode: str = "FILE"
    faq_store_path: Path | None = None
    faq_firestore_collection_prefix: str = "ai_ops_faq"
    example_store_mode: str = "FILE"
    example_store_path: Path | None = None
    example_firestore_collection_prefix: str = "ai_ops_faq"
    quality_store_mode: str = "FILE"
    quality_store_path: Path | None = None
    quality_firestore_collection: str = "ai_ops_quality_state"
    sync_store_mode: str = "FILE"
    sync_store_path: Path | None = None
    sync_firestore_collection: str = "ai_ops_sync_state"
    sync_adapter_url: str | None = None
    budget_store_mode: str = "FILE"
    budget_store_path: Path | None = None
    budget_firestore_collection: str = "ai_ops_budget_state"
    budget_notification_targets: tuple[str, ...] = (
        "notification-center=NOTIFICATION_CENTER",
    )
    prompt_poc_store_mode: str = "FILE"
    prompt_poc_store_path: Path | None = None
    prompt_poc_firestore_collection: str = "ai_ops_prompt_poc_state"
    prompt_masking_policy_version: str = "mask-v1"
    prompt_active_effective_at: str | None = None
    governance_store_mode: str = "FILE"
    governance_store_path: Path | None = None
    governance_firestore_collection: str = "ai_ops_governance_state"
    # Knowledge Portal BFF bridge (consolidation M1). Defaults keep bridge off.
    knowledge_internal_url: str = ""
    knowledge_service_token: str = ""
    knowledge_delegation_secret: str = ""
    knowledge_bridge_enabled: bool = True
    deployment_tenant_id: str = "local-development"
    relaxed_workflow: bool = False
    min_test_cases_for_review: int = 3

    @classmethod
    def from_env(cls) -> BackofficeSettings:
        project_dir = Path(__file__).resolve().parents[2]
        data_dir = Path(os.environ.get("RAG_DATA_DIR", project_dir.parent / "data"))
        ops_dir = Path(os.environ.get("OPS_DATA_DIR", data_dir / "ops"))
        return cls(
            host=os.environ.get("AI_OPS_BACKOFFICE_HOST", "0.0.0.0"),
            port=int(os.environ.get("AI_OPS_BACKOFFICE_PORT", "8092")),
            service_token=os.environ.get("AI_OPS_BACKOFFICE_TOKEN", ""),
            auth_mode=os.environ.get("AI_OPS_BACKOFFICE_AUTH_MODE", "HEADER").upper(),
            ops_store_mode=(os.environ.get("OPS_STORE_MODE", "FILE") or "FILE").upper(),
            ops_store_path=Path(os.environ.get("OPS_STORE_PATH", ops_dir / "events")).expanduser().resolve(),
            ops_taxonomy_path=Path(
                os.environ.get("OPS_TAXONOMY_PATH", ops_dir / "issue_taxonomy_v1.json")
            ).expanduser().resolve(),
            ops_metrics_path=Path(
                os.environ.get("OPS_METRICS_PATH", ops_dir / "metrics_definitions_v1.json")
            ).expanduser().resolve(),
            ops_classification_rules_path=Path(
                os.environ.get("OPS_CLASSIFICATION_RULES_PATH", ops_dir / "issue_classification_rules.json")
            ).expanduser().resolve(),
            ops_audit_store_mode=(
                os.environ.get("OPS_AUDIT_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            knowledge_portal_url=os.environ.get(
                "KNOWLEDGE_PORTAL_PUBLIC_URL", "http://127.0.0.1:8091"
            ),
            knowledge_internal_url=os.environ.get(
                "KNOWLEDGE_PORTAL_INTERNAL_URL",
                os.environ.get("KNOWLEDGE_PORTAL_PUBLIC_URL", "http://127.0.0.1:8091"),
            ),
            knowledge_service_token=os.environ.get("KNOWLEDGE_PORTAL_TOKEN", ""),
            knowledge_delegation_secret=os.environ.get(
                "KNOWLEDGE_PORTAL_DELEGATION_SECRET",
                os.environ.get("AI_OPS_KNOWLEDGE_DELEGATION_SECRET", ""),
            ),
            knowledge_bridge_enabled=os.environ.get(
                "AI_OPS_KNOWLEDGE_BRIDGE_ENABLED", "true"
            ).lower()
            in {"1", "true", "yes", "on"},
            deployment_tenant_id=os.environ.get(
                "AI_OPS_DEPLOYMENT_TENANT_ID", "local-development"
            ),
            agent_api_url=os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_URL")
            or os.environ.get("AGENT_API_URL"),
            adapter_api_url=os.environ.get("TEAMS_ADAPTER_URL")
            or os.environ.get("ADAPTER_API_URL"),
            ticket_service_url=os.environ.get("TICKET_SERVICE_BASE_URL"),
            default_owner_unit_id=os.environ.get(
                "AI_OPS_DEFAULT_OWNER_UNIT", "IT Service Desk"
            ),
            entra_tenant_id=os.environ.get("AI_OPS_ENTRA_TENANT_ID")
            or os.environ.get("ENTRA_TENANT_ID"),
            entra_client_id=os.environ.get("AI_OPS_ENTRA_CLIENT_ID")
            or os.environ.get("ENTRA_CLIENT_ID"),
            gcp_project_id=os.environ.get("AI_OPS_GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCP_PROJECT"),
            simulate_health_anomalies=os.environ.get(
                "AI_OPS_SIMULATE_HEALTH_ANOMALIES", ""
            ).lower()
            in {"1", "true", "yes"},
            export_job_store_mode=(
                os.environ.get("AI_OPS_EXPORT_JOB_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            export_job_collection=os.environ.get(
                "AI_OPS_EXPORT_JOB_COLLECTION", "ai_ops_export_jobs"
            ),
            export_content_backend=(
                os.environ.get("AI_OPS_EXPORT_CONTENT_BACKEND", "FILE") or "FILE"
            ).upper(),
            export_content_path=Path(
                os.environ.get("AI_OPS_EXPORT_CONTENT_PATH", ops_dir / "exports" / "content")
            ).expanduser().resolve(),
            export_gcs_bucket=os.environ.get("AI_OPS_EXPORT_GCS_BUCKET") or None,
            export_ttl_seconds=int(os.environ.get("AI_OPS_EXPORT_TTL_SECONDS", "86400")),
            export_max_records=int(
                os.environ.get("AI_OPS_EXPORT_MAX_RECORDS", "100000")
            ),
            export_worker_lease_seconds=int(
                os.environ.get("AI_OPS_EXPORT_WORKER_LEASE_SECONDS", "60")
            ),
            export_worker_max_attempts=int(
                os.environ.get("AI_OPS_EXPORT_WORKER_MAX_ATTEMPTS", "3")
            ),
            faq_store_mode=(
                os.environ.get("AI_OPS_FAQ_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            faq_store_path=Path(
                os.environ.get("AI_OPS_FAQ_STORE_PATH", ops_dir / "phase2" / "faqs.json")
            ).expanduser().resolve(),
            faq_firestore_collection_prefix=os.environ.get(
                "AI_OPS_FAQ_FIRESTORE_COLLECTION_PREFIX", "ai_ops_faq"
            ),
            example_store_mode=(
                os.environ.get("AI_OPS_EXAMPLE_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            example_store_path=Path(
                os.environ.get(
                    "AI_OPS_EXAMPLE_STORE_PATH", ops_dir / "phase2" / "examples.json"
                )
            ).expanduser().resolve(),
            example_firestore_collection_prefix=os.environ.get(
                "AI_OPS_EXAMPLE_FIRESTORE_COLLECTION_PREFIX", "ai_ops_faq"
            ),
            quality_store_mode=(
                os.environ.get("AI_OPS_QUALITY_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            quality_store_path=Path(
                os.environ.get(
                    "AI_OPS_QUALITY_STORE_PATH", ops_dir / "phase2" / "quality.json"
                )
            ).expanduser().resolve(),
            quality_firestore_collection=os.environ.get(
                "AI_OPS_QUALITY_FIRESTORE_COLLECTION", "ai_ops_quality_state"
            ),
            sync_store_mode=(
                os.environ.get("AI_OPS_SYNC_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            sync_store_path=Path(
                os.environ.get(
                    "AI_OPS_SYNC_STORE_PATH", ops_dir / "phase2" / "sync_jobs.json"
                )
            ).expanduser().resolve(),
            sync_firestore_collection=os.environ.get(
                "AI_OPS_SYNC_FIRESTORE_COLLECTION", "ai_ops_sync_state"
            ),
            sync_adapter_url=os.environ.get("AI_OPS_SYNC_ADAPTER_URL") or None,
            budget_store_mode=(
                os.environ.get("AI_OPS_BUDGET_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            budget_store_path=Path(
                os.environ.get(
                    "AI_OPS_BUDGET_STORE_PATH", ops_dir / "phase2" / "budgets.json"
                )
            ).expanduser().resolve(),
            budget_firestore_collection=os.environ.get(
                "AI_OPS_BUDGET_FIRESTORE_COLLECTION", "ai_ops_budget_state"
            ),
            budget_notification_targets=tuple(
                item.strip()
                for item in os.environ.get(
                    "AI_OPS_BUDGET_NOTIFICATION_TARGETS",
                    "notification-center=NOTIFICATION_CENTER",
                ).split(",")
                if item.strip()
            ),
            prompt_poc_store_mode=(
                os.environ.get("AI_OPS_PROMPT_POC_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            prompt_poc_store_path=Path(
                os.environ.get(
                    "AI_OPS_PROMPT_POC_STORE_PATH",
                    ops_dir / "phase2" / "prompt_candidates.json",
                )
            ).expanduser().resolve(),
            prompt_poc_firestore_collection=os.environ.get(
                "AI_OPS_PROMPT_POC_FIRESTORE_COLLECTION", "ai_ops_prompt_poc_state"
            ),
            prompt_masking_policy_version=os.environ.get(
                "AI_OPS_PROMPT_MASKING_POLICY_VERSION", "mask-v1"
            ),
            prompt_active_effective_at=os.environ.get("AI_OPS_PROMPT_ACTIVE_EFFECTIVE_AT") or None,
            governance_store_mode=(
                os.environ.get("AI_OPS_GOVERNANCE_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            governance_store_path=Path(
                os.environ.get(
                    "AI_OPS_GOVERNANCE_STORE_PATH",
                    ops_dir / "phase3" / "governance.json",
                )
            ).expanduser().resolve(),
            governance_firestore_collection=os.environ.get(
                "AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION", "ai_ops_governance_state"
            ),
            relaxed_workflow=(
                os.environ.get("AI_OPS_RELAXED_WORKFLOW")
                or os.environ.get("KNOWLEDGE_PORTAL_RELAXED_WORKFLOW")
                or (
                    "false"
                    if (
                        os.environ.get("AGENT_DEPLOYMENT_ENV")
                        or os.environ.get("ENV")
                        or "dev"
                    ).lower()
                    in {"prod", "production", "staging"}
                    else "true"
                )
            ).lower()
            in {"1", "true", "yes", "on"},
            min_test_cases_for_review=int(
                os.environ.get("AI_OPS_MIN_TEST_CASES_FOR_REVIEW")
                or os.environ.get("KNOWLEDGE_PORTAL_MIN_TEST_CASES_FOR_REVIEW")
                or (
                    "0"
                    if (
                        os.environ.get("AI_OPS_RELAXED_WORKFLOW")
                        or os.environ.get("KNOWLEDGE_PORTAL_RELAXED_WORKFLOW")
                        or (
                            "false"
                            if (
                                os.environ.get("AGENT_DEPLOYMENT_ENV")
                                or os.environ.get("ENV")
                                or "dev"
                            ).lower()
                            in {"prod", "production", "staging"}
                            else "true"
                        )
                    ).lower()
                    in {"1", "true", "yes", "on"}
                    else "3"
                )
            ),
        )
