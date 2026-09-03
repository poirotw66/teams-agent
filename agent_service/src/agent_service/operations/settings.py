from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class OpsSettings:
    enabled: bool
    store_mode: str
    store_path: Path
    taxonomy_path: Path
    metrics_path: Path
    environment: str
    default_retention_days: int
    transcript_retention_days: int
    audit_retention_days: int
    async_emit: bool
    classification_rules_path: Path
    firestore_project: str | None
    firestore_database: str | None
    firestore_collection: str
    bigquery_enabled: bool
    bigquery_project: str | None
    bigquery_dataset: str
    bigquery_table: str
    audit_store_mode: str
    audit_firestore_collection: str
    delivery_enabled: bool = True
    delivery_firestore_collection: str = "operational_delivery_outbox"
    delivery_lease_seconds: float = 30.0
    delivery_timeout_seconds: float = 20.0
    delivery_retry_base_seconds: float = 1.0
    delivery_retry_max_seconds: float = 300.0
    delivery_poll_seconds: float = 1.0
    delivery_batch_size: int = 100

    @classmethod
    def from_env(cls, data_dir: Path | None = None) -> OpsSettings:
        project_dir = Path(__file__).resolve().parents[3]
        root_data = data_dir or Path(environ.get("RAG_DATA_DIR", project_dir.parent / "data"))
        ops_dir = Path(environ.get("OPS_DATA_DIR", root_data / "ops"))
        return cls(
            enabled=_bool_env("OPS_EVENTS_ENABLED", True),
            store_mode=(environ.get("OPS_STORE_MODE", "FILE") or "FILE").upper(),
            store_path=Path(environ.get("OPS_STORE_PATH", ops_dir / "events")).expanduser().resolve(),
            taxonomy_path=Path(
                environ.get("OPS_TAXONOMY_PATH", ops_dir / "issue_taxonomy_v1.json")
            ).expanduser().resolve(),
            metrics_path=Path(
                environ.get("OPS_METRICS_PATH", ops_dir / "metrics_definitions_v1.json")
            ).expanduser().resolve(),
            environment=(
                environ.get("AGENT_DEPLOYMENT_ENV")
                or environ.get("RAG_DEPLOYMENT_ENV")
                or "dev"
            ),
            default_retention_days=int(environ.get("OPS_DEFAULT_RETENTION_DAYS", "365")),
            transcript_retention_days=int(environ.get("OPS_TRANSCRIPT_RETENTION_DAYS", "365")),
            audit_retention_days=int(environ.get("OPS_AUDIT_RETENTION_DAYS", "1095")),
            async_emit=_bool_env("OPS_ASYNC_EMIT", True),
            classification_rules_path=Path(
                environ.get("OPS_CLASSIFICATION_RULES_PATH", ops_dir / "issue_classification_rules.json")
            ).expanduser().resolve(),
            firestore_project=environ.get("OPS_FIRESTORE_PROJECT") or environ.get("GCP_PROJECT_ID"),
            firestore_database=environ.get("OPS_FIRESTORE_DATABASE"),
            firestore_collection=environ.get("OPS_FIRESTORE_COLLECTION", "operational_events"),
            bigquery_enabled=_bool_env("OPS_BIGQUERY_ENABLED", False),
            bigquery_project=environ.get("OPS_BIGQUERY_PROJECT") or environ.get("GCP_PROJECT_ID"),
            bigquery_dataset=environ.get("OPS_BIGQUERY_DATASET", "ai_ops_analytics"),
            bigquery_table=environ.get("OPS_BIGQUERY_TABLE", "operational_events"),
            audit_store_mode=(environ.get("OPS_AUDIT_STORE_MODE", "MEMORY") or "MEMORY").upper(),
            audit_firestore_collection=environ.get("OPS_AUDIT_FIRESTORE_COLLECTION", "audit_events"),
            delivery_enabled=_bool_env("OPS_DELIVERY_ENABLED", True),
            delivery_firestore_collection=environ.get(
                "OPS_DELIVERY_FIRESTORE_COLLECTION", "operational_delivery_outbox"
            ),
            delivery_lease_seconds=float(environ.get("OPS_DELIVERY_LEASE_SECONDS", "30")),
            delivery_timeout_seconds=float(environ.get("OPS_DELIVERY_TIMEOUT_SECONDS", "20")),
            delivery_retry_base_seconds=float(
                environ.get("OPS_DELIVERY_RETRY_BASE_SECONDS", "1")
            ),
            delivery_retry_max_seconds=float(
                environ.get("OPS_DELIVERY_RETRY_MAX_SECONDS", "300")
            ),
            delivery_poll_seconds=float(environ.get("OPS_DELIVERY_POLL_SECONDS", "1")),
            delivery_batch_size=int(environ.get("OPS_DELIVERY_BATCH_SIZE", "100")),
        )
