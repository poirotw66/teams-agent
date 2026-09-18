from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings_env import build_backoffice_settings_kwargs


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
    knowledge_auth_mode: str = "BEARER"
    knowledge_timeout_seconds: float = 180.0
    source_delegation_secret: str = ""
    knowledge_bridge_enabled: bool = True
    knowledge_in_process: bool = True
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
    source_store_mode: str = "FILE"
    source_store_path: Path | None = None
    artifact_storage_backend: str = "FILE"
    artifact_storage_path: Path | None = None
    artifact_gcs_bucket: str | None = None
    environment: str = "dev"
    workers_enabled: bool = True
    query_cache_ttl_seconds: int = 120
    freshness_firestore_collection: str = "freshness_state"
    console_v2_enabled: bool = True
    legacy_shell_enabled: bool = False

    def validate_for_production(self, *, require_gcp_project: bool = False) -> list[str]:
        """Validate settings for production deployment to prevent ephemeral data loss."""
        from .config_validator import validate_backoffice_settings

        return validate_backoffice_settings(
            self,
            require_production=self.environment in {"prod", "production", "staging"},
            require_gcp_project=require_gcp_project,
        )

    @classmethod
    def from_env(cls) -> BackofficeSettings:
        return cls(**build_backoffice_settings_kwargs())

