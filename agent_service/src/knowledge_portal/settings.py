from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .settings_env import build_portal_settings_kwargs


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
    catalog_drafts_collection: str = "knowledge_catalog_drafts"
    require_approved_catalog_for_production: bool = False
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
        from agent_service.gemini_backend import (
            GeminiApiBackend,
            peek_gemini_api_backend,
        )

        if peek_gemini_api_backend() is GeminiApiBackend.VERTEX_AI:
            if self.gemini_file_search_sync_enabled or self.require_file_search_parity:
                raise ValueError(
                    "VERTEX_AI disables File Search sync and parity together. "
                    "Do not enable KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED "
                    "or KNOWLEDGE_PORTAL_REQUIRE_FILE_SEARCH_PARITY on Vertex."
                )
        elif self.gemini_file_search_sync_enabled and not self.gemini_file_search_api_key:
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
        return cls(**build_portal_settings_kwargs())

    def effective_relaxed_workflow(self) -> bool:
        """Demo/relaxed gates never apply in production deployments."""
        if (self.deployment_environment or "").strip().lower() == "prod":
            return False
        if not self.demo_mode:
            return False
        return self.relaxed_workflow
