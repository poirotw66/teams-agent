from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PortalSettings:
    host: str
    port: int
    service_token: str
    repository_mode: str
    firestore_project_id: str | None
    firestore_database_id: str
    documents_collection: str
    versions_collection: str
    reviews_collection: str
    releases_collection: str
    audit_collection: str
    config_collection: str
    release_artifact_dir: Path
    data_dir: Path
    chunk_size: int
    chunk_overlap: int
    embedding_model: str | None
    default_owner_unit_id: str
    default_owner_unit_ids: list[str]
    require_dual_approval: bool
    auth_mode: str
    entra_tenant_id: str | None
    entra_client_id: str | None
    entra_allowed_audiences: list[str]
    entra_platform_roles: set[str]
    entra_manager_roles: set[str]
    entra_reviewer_roles: set[str]
    entra_auditor_roles: set[str]
    agent_api_url: str | None
    agent_api_token: str | None
    state_path: Path

    @classmethod
    def from_env(cls) -> PortalSettings:
        repo_root = Path(__file__).resolve().parents[3]
        data_dir = Path(os.environ.get("KNOWLEDGE_PORTAL_DATA_DIR", repo_root / "data"))
        default_owner_unit_id = os.environ.get(
            "KNOWLEDGE_PORTAL_DEFAULT_OWNER_UNIT", "IT Service Desk"
        )
        return cls(
            host=os.environ.get("KNOWLEDGE_PORTAL_HOST", "0.0.0.0"),
            port=int(os.environ.get("KNOWLEDGE_PORTAL_PORT", "8090")),
            service_token=os.environ.get("KNOWLEDGE_PORTAL_TOKEN", ""),
            repository_mode=os.environ.get(
                "KNOWLEDGE_PORTAL_REPOSITORY_MODE", "MEMORY"
            ).upper(),
            firestore_project_id=os.environ.get("GCP_PROJECT_ID")
            or os.environ.get("KNOWLEDGE_PORTAL_FIRESTORE_PROJECT"),
            firestore_database_id=os.environ.get(
                "KNOWLEDGE_PORTAL_FIRESTORE_DATABASE", "(default)"
            ),
            documents_collection=os.environ.get(
                "KNOWLEDGE_PORTAL_DOCUMENTS_COLLECTION", "knowledge_documents"
            ),
            versions_collection=os.environ.get(
                "KNOWLEDGE_PORTAL_VERSIONS_COLLECTION", "knowledge_versions"
            ),
            reviews_collection=os.environ.get(
                "KNOWLEDGE_PORTAL_REVIEWS_COLLECTION", "knowledge_reviews"
            ),
            releases_collection=os.environ.get(
                "KNOWLEDGE_PORTAL_RELEASES_COLLECTION", "knowledge_releases"
            ),
            audit_collection=os.environ.get(
                "KNOWLEDGE_PORTAL_AUDIT_COLLECTION", "knowledge_audit_events"
            ),
            config_collection=os.environ.get(
                "KNOWLEDGE_PORTAL_CONFIG_COLLECTION", "knowledge_portal_config"
            ),
            release_artifact_dir=Path(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_RELEASE_DIR",
                    data_dir / "releases",
                )
            ),
            data_dir=data_dir,
            chunk_size=int(os.environ.get("RAG_CHUNK_SIZE", "900")),
            chunk_overlap=int(os.environ.get("RAG_CHUNK_OVERLAP", "120")),
            embedding_model=os.environ.get("RAG_EMBEDDING_MODEL") or None,
            default_owner_unit_id=default_owner_unit_id,
            default_owner_unit_ids=[
                item.strip()
                for item in os.environ.get(
                    "KNOWLEDGE_PORTAL_OWNER_UNITS",
                    default_owner_unit_id,
                ).split(",")
                if item.strip()
            ],
            require_dual_approval=os.environ.get(
                "KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL", "true"
            ).lower()
            in {"1", "true", "yes"},
            auth_mode=os.environ.get("KNOWLEDGE_PORTAL_AUTH_MODE", "HEADER").upper(),
            entra_tenant_id=os.environ.get("KNOWLEDGE_PORTAL_ENTRA_TENANT_ID")
            or os.environ.get("ENTRA_TENANT_ID"),
            entra_client_id=os.environ.get("KNOWLEDGE_PORTAL_ENTRA_CLIENT_ID")
            or os.environ.get("ENTRA_CLIENT_ID"),
            entra_allowed_audiences=[
                item.strip()
                for item in os.environ.get("KNOWLEDGE_PORTAL_ENTRA_AUDIENCES", "").split(",")
                if item.strip()
            ],
            entra_platform_roles=set(
                filter(
                    None,
                    os.environ.get("KNOWLEDGE_PORTAL_ENTRA_PLATFORM_ROLES", "Knowledge.PlatformAdmin").split(","),
                )
            ),
            entra_manager_roles=set(
                filter(
                    None,
                    os.environ.get("KNOWLEDGE_PORTAL_ENTRA_MANAGER_ROLES", "Knowledge.Manager").split(","),
                )
            ),
            entra_reviewer_roles=set(
                filter(
                    None,
                    os.environ.get("KNOWLEDGE_PORTAL_ENTRA_REVIEWER_ROLES", "Knowledge.Reviewer").split(","),
                )
            ),
            entra_auditor_roles=set(
                filter(
                    None,
                    os.environ.get("KNOWLEDGE_PORTAL_ENTRA_AUDITOR_ROLES", "Knowledge.Auditor").split(","),
                )
            ),
            agent_api_url=os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_URL"),
            agent_api_token=os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_TOKEN")
            or os.environ.get("AGENT_SERVICE_TOKEN"),
            state_path=Path(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_STATE_PATH",
                    data_dir / "portal_state" / "portal_state.json",
                )
            ).expanduser().resolve(),
        )
