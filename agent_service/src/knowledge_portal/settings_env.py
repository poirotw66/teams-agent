"""Environment parsing helpers for PortalSettings.from_env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _truthy(value: str, *, extras: set[str] | None = None) -> bool:
    accepted = {"1", "true", "yes"}
    if extras:
        accepted = accepted | extras
    return value.lower() in accepted


def _csv_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _csv_set(raw: str) -> set[str]:
    return set(filter(None, raw.split(",")))


def _optional_path(key: str) -> Path | None:
    raw = os.environ.get(key)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _optional_env(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


def resolve_portal_paths() -> tuple[Path, Path, Path, str]:
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
    return data_dir, state_path, repo_root, default_owner_unit_id


def resolve_repository_mode(state_path: Path) -> str:
    repository_mode_raw = os.environ.get("KNOWLEDGE_PORTAL_REPOSITORY_MODE")
    if repository_mode_raw:
        return repository_mode_raw.upper()
    if state_path.exists():
        return "FILE"
    return "MEMORY"


def load_server_auth_env() -> dict[str, Any]:
    return {
        "host": os.environ.get("KNOWLEDGE_PORTAL_HOST", "0.0.0.0"),
        "port": int(os.environ.get("KNOWLEDGE_PORTAL_PORT", "8090")),
        "service_token": os.environ.get("KNOWLEDGE_PORTAL_TOKEN", "").strip(),
        "auth_mode": os.environ.get("KNOWLEDGE_PORTAL_AUTH_MODE", "HEADER").upper(),
        "entra_tenant_id": _optional_env(
            "KNOWLEDGE_PORTAL_ENTRA_TENANT_ID", "ENTRA_TENANT_ID"
        ),
        "entra_client_id": _optional_env(
            "KNOWLEDGE_PORTAL_ENTRA_CLIENT_ID", "ENTRA_CLIENT_ID"
        ),
        "entra_allowed_audiences": _csv_list(
            os.environ.get("KNOWLEDGE_PORTAL_ENTRA_AUDIENCES", "")
        ),
        "entra_platform_roles": _csv_set(
            os.environ.get(
                "KNOWLEDGE_PORTAL_ENTRA_PLATFORM_ROLES", "Knowledge.PlatformAdmin"
            )
        ),
        "entra_manager_roles": _csv_set(
            os.environ.get(
                "KNOWLEDGE_PORTAL_ENTRA_MANAGER_ROLES", "Knowledge.Manager"
            )
        ),
        "entra_reviewer_roles": _csv_set(
            os.environ.get(
                "KNOWLEDGE_PORTAL_ENTRA_REVIEWER_ROLES", "Knowledge.Reviewer"
            )
        ),
        "entra_auditor_roles": _csv_set(
            os.environ.get(
                "KNOWLEDGE_PORTAL_ENTRA_AUDITOR_ROLES", "Knowledge.Auditor"
            )
        ),
        "delegation_secret": os.environ.get("KNOWLEDGE_PORTAL_DELEGATION_SECRET", ""),
        "require_service_token_with_delegation": _truthy(
            os.environ.get(
                "KNOWLEDGE_PORTAL_REQUIRE_SERVICE_TOKEN_WITH_DELEGATION", "true"
            ),
            extras={"on"},
        ),
    }


def load_firestore_collection_env() -> dict[str, Any]:
    return {
        "firestore_project_id": (
            os.environ.get("GCP_PROJECT_ID")
            or os.environ.get("KNOWLEDGE_PORTAL_FIRESTORE_PROJECT")
        ),
        "firestore_database_id": os.environ.get(
            "KNOWLEDGE_PORTAL_FIRESTORE_DATABASE", "(default)"
        ),
        "documents_collection": os.environ.get(
            "KNOWLEDGE_PORTAL_DOCUMENTS_COLLECTION", "knowledge_documents"
        ),
        "versions_collection": os.environ.get(
            "KNOWLEDGE_PORTAL_VERSIONS_COLLECTION", "knowledge_versions"
        ),
        "reviews_collection": os.environ.get(
            "KNOWLEDGE_PORTAL_REVIEWS_COLLECTION", "knowledge_reviews"
        ),
        "releases_collection": os.environ.get(
            "KNOWLEDGE_PORTAL_RELEASES_COLLECTION", "knowledge_releases"
        ),
        "audit_collection": os.environ.get(
            "KNOWLEDGE_PORTAL_AUDIT_COLLECTION", "knowledge_audit_events"
        ),
        "config_collection": os.environ.get(
            "KNOWLEDGE_PORTAL_CONFIG_COLLECTION", "knowledge_portal_config"
        ),
    }


def load_workflow_feature_env(default_owner_unit_id: str) -> dict[str, Any]:
    return {
        "default_owner_unit_id": default_owner_unit_id,
        "default_owner_unit_ids": _csv_list(
            os.environ.get(
                "KNOWLEDGE_PORTAL_OWNER_UNITS",
                default_owner_unit_id,
            )
        ),
        "require_dual_approval": _truthy(
            os.environ.get("KNOWLEDGE_PORTAL_REQUIRE_DUAL_APPROVAL", "false")
        ),
        "relaxed_workflow": _truthy(
            os.environ.get("KNOWLEDGE_PORTAL_RELAXED_WORKFLOW", "true")
        ),
        "demo_mode": _truthy(os.environ.get("KNOWLEDGE_PORTAL_DEMO_MODE", "true")),
        "chunk_size": int(os.environ.get("RAG_CHUNK_SIZE", "900")),
        "chunk_overlap": int(os.environ.get("RAG_CHUNK_OVERLAP", "120")),
        "embedding_model": os.environ.get("RAG_EMBEDDING_MODEL") or None,
        "default_tenant_id": os.environ.get(
            "KNOWLEDGE_PORTAL_DEFAULT_TENANT_ID", "default"
        ),
        "deployment_environment": os.environ.get(
            "AGENT_DEPLOYMENT_ENV",
            "dev",
        )
        .strip()
        .lower(),
        "release_purpose": os.environ.get(
            "KNOWLEDGE_PORTAL_RELEASE_PURPOSE",
            "PRODUCTION",
        )
        .strip()
        .upper(),
    }


def load_agent_api_env() -> dict[str, Any]:
    return {
        "agent_api_url": (
            os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_URL")
            or os.environ.get("AGENT_API_URL")
        ),
        "agent_api_token": (
            os.environ.get("KNOWLEDGE_PORTAL_AGENT_API_TOKEN")
            or os.environ.get("AGENT_SERVICE_TOKEN")
            or os.environ.get("AGENT_RELOAD_TOKEN")
            or os.environ.get("SERVICE_TOKEN")
        ),
        "agent_api_auth_mode": os.environ.get(
            "KNOWLEDGE_PORTAL_AGENT_API_AUTH_MODE",
            "BEARER",
        ).upper(),
    }


def load_storage_paths_env(data_dir: Path, state_path: Path) -> dict[str, Any]:
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
    return {
        "data_dir": data_dir,
        "state_path": state_path,
        "release_artifact_dir": Path(
            os.environ.get(
                "KNOWLEDGE_PORTAL_RELEASE_DIR",
                data_dir / "releases",
            )
        ),
        "drafts_dir": Path(
            os.environ.get(
                "KNOWLEDGE_PORTAL_DRAFTS_DIR",
                data_dir / "portal_drafts",
            )
        )
        .expanduser()
        .resolve(),
        "max_asset_bytes": int(
            os.environ.get("KNOWLEDGE_PORTAL_MAX_ASSET_BYTES", "2000000")
        ),
        "max_assets_per_version": int(
            os.environ.get("KNOWLEDGE_PORTAL_MAX_ASSETS_PER_VERSION", "20")
        ),
        "pdf_jobs_dir": pdf_jobs_dir,
        "original_assets_dir": _optional_path("KNOWLEDGE_PORTAL_ORIGINAL_ASSETS_DIR"),
        "artifact_storage_backend": (
            os.environ.get("KNOWLEDGE_PORTAL_ARTIFACT_STORAGE_BACKEND")
            or os.environ.get("AI_OPS_ARTIFACT_STORAGE_BACKEND")
            or "NONE"
        ).upper(),
        "artifact_gcs_bucket": (
            os.environ.get("KNOWLEDGE_PORTAL_ARTIFACT_GCS_BUCKET")
            or os.environ.get("AI_OPS_ARTIFACT_GCS_BUCKET")
            or None
        ),
        "artifact_storage_path": _optional_path(
            "KNOWLEDGE_PORTAL_ARTIFACT_STORAGE_PATH"
        ),
        "source_store_mode": (
            os.environ.get("KNOWLEDGE_PORTAL_SOURCE_STORE_MODE")
            or os.environ.get("AI_OPS_SOURCE_STORE_MODE")
            or "NONE"
        ).upper(),
        "source_store_path": _optional_path("KNOWLEDGE_PORTAL_SOURCE_STORE_PATH"),
        "release_gcs_bucket": (
            os.environ.get("KNOWLEDGE_PORTAL_RELEASE_GCS_BUCKET") or None
        ),
        "release_gcs_prefix": (
            os.environ.get(
                "KNOWLEDGE_PORTAL_RELEASE_GCS_PREFIX",
                "knowledge-releases",
            ).strip("/")
        ),
    }


def load_pdf_converter_env() -> dict[str, Any]:
    return {
        "pdf_converter_url": (
            os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_URL")
            or os.environ.get("PDF_CONVERTER_URL")
            or None
        ),
        "pdf_converter_token": (
            os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_TOKEN")
            or os.environ.get("PDF_CONVERTER_TOKEN")
            or None
        ),
        "pdf_converter_auth_mode": (
            os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE")
            or os.environ.get("PDF_CONVERTER_AUTH_MODE")
            or "BEARER"
        )
        .strip()
        .upper(),
        "pdf_converter_timeout_seconds": float(
            os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_TIMEOUT_SECONDS", "120")
        ),
        "pdf_converter_engine": (
            os.environ.get("KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE")
            or os.environ.get("PDF_CONVERTER_ENGINE")
            or "legacy_text"
        ).strip()
        or "legacy_text",
        "pdf_sync_max_bytes": int(
            os.environ.get(
                "KNOWLEDGE_PORTAL_PDF_SYNC_MAX_BYTES",
                str(5 * 1024 * 1024),
            )
        ),
        "pdf_sync_max_pages": int(
            os.environ.get("KNOWLEDGE_PORTAL_PDF_SYNC_MAX_PAGES", "20")
        ),
        "pdf_max_upload_bytes": int(
            os.environ.get(
                "KNOWLEDGE_PORTAL_PDF_MAX_UPLOAD_BYTES",
                str(50 * 1024 * 1024),
            )
        ),
        "document_parser": os.environ.get(
            "KNOWLEDGE_PORTAL_DOCUMENT_PARSER",
            "PDF_CONVERTER",
        )
        .strip()
        .upper(),
        "document_ai_processor_name": (
            os.environ.get("KNOWLEDGE_PORTAL_DOCUMENT_AI_PROCESSOR") or None
        ),
        "pdf_prompt_template": os.environ.get(
            "KNOWLEDGE_PORTAL_PDF_PROMPT_TEMPLATE", "slide"
        ),
    }


def load_gemini_ingestion_env() -> dict[str, Any]:
    return {
        "gemini_file_search_sync_enabled": _truthy(
            os.environ.get(
                "KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED",
                "false",
            ),
            extras={"on"},
        ),
        "gemini_file_search_api_key": (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or None
        ),
        "require_file_search_parity": _truthy(
            os.environ.get(
                "KNOWLEDGE_PORTAL_REQUIRE_FILE_SEARCH_PARITY",
                "false",
            ),
            extras={"on"},
        ),
        "ingestion_tasks_queue": (
            os.environ.get("KNOWLEDGE_PORTAL_INGESTION_TASKS_QUEUE") or None
        ),
        "ingestion_worker_url": (
            os.environ.get("KNOWLEDGE_PORTAL_INGESTION_WORKER_URL") or None
        ),
        "ingestion_worker_service_account": (
            os.environ.get("KNOWLEDGE_PORTAL_INGESTION_WORKER_SERVICE_ACCOUNT")
            or None
        ),
    }


def build_portal_settings_kwargs() -> dict[str, Any]:
    """Assemble all PortalSettings constructor kwargs from the environment."""
    data_dir, state_path, _repo_root, default_owner_unit_id = resolve_portal_paths()
    return {
        "repository_mode": resolve_repository_mode(state_path),
        **load_server_auth_env(),
        **load_firestore_collection_env(),
        **load_workflow_feature_env(default_owner_unit_id),
        **load_agent_api_env(),
        **load_storage_paths_env(data_dir, state_path),
        **load_pdf_converter_env(),
        **load_gemini_ingestion_env(),
    }
