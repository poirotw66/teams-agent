from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PdfConverterAuthMode(str, Enum):
    """Supported authentication modes for the PDF converter."""

    BEARER = "BEARER"
    GOOGLE_ID_TOKEN = "GOOGLE_ID_TOKEN"


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
    relaxed_workflow: bool
    demo_mode: bool
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
    drafts_dir: Path
    max_asset_bytes: int
    max_assets_per_version: int
    delegation_secret: str = ""
    require_service_token_with_delegation: bool = True
    pdf_converter_url: str | None = None
    pdf_converter_token: str | None = None
    pdf_converter_auth_mode: PdfConverterAuthMode = PdfConverterAuthMode.BEARER
    pdf_converter_timeout_seconds: float = 120.0
    pdf_converter_engine: str = "legacy_text"
    pdf_sync_max_bytes: int = 5 * 1024 * 1024
    pdf_sync_max_pages: int = 20
    pdf_max_upload_bytes: int = 50 * 1024 * 1024
    document_parser: str = "PDF_CONVERTER"
    document_ai_processor_name: str | None = None
    pdf_jobs_dir: Path | None = None
    pdf_prompt_template: str = "slide"
    original_assets_dir: Path | None = None
    artifact_storage_backend: str = "NONE"
    artifact_gcs_bucket: str | None = None
    artifact_storage_path: Path | None = None
    default_tenant_id: str = "default"
    source_store_mode: str = "NONE"
    source_store_path: Path | None = None
    release_gcs_bucket: str | None = None
    release_gcs_prefix: str = "knowledge-releases"
    agent_api_auth_mode: str = "BEARER"
    deployment_environment: str = "dev"
    release_purpose: str = "PRODUCTION"
    gemini_file_search_sync_enabled: bool = False
    gemini_file_search_api_key: str | None = None
    require_file_search_parity: bool = False
    ingestion_tasks_queue: str | None = None
    ingestion_worker_url: str | None = None
    ingestion_worker_service_account: str | None = None

    def __post_init__(self) -> None:
        try:
            auth_mode = PdfConverterAuthMode(self.pdf_converter_auth_mode)
        except ValueError as error:
            supported_modes = ", ".join(mode.value for mode in PdfConverterAuthMode)
            raise ValueError(
                f"KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE must be one of {supported_modes}."
            ) from error
        object.__setattr__(self, "pdf_converter_auth_mode", auth_mode)
        if auth_mode is PdfConverterAuthMode.GOOGLE_ID_TOKEN and not self.pdf_converter_url:
            raise ValueError(
                "KNOWLEDGE_PORTAL_PDF_CONVERTER_URL is required when "
                "KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE=GOOGLE_ID_TOKEN."
            )
        if self.deployment_environment not in {"dev", "test", "poc", "prod"}:
            raise ValueError("AGENT_DEPLOYMENT_ENV must be one of dev, test, poc, or prod.")
        if self.release_purpose not in {"PRODUCTION", "E2E", "SHADOW"}:
            raise ValueError("KNOWLEDGE_PORTAL_RELEASE_PURPOSE must be PRODUCTION, E2E, or SHADOW.")
        if self.deployment_environment == "prod" and self.release_purpose != "PRODUCTION":
            raise ValueError("Production Portal deployments may only publish PRODUCTION releases.")
        if self.document_parser not in {"PDF_CONVERTER", "DOCUMENT_AI"}:
            raise ValueError(
                "KNOWLEDGE_PORTAL_DOCUMENT_PARSER must be PDF_CONVERTER or DOCUMENT_AI."
            )
        if self.document_parser == "DOCUMENT_AI" and not self.document_ai_processor_name:
            raise ValueError(
                "KNOWLEDGE_PORTAL_DOCUMENT_AI_PROCESSOR is required for DOCUMENT_AI."
            )
        if self.gemini_file_search_sync_enabled and not self.gemini_file_search_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when File Search release sync is enabled."
            )
        if self.require_file_search_parity and not self.gemini_file_search_sync_enabled:
            raise ValueError(
                "File Search release sync must be enabled when parity is required."
            )
        task_values = (
            self.ingestion_tasks_queue,
            self.ingestion_worker_url,
            self.ingestion_worker_service_account,
        )
        if any(task_values) and not all(task_values):
            raise ValueError(
                "Ingestion Cloud Tasks queue, worker URL, and service account "
                "must be configured together."
            )

    @classmethod
    def from_env(cls) -> PortalSettings:
        repo_root = Path(__file__).resolve().parents[3]
        data_dir = Path(os.environ.get("KNOWLEDGE_PORTAL_DATA_DIR", repo_root / "data"))
        default_owner_unit_id = os.environ.get(
            "KNOWLEDGE_PORTAL_DEFAULT_OWNER_UNIT", "IT Service Desk"
        )
        state_path = (
            Path(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_STATE_PATH",
                    data_dir / "portal_state" / "portal_state.json",
                )
            )
            .expanduser()
            .resolve()
        )
        repository_mode_raw = os.environ.get("KNOWLEDGE_PORTAL_REPOSITORY_MODE")
        if repository_mode_raw:
            repository_mode = repository_mode_raw.upper()
        elif state_path.exists():
            repository_mode = "FILE"
        else:
            repository_mode = "MEMORY"
        pdf_jobs_dir = (
            Path(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_PDF_JOBS_DIR",
                    data_dir / "portal_pdf_jobs",
                )
            )
            .expanduser()
            .resolve()
        )
        return cls(
            host=os.environ.get("KNOWLEDGE_PORTAL_HOST", "0.0.0.0"),
            port=int(os.environ.get("KNOWLEDGE_PORTAL_PORT", "8090")),
            service_token=os.environ.get("KNOWLEDGE_PORTAL_TOKEN", "").strip(),
            repository_mode=repository_mode,
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
                "KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL", "false"
            ).lower()
            in {"1", "true", "yes"},
            relaxed_workflow=os.environ.get("KNOWLEDGE_PORTAL_RELAXED_WORKFLOW", "true").lower()
            in {"1", "true", "yes"},
            demo_mode=os.environ.get("KNOWLEDGE_PORTAL_DEMO_MODE", "true").lower()
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
                    os.environ.get(
                        "KNOWLEDGE_PORTAL_ENTRA_PLATFORM_ROLES", "Knowledge.PlatformAdmin"
                    ).split(","),
                )
            ),
            entra_manager_roles=set(
                filter(
                    None,
                    os.environ.get(
                        "KNOWLEDGE_PORTAL_ENTRA_MANAGER_ROLES", "Knowledge.Manager"
                    ).split(","),
                )
            ),
            entra_reviewer_roles=set(
                filter(
                    None,
                    os.environ.get(
                        "KNOWLEDGE_PORTAL_ENTRA_REVIEWER_ROLES", "Knowledge.Reviewer"
                    ).split(","),
                )
            ),
            entra_auditor_roles=set(
                filter(
                    None,
                    os.environ.get(
                        "KNOWLEDGE_PORTAL_ENTRA_AUDITOR_ROLES", "Knowledge.Auditor"
                    ).split(","),
                )
            ),
            agent_api_url=(
                os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_URL") or os.environ.get("AGENT_API_URL")
            ),
            agent_api_token=(
                os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_TOKEN")
                or os.environ.get("AGENT_SERVICE_TOKEN")
                or os.environ.get("AGENT_RELOAD_TOKEN")
                or os.environ.get("SERVICE_TOKEN")
            ),
            state_path=state_path,
            drafts_dir=Path(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_DRAFTS_DIR",
                    data_dir / "portal_drafts",
                )
            )
            .expanduser()
            .resolve(),
            max_asset_bytes=int(os.environ.get("KNOWLEDGE_PORTAL_MAX_ASSET_BYTES", "2000000")),
            max_assets_per_version=int(
                os.environ.get("KNOWLEDGE_PORTAL_MAX_ASSETS_PER_VERSION", "20")
            ),
            delegation_secret=os.environ.get("KNOWLEDGE_PORTAL_DELEGATION_SECRET", ""),
            require_service_token_with_delegation=os.environ.get(
                "KNOWLEDGE_PORTAL_REQUIRE_SERVICE_TOKEN_WITH_DELEGATION", "true"
            ).lower()
            in {"1", "true", "yes", "on"},
            pdf_converter_url=(
                os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_URL")
                or os.environ.get("PDF_CONVERTER_URL")
                or None
            ),
            pdf_converter_token=(
                os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_TOKEN")
                or os.environ.get("PDF_CONVERTER_TOKEN")
                or None
            ),
            pdf_converter_auth_mode=(
                os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE")
                or os.environ.get("PDF_CONVERTER_AUTH_MODE")
                or "BEARER"
            )
            .strip()
            .upper(),
            pdf_converter_timeout_seconds=float(
                os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_TIMEOUT_SECONDS", "120")
            ),
            pdf_converter_engine=(
                os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE")
                or os.environ.get("PDF_CONVERTER_ENGINE")
                or "legacy_text"
            ).strip()
            or "legacy_text",
            pdf_sync_max_bytes=int(
                os.environ.get("KNOWLEDGE_PORTAL_PDF_SYNC_MAX_BYTES", str(5 * 1024 * 1024))
            ),
            pdf_sync_max_pages=int(os.environ.get("KNOWLEDGE_PORTAL_PDF_SYNC_MAX_PAGES", "20")),
            pdf_max_upload_bytes=int(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_PDF_MAX_UPLOAD_BYTES",
                    str(50 * 1024 * 1024),
                )
            ),
            document_parser=os.environ.get(
                "KNOWLEDGE_PORTAL_DOCUMENT_PARSER",
                "PDF_CONVERTER",
            )
            .strip()
            .upper(),
            document_ai_processor_name=(
                os.environ.get("KNOWLEDGE_PORTAL_DOCUMENT_AI_PROCESSOR") or None
            ),
            pdf_jobs_dir=pdf_jobs_dir,
            pdf_prompt_template=os.environ.get("KNOWLEDGE_PORTAL_PDF_PROMPT_TEMPLATE", "slide"),
            original_assets_dir=(
                Path(os.environ["KNOWLEDGE_PORTAL_ORIGINAL_ASSETS_DIR"]).expanduser().resolve()
                if os.environ.get("KNOWLEDGE_PORTAL_ORIGINAL_ASSETS_DIR")
                else None
            ),
            artifact_storage_backend=(
                os.environ.get("KNOWLEDGE_PORTAL_ARTIFACT_STORAGE_BACKEND")
                or os.environ.get("AI_OPS_ARTIFACT_STORAGE_BACKEND")
                or "NONE"
            ).upper(),
            artifact_gcs_bucket=(
                os.environ.get("KNOWLEDGE_PORTAL_ARTIFACT_GCS_BUCKET")
                or os.environ.get("AI_OPS_ARTIFACT_GCS_BUCKET")
                or None
            ),
            artifact_storage_path=(
                Path(os.environ["KNOWLEDGE_PORTAL_ARTIFACT_STORAGE_PATH"]).expanduser().resolve()
                if os.environ.get("KNOWLEDGE_PORTAL_ARTIFACT_STORAGE_PATH")
                else None
            ),
            default_tenant_id=os.environ.get("KNOWLEDGE_PORTAL_DEFAULT_TENANT_ID", "default"),
            source_store_mode=(
                os.environ.get("KNOWLEDGE_PORTAL_SOURCE_STORE_MODE")
                or os.environ.get("AI_OPS_SOURCE_STORE_MODE")
                or "NONE"
            ).upper(),
            source_store_path=(
                Path(os.environ["KNOWLEDGE_PORTAL_SOURCE_STORE_PATH"]).expanduser().resolve()
                if os.environ.get("KNOWLEDGE_PORTAL_SOURCE_STORE_PATH")
                else None
            ),
            release_gcs_bucket=(os.environ.get("KNOWLEDGE_PORTAL_RELEASE_GCS_BUCKET") or None),
            release_gcs_prefix=(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_RELEASE_GCS_PREFIX",
                    "knowledge-releases",
                ).strip("/")
            ),
            agent_api_auth_mode=os.environ.get(
                "KNOWLEDGE_PORTAL_AGENT_API_AUTH_MODE",
                "BEARER",
            ).upper(),
            deployment_environment=os.environ.get(
                "AGENT_DEPLOYMENT_ENV",
                "dev",
            )
            .strip()
            .lower(),
            release_purpose=os.environ.get(
                "KNOWLEDGE_PORTAL_RELEASE_PURPOSE",
                "PRODUCTION",
            )
            .strip()
            .upper(),
            gemini_file_search_sync_enabled=os.environ.get(
                "KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            gemini_file_search_api_key=(
                os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
                or None
            ),
            require_file_search_parity=os.environ.get(
                "KNOWLEDGE_PORTAL_REQUIRE_FILE_SEARCH_PARITY",
                "false",
            ).lower()
            in {"1", "true", "yes", "on"},
            ingestion_tasks_queue=(
                os.environ.get("KNOWLEDGE_PORTAL_INGESTION_TASKS_QUEUE") or None
            ),
            ingestion_worker_url=(
                os.environ.get("KNOWLEDGE_PORTAL_INGESTION_WORKER_URL") or None
            ),
            ingestion_worker_service_account=(
                os.environ.get(
                    "KNOWLEDGE_PORTAL_INGESTION_WORKER_SERVICE_ACCOUNT"
                )
                or None
            ),
        )

    def effective_relaxed_workflow(self) -> bool:
        """GOVERNED profile always disables relaxed workflow."""
        if not self.demo_mode:
            return False
        return self.relaxed_workflow
