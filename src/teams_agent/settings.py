from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class SettingsError(ValueError):
    """Raised when application configuration is invalid."""


@dataclass(frozen=True)
class AgentSettings:
    mode: str = "echo"
    api_url: str | None = None
    api_token: str | None = None
    api_auth_mode: str = "none"
    api_audience: str | None = None
    api_timeout_seconds: float = 10.0
    asset_dir: Path | None = None
    source_dir: Path | None = None
    public_base_url: str | None = None
    asset_signing_key: str | None = None
    asset_url_ttl_seconds: int = 3600
    asset_max_dimension: int = 1024
    asset_max_bytes: int = 1_000_000
    asset_gcs_bucket: str | None = None
    asset_gcs_prefix: str = "knowledge-releases"
    asset_gcs_tenant_id: str = "default"
    user_directory_mode: str = "disabled"
    user_directory_cache_ttl_seconds: float = 300.0
    # Stream workflow progress into Teams while the Agent Service runs.
    # Only takes effect in 1:1 personal chats -- Teams rejects streamed
    # messages in channels and group chats (see teams_agent.agent).
    streaming_enabled: bool = True
    # Microsoft Teams SDK app (Entra app registration) credentials. The SDK
    # reads CLIENT_ID / CLIENT_SECRET / TENANT_ID from the environment itself;
    # they are mirrored here so `/readyz` can report whether the adapter is
    # able to authenticate, and so the User Directory Service can run the
    # app-only Graph client-credentials flow without reaching into SDK
    # internals. Values are never logged or echoed back to users (spec §17).
    client_id: str | None = None
    client_secret: str | None = None
    tenant_id: str | None = None
    # Cloud-hosted Microsoft 365 Agents Playground sends an Entra client-
    # credentials token directly to the bot endpoint. Real Teams/Bot Framework
    # traffic uses the Bot Framework issuer instead. Deployed adapters that
    # must serve both set TEAMS_INBOUND_AUTH_MODE=both.
    teams_inbound_auth_mode: str = "botframework"
    allow_unauthenticated_requests: bool = False
    playground_test_user_email: str | None = None
    viewer_membership_store_path: Path | None = None
    viewer_membership_backend: str = "memory"
    viewer_membership_gcs_bucket: str | None = None
    source_api_base_url: str | None = None
    source_api_token: str | None = None
    source_delegation_secret: str | None = None
    source_api_timeout_seconds: float = 20.0
    # Adaptive Card "開啟原始檔案 / 查看引用段落" buttons. Playground does not
    # make markdown source links clickable, so these stay on by default.
    citation_open_actions_enabled: bool = True

    @classmethod
    def from_env(cls) -> "AgentSettings":
        from .settings_env import load_agent_settings_kwargs

        settings = cls(**load_agent_settings_kwargs())
        settings.validate()
        return settings

    def validate(self) -> None:
        from .settings_validate import (
            validate_identity_and_auth,
            validate_public_url_and_api_mode,
            validate_source_and_asset_settings,
        )

        validate_identity_and_auth(self)
        validate_source_and_asset_settings(self)
        validate_public_url_and_api_mode(self)

    @property
    def resolved_api_audience(self) -> str | None:
        if self.api_audience:
            return self.api_audience
        if not self.api_url:
            return None
        parsed_url = urlparse(self.api_url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}"

    @property
    def resolved_stream_url(self) -> str | None:
        """`/agent/chat/stream` alongside the configured `/agent/chat`.

        Derived from `api_url` by suffix rather than configured separately,
        so the two endpoints can never drift onto different hosts.
        """
        if not self.api_url:
            return None
        return f"{self.api_url.rstrip('/')}/stream"

    @property
    def streaming_ready(self) -> bool:
        return self.streaming_enabled and self.mode == "api" and bool(self.api_url)

    @property
    def resolved_feedback_url(self) -> str | None:
        """POST /feedback on the same Agent Service host as `api_url` (spec §14)."""
        if not self.api_url:
            return None
        parsed_url = urlparse(self.api_url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}/feedback"

    @property
    def resolved_health_telemetry_url(self) -> str | None:
        """POST Adapter reply health samples to Agent Service (REQ-024)."""
        if not self.api_url:
            return None
        parsed_url = urlparse(self.api_url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}/agent/ops/health-telemetry"

    @property
    def ready(self) -> bool:
        return self.mode == "echo" or bool(self.api_url)

    @property
    def uses_playground_identity_fallback(self) -> bool:
        """Whether missing activity emails may be filled from PLAYGROUND_TEST_USER_EMAIL.

        Hosted Playground traffic is accepted in `entra` and `both` modes.
        Local Teams SDK devtools use the unauthenticated escape hatch.
        """
        return self.allow_unauthenticated_requests or (
            self.teams_inbound_auth_mode in {"entra", "both"}
        )

    @property
    def teams_auth_ready(self) -> bool:
        """Whether the Teams SDK can validate inbound Bot Framework JWTs.

        `DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS` short-circuits JWT
        validation and is only ever acceptable for local development against
        the Teams SDK devtools, never in Cloud Run.
        """
        return bool(self.client_id and self.client_secret) or (
            self.allow_unauthenticated_requests
        )

    @property
    def graph_credentials_ready(self) -> bool:
        """Whether an app-only Microsoft Graph token can be acquired."""
        return bool(self.client_id and self.client_secret and self.tenant_id)

    @property
    def images_ready(self) -> bool:
        has_local_assets = bool(self.asset_dir and self.asset_dir.is_dir())
        return bool(
            (has_local_assets or self.asset_gcs_bucket)
            and self.public_base_url
            and self.asset_signing_key
        )

    @property
    def sources_ready(self) -> bool:
        if not (
            self.source_dir
            and self.source_dir.is_dir()
            and self.public_base_url
            and self.asset_signing_key
        ):
            return False
        sources = self.source_dir / "sources"
        releases = self.source_dir / "releases"
        has_markdown = sources.is_dir() and any(sources.glob("*.md"))
        has_release = releases.is_dir() and any(releases.glob("*/sources/*.md"))
        return has_markdown or has_release

    @property
    def source_api_ready(self) -> bool:
        """Whether Adapter can mint and proxy original-source delivery."""

        return bool(
            self.public_base_url
            and self.asset_signing_key
            and self.source_api_base_url
            and self.source_api_token
            and self.source_delegation_secret
        )
