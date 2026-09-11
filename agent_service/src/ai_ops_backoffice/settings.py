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
    faq_artifact_dir: Path | None = None
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
    teams_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ai-ops@example.com"
    budget_eval_interval_seconds: int = 300
    default_personal_daily_budget_enabled: bool = True
    default_personal_daily_budget_threshold: float = 50.0
    default_personal_daily_warning_threshold: float = 40.0
    api_anomaly_check_enabled: bool = True
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
    pricing_store_mode: str = "FILE"
    pricing_store_path: Path | None = None
    pricing_firestore_collection: str = "ai_ops_pricing_state"
    eval_store_mode: str | None = None
    eval_store_path: Path | None = None
    eval_firestore_collection: str = "ai_ops_evaluation_state"
    gate_store_mode: str | None = None
    gate_store_path: Path | None = None
    gate_firestore_collection_prefix: str = "ai_ops_gate"
    fixture_store_mode: str | None = None
    fixture_store_path: Path | None = None
    fixture_firestore_collection_prefix: str = "ai_ops_fixture"
    job_store_mode: str | None = None
    job_store_path: Path | None = None
    job_firestore_collection: str = "ai_ops_execution_jobs"
    environment: str = "dev"

    def validate_for_production(self) -> list[str]:
        """Validate settings for production deployment to prevent ephemeral data loss."""
        issues: list[str] = []
        is_prod = self.environment in {"prod", "production"}
        if is_prod:
            if self.auth_mode != "ENTRA":
                issues.append("auth_mode must be ENTRA in production; configure ENTRA.")
            eval_mode = self.eval_store_mode or self.ops_store_mode
            gate_mode = self.gate_store_mode or self.ops_store_mode
            fixture_mode = self.fixture_store_mode or self.ops_store_mode
            job_mode = self.job_store_mode or self.ops_store_mode
            file_stores = [
                ("ops_store_mode", self.ops_store_mode),
                ("ops_audit_store_mode", self.ops_audit_store_mode),
                ("export_job_store_mode", self.export_job_store_mode),
                ("faq_store_mode", self.faq_store_mode),
                ("example_store_mode", self.example_store_mode),
                ("quality_store_mode", self.quality_store_mode),
                ("sync_store_mode", self.sync_store_mode),
                ("budget_store_mode", self.budget_store_mode),
                ("governance_store_mode", self.governance_store_mode),
                ("prompt_poc_store_mode", self.prompt_poc_store_mode),
                ("eval_store_mode", eval_mode),
                ("gate_store_mode", gate_mode),
                ("fixture_store_mode", fixture_mode),
                ("job_store_mode", job_mode),
            ]
            for name, mode in file_stores:
                if mode in {"FILE", "MEMORY"}:
                    issues.append(f"{name} must not be {mode} in production; configure FIRESTORE.")
        return issues

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
            faq_artifact_dir=Path(
                os.environ.get(
                    "AI_OPS_FAQ_ARTIFACT_DIR", ops_dir / "phase2" / "faq-artifacts"
                )
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
            sync_adapter_url=(
                os.environ.get("AI_OPS_SYNC_ADAPTER_URL")
                or os.environ.get("KNOWLEDGE_PORTAL_INTERNAL_URL")
                or os.environ.get("KNOWLEDGE_PORTAL_PUBLIC_URL")
                or "http://127.0.0.1:8091"
            ),
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
            teams_webhook_url=os.environ.get("AI_OPS_TEAMS_WEBHOOK_URL", ""),
            smtp_host=os.environ.get("AI_OPS_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("AI_OPS_SMTP_PORT", "587")),
            smtp_user=os.environ.get("AI_OPS_SMTP_USER", ""),
            smtp_password=os.environ.get("AI_OPS_SMTP_PASSWORD", ""),
            smtp_from=os.environ.get("AI_OPS_SMTP_FROM", "ai-ops@example.com"),
            budget_eval_interval_seconds=int(
                os.environ.get("AI_OPS_BUDGET_EVAL_INTERVAL_SECONDS", "300")
            ),
            default_personal_daily_budget_enabled=os.environ.get(
                "AI_OPS_DEFAULT_PERSONAL_DAILY_BUDGET_ENABLED", "true"
            ).lower() in {"1", "true", "yes"},
            default_personal_daily_budget_threshold=float(
                os.environ.get("AI_OPS_DEFAULT_PERSONAL_DAILY_BUDGET_THRESHOLD", "50.0")
            ),
            default_personal_daily_warning_threshold=float(
                os.environ.get("AI_OPS_DEFAULT_PERSONAL_DAILY_WARNING_THRESHOLD", "40.0")
            ),
            api_anomaly_check_enabled=os.environ.get(
                "AI_OPS_API_ANOMALY_CHECK_ENABLED", "true"
            ).lower() in {"1", "true", "yes"},
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
            pricing_store_mode=(
                os.environ.get("AI_OPS_PRICING_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            pricing_store_path=Path(
                os.environ.get(
                    "AI_OPS_PRICING_STORE_PATH",
                    ops_dir / "phase2" / "pricing_rules.json",
                )
            ).expanduser().resolve(),
            pricing_firestore_collection=os.environ.get(
                "AIOPS_PRICING_FIRESTORE_COLLECTION", "ai_ops_pricing_state"
            ),
            eval_store_mode=(
                os.environ.get("AI_OPS_EVAL_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            eval_store_path=Path(
                os.environ.get(
                    "AI_OPS_EVAL_STORE_PATH",
                    ops_dir / "evaluations" / "golden_evals.json",
                )
            ).expanduser().resolve(),
            eval_firestore_collection=os.environ.get(
                "AI_OPS_EVAL_FIRESTORE_COLLECTION", "ai_ops_evaluation_state"
            ),
            gate_store_mode=(
                os.environ.get("AI_OPS_GATE_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            gate_store_path=Path(
                os.environ.get(
                    "AI_OPS_GATE_STORE_PATH",
                    ops_dir / "evaluations" / "gates",
                )
            ).expanduser().resolve(),
            gate_firestore_collection_prefix=os.environ.get(
                "AI_OPS_GATE_FIRESTORE_COLLECTION_PREFIX", "ai_ops_gate"
            ),
            fixture_store_mode=(
                os.environ.get("AI_OPS_FIXTURE_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            fixture_store_path=Path(
                os.environ.get(
                    "AI_OPS_FIXTURE_STORE_PATH",
                    ops_dir / "evaluations" / "fixtures",
                )
            ).expanduser().resolve(),
            fixture_firestore_collection_prefix=os.environ.get(
                "AI_OPS_FIXTURE_FIRESTORE_COLLECTION_PREFIX", "ai_ops_fixture"
            ),
            job_store_mode=(
                os.environ.get("AI_OPS_JOB_STORE_MODE", "FILE") or "FILE"
            ).upper(),
            job_store_path=Path(
                os.environ.get(
                    "AI_OPS_JOB_STORE_PATH",
                    ops_dir / "evaluations" / "jobs",
                )
            ).expanduser().resolve(),
            job_firestore_collection=os.environ.get(
                "AI_OPS_JOB_FIRESTORE_COLLECTION", "ai_ops_execution_jobs"
            ),
            environment=(
                os.environ.get("AI_OPS_DEPLOYMENT_ENV")
                or os.environ.get("AGENT_DEPLOYMENT_ENV")
                or os.environ.get("ENV")
                or "dev"
            ).lower(),
        )
