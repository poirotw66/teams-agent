"""Environment loading helpers for AgentSettings.from_env."""

from __future__ import annotations

from os import environ
from pathlib import Path

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _load_core_agent_env() -> dict:
    from .settings import SettingsError

    api_token = environ.get("AGENT_API_TOKEN", "").strip() or None
    project_dir = Path(__file__).resolve().parents[2]
    asset_dir = Path(environ.get("RAG_ASSET_DIR", project_dir / "data" / "sources" / "assets"))
    source_dir = Path(environ.get("RAG_SOURCE_DIR", project_dir / "data"))
    try:
        timeout = float(environ.get("AGENT_API_TIMEOUT_SECONDS", "10"))
    except ValueError as error:
        raise SettingsError("AGENT_API_TIMEOUT_SECONDS must be a number.") from error
    return {
        "mode": environ.get("AGENT_MODE", "echo").strip().lower(),
        "api_url": environ.get("AGENT_API_URL", "").strip() or None,
        "api_token": api_token,
        "api_auth_mode": environ.get(
            "AGENT_API_AUTH_MODE",
            "service_token" if api_token else "none",
        )
        .strip()
        .lower(),
        "api_audience": environ.get("AGENT_API_AUDIENCE", "").strip() or None,
        "api_timeout_seconds": timeout,
        "asset_dir": asset_dir.expanduser().resolve(),
        "source_dir": source_dir.expanduser().resolve(),
        "public_base_url": (
            environ.get("BOT_PUBLIC_BASE_URL", "").strip().rstrip("/") or None
        ),
        "asset_signing_key": environ.get("RAG_ASSET_SIGNING_KEY", "").strip() or None,
        "asset_url_ttl_seconds": int(environ.get("RAG_ASSET_URL_TTL_SECONDS", "3600")),
        "asset_max_dimension": int(environ.get("RAG_ASSET_MAX_DIMENSION", "1024")),
        "asset_max_bytes": int(environ.get("RAG_ASSET_MAX_BYTES", "1000000")),
        "asset_gcs_bucket": environ.get("RAG_ASSET_GCS_BUCKET", "").strip() or None,
        "asset_gcs_prefix": (
            environ.get("RAG_ASSET_GCS_PREFIX", "knowledge-releases").strip().strip("/")
        ),
        "asset_gcs_tenant_id": (
            environ.get("RAG_ASSET_GCS_TENANT_ID", "default").strip() or "default"
        ),
    }


def _load_identity_and_source_env(*, asset_signing_key: str | None) -> dict:
    from .settings import SettingsError

    try:
        source_api_timeout = float(environ.get("SOURCE_API_TIMEOUT_SECONDS", "20"))
    except ValueError as error:
        raise SettingsError("SOURCE_API_TIMEOUT_SECONDS must be a number.") from error
    return {
        "user_directory_mode": environ.get("USER_DIRECTORY_MODE", "disabled")
        .strip()
        .lower(),
        "user_directory_cache_ttl_seconds": float(
            environ.get("USER_DIRECTORY_CACHE_TTL_SECONDS", "300")
        ),
        "streaming_enabled": (
            environ.get("AGENT_STREAMING_ENABLED", "true").strip().lower() in _TRUE_VALUES
        ),
        "client_id": environ.get("CLIENT_ID", "").strip() or None,
        "client_secret": environ.get("CLIENT_SECRET", "").strip() or None,
        "tenant_id": environ.get("TENANT_ID", "").strip() or None,
        "teams_inbound_auth_mode": (
            environ.get("TEAMS_INBOUND_AUTH_MODE", "botframework").strip().lower()
        ),
        "allow_unauthenticated_requests": (
            environ.get("DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS", "")
            .strip()
            .lower()
            in _TRUE_VALUES
        ),
        "playground_test_user_email": (
            environ.get("PLAYGROUND_TEST_USER_EMAIL", "").strip() or None
        ),
        "viewer_membership_store_path": (
            Path(environ["VIEWER_MEMBERSHIP_STORE_PATH"]).resolve()
            if environ.get("VIEWER_MEMBERSHIP_STORE_PATH", "").strip()
            else None
        ),
        "viewer_membership_backend": (
            environ.get("VIEWER_MEMBERSHIP_BACKEND", "memory").strip().lower()
        ),
        "viewer_membership_gcs_bucket": (
            environ.get("VIEWER_MEMBERSHIP_GCS_BUCKET", "").strip()
            or environ.get("ARTIFACT_GCS_BUCKET", "").strip()
            or environ.get("GCS_BUCKET", "").strip()
            or None
        ),
        "source_api_base_url": (
            environ.get("SOURCE_API_BASE_URL", "").strip().rstrip("/") or None
        ),
        "source_api_token": (
            environ.get("SOURCE_API_TOKEN", "").strip()
            or environ.get("AI_OPS_BACKOFFICE_TOKEN", "").strip()
            or None
        ),
        "source_delegation_secret": (
            environ.get("SOURCE_DELEGATION_SECRET", "").strip()
            or environ.get("AI_OPS_SOURCE_DELEGATION_SECRET", "").strip()
            or (
                asset_signing_key
                if (environ.get("SOURCE_API_BASE_URL", "").strip())
                else None
            )
        ),
        "source_api_timeout_seconds": source_api_timeout,
        "citation_open_actions_enabled": (
            environ.get("TEAMS_CITATION_OPEN_ACTIONS", "true").strip().lower()
            in _TRUE_VALUES
        ),
    }


def load_agent_settings_kwargs() -> dict:
    """Read adapter settings from the environment as constructor kwargs."""
    core = _load_core_agent_env()
    return {
        **core,
        **_load_identity_and_source_env(asset_signing_key=core["asset_signing_key"]),
    }
