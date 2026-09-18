"""Validation helpers for AgentSettings.validate."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse


class _TeamsSettingsView(Protocol):
    viewer_membership_backend: str
    viewer_membership_gcs_bucket: str | None
    mode: str
    user_directory_mode: str
    teams_inbound_auth_mode: str
    client_id: str | None
    tenant_id: str | None
    playground_test_user_email: str | None
    allow_unauthenticated_requests: bool
    user_directory_cache_ttl_seconds: float
    api_auth_mode: str
    api_token: str | None
    api_timeout_seconds: float
    source_api_timeout_seconds: float
    source_api_base_url: str | None
    source_api_token: str | None
    source_delegation_secret: str | None
    asset_url_ttl_seconds: int
    asset_max_dimension: int
    asset_max_bytes: int
    public_base_url: str | None
    asset_signing_key: str | None
    api_url: str | None
    api_audience: str | None


def _raise_settings_error(message: str) -> None:
    from .settings import SettingsError

    raise SettingsError(message)


def validate_identity_and_auth(settings: _TeamsSettingsView) -> None:
    if settings.viewer_membership_backend not in {"memory", "file", "gcs"}:
        _raise_settings_error("VIEWER_MEMBERSHIP_BACKEND must be 'memory', 'file', or 'gcs'.")
    if settings.viewer_membership_backend == "gcs" and not settings.viewer_membership_gcs_bucket:
        _raise_settings_error(
            "VIEWER_MEMBERSHIP_GCS_BUCKET is required when VIEWER_MEMBERSHIP_BACKEND is 'gcs'."
        )
    if settings.mode not in {"echo", "api"}:
        _raise_settings_error("AGENT_MODE must be either 'echo' or 'api'.")
    if settings.user_directory_mode not in {"disabled", "graph"}:
        _raise_settings_error("USER_DIRECTORY_MODE must be either 'disabled' or 'graph'.")
    if settings.teams_inbound_auth_mode not in {"botframework", "entra", "both"}:
        _raise_settings_error("TEAMS_INBOUND_AUTH_MODE must be 'botframework', 'entra', or 'both'.")
    if settings.teams_inbound_auth_mode in {"entra", "both"} and not (
        settings.client_id and settings.tenant_id
    ):
        _raise_settings_error(
            "CLIENT_ID and TENANT_ID are required when "
            "TEAMS_INBOUND_AUTH_MODE is 'entra' or 'both'."
        )
    if settings.playground_test_user_email and not (
        settings.allow_unauthenticated_requests
        or settings.teams_inbound_auth_mode in {"entra", "both"}
    ):
        _raise_settings_error(
            "PLAYGROUND_TEST_USER_EMAIL is allowed only for a local "
            "unauthenticated Playground or TEAMS_INBOUND_AUTH_MODE "
            "'entra'/'both'."
        )
    if settings.user_directory_cache_ttl_seconds <= 0:
        _raise_settings_error("USER_DIRECTORY_CACHE_TTL_SECONDS must be greater than zero.")
    if settings.api_auth_mode not in {"none", "service_token", "google_id_token"}:
        _raise_settings_error(
            "AGENT_API_AUTH_MODE must be none, service_token, or google_id_token."
        )
    if settings.api_auth_mode == "service_token" and not settings.api_token:
        _raise_settings_error("AGENT_API_TOKEN is required when AGENT_API_AUTH_MODE=service_token.")


def validate_source_and_asset_settings(settings: _TeamsSettingsView) -> None:
    if settings.api_timeout_seconds <= 0:
        _raise_settings_error("AGENT_API_TIMEOUT_SECONDS must be greater than zero.")
    if settings.source_api_timeout_seconds <= 0:
        _raise_settings_error("SOURCE_API_TIMEOUT_SECONDS must be greater than zero.")
    source_api_fields = (
        settings.source_api_base_url,
        settings.source_api_token,
        settings.source_delegation_secret,
    )
    if any(source_api_fields) and not all(source_api_fields):
        _raise_settings_error(
            "SOURCE_API_BASE_URL, SOURCE_API_TOKEN, and "
            "SOURCE_DELEGATION_SECRET (or RAG_ASSET_SIGNING_KEY) must be "
            "configured together for original-source delivery."
        )
    if settings.asset_url_ttl_seconds < 60 or settings.asset_url_ttl_seconds > 86400:
        _raise_settings_error("RAG_ASSET_URL_TTL_SECONDS must be between 60 and 86400.")
    if settings.asset_max_dimension < 128 or settings.asset_max_dimension > 1024:
        _raise_settings_error("RAG_ASSET_MAX_DIMENSION must be between 128 and 1024.")
    if settings.asset_max_bytes < 100_000 or settings.asset_max_bytes > 1_000_000:
        _raise_settings_error("RAG_ASSET_MAX_BYTES must be between 100000 and 1000000.")
    if settings.client_id and not settings.tenant_id:
        _raise_settings_error(
            "TENANT_ID is required alongside CLIENT_ID for a single-tenant Teams app registration."
        )


def validate_public_url_and_api_mode(settings: _TeamsSettingsView) -> None:
    if settings.public_base_url:
        parsed_public_url = urlparse(settings.public_base_url)
        is_local_playground_url = (
            parsed_public_url.scheme == "http"
            and parsed_public_url.hostname in {"localhost", "127.0.0.1", "::1"}
            and settings.allow_unauthenticated_requests
        )
        if not parsed_public_url.netloc or (
            parsed_public_url.scheme != "https" and not is_local_playground_url
        ):
            _raise_settings_error(
                "BOT_PUBLIC_BASE_URL must use HTTPS, except for a localhost "
                "Playground URL when DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS "
                "is enabled."
            )
        if not settings.asset_signing_key or len(settings.asset_signing_key) < 16:
            _raise_settings_error(
                "RAG_ASSET_SIGNING_KEY must contain at least 16 characters "
                "when BOT_PUBLIC_BASE_URL is configured."
            )
    if settings.mode != "api":
        return
    if not settings.api_url:
        _raise_settings_error("AGENT_API_URL is required when AGENT_MODE=api.")
    parsed_url = urlparse(settings.api_url)
    is_local_http = parsed_url.scheme == "http" and parsed_url.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if parsed_url.scheme != "https" and not is_local_http:
        _raise_settings_error("AGENT_API_URL must use HTTPS, except for localhost development.")
    if settings.api_auth_mode == "google_id_token":
        audience = settings.api_audience or f"{parsed_url.scheme}://{parsed_url.netloc}"
        if not audience.startswith("https://"):
            _raise_settings_error("AGENT_API_AUDIENCE must be an HTTPS Cloud Run service URL.")
