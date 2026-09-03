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
        )
