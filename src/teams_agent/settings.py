from dataclasses import dataclass
from os import environ
from pathlib import Path
from urllib.parse import urlparse

_TRUE_VALUES = {"1", "true", "yes", "on"}


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
    public_base_url: str | None = None
    asset_signing_key: str | None = None
    asset_url_ttl_seconds: int = 3600
    asset_max_dimension: int = 1024
    asset_max_bytes: int = 1_000_000
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
    # traffic uses the Bot Framework issuer instead.
    teams_inbound_auth_mode: str = "botframework"
    allow_unauthenticated_requests: bool = False

    @classmethod
    def from_env(cls) -> "AgentSettings":
        mode = environ.get("AGENT_MODE", "echo").strip().lower()
        api_url = environ.get("AGENT_API_URL", "").strip() or None
        api_token = environ.get("AGENT_API_TOKEN", "").strip() or None
        api_auth_mode = environ.get(
            "AGENT_API_AUTH_MODE",
            "service_token" if api_token else "none",
        ).strip().lower()
        project_dir = Path(__file__).resolve().parents[2]
        asset_dir = Path(
            environ.get("RAG_ASSET_DIR", project_dir / "data" / "assets")
        )

        try:
            timeout = float(environ.get("AGENT_API_TIMEOUT_SECONDS", "10"))
        except ValueError as error:
            raise SettingsError("AGENT_API_TIMEOUT_SECONDS must be a number.") from error

        settings = cls(
            mode=mode,
            api_url=api_url,
            api_token=api_token,
            api_auth_mode=api_auth_mode,
            api_audience=environ.get("AGENT_API_AUDIENCE", "").strip() or None,
            api_timeout_seconds=timeout,
            asset_dir=asset_dir.expanduser().resolve(),
            public_base_url=(
                environ.get("BOT_PUBLIC_BASE_URL", "").strip().rstrip("/")
                or None
            ),
            asset_signing_key=(
                environ.get("RAG_ASSET_SIGNING_KEY", "").strip() or None
            ),
            asset_url_ttl_seconds=int(
                environ.get("RAG_ASSET_URL_TTL_SECONDS", "3600")
            ),
            asset_max_dimension=int(
                environ.get("RAG_ASSET_MAX_DIMENSION", "1024")
            ),
            asset_max_bytes=int(
                environ.get("RAG_ASSET_MAX_BYTES", "1000000")
            ),
            user_directory_mode=(
                environ.get("USER_DIRECTORY_MODE", "disabled").strip().lower()
            ),
            user_directory_cache_ttl_seconds=float(
                environ.get("USER_DIRECTORY_CACHE_TTL_SECONDS", "300")
            ),
            streaming_enabled=(
                environ.get("AGENT_STREAMING_ENABLED", "true").strip().lower()
                in _TRUE_VALUES
            ),
            client_id=environ.get("CLIENT_ID", "").strip() or None,
            client_secret=environ.get("CLIENT_SECRET", "").strip() or None,
            tenant_id=environ.get("TENANT_ID", "").strip() or None,
            teams_inbound_auth_mode=(
                environ.get("TEAMS_INBOUND_AUTH_MODE", "botframework")
                .strip()
                .lower()
            ),
            allow_unauthenticated_requests=(
                environ.get("DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS", "")
                .strip()
                .lower()
                in _TRUE_VALUES
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in {"echo", "api"}:
            raise SettingsError("AGENT_MODE must be either 'echo' or 'api'.")
        if self.user_directory_mode not in {"disabled", "graph"}:
            raise SettingsError(
                "USER_DIRECTORY_MODE must be either 'disabled' or 'graph'."
            )
        if self.teams_inbound_auth_mode not in {"botframework", "entra"}:
            raise SettingsError(
                "TEAMS_INBOUND_AUTH_MODE must be either 'botframework' or 'entra'."
            )
        if self.teams_inbound_auth_mode == "entra" and not (
            self.client_id and self.tenant_id
        ):
            raise SettingsError(
                "CLIENT_ID and TENANT_ID are required when "
                "TEAMS_INBOUND_AUTH_MODE=entra."
            )
        if self.user_directory_cache_ttl_seconds <= 0:
            raise SettingsError(
                "USER_DIRECTORY_CACHE_TTL_SECONDS must be greater than zero."
            )
        if self.api_auth_mode not in {"none", "service_token", "google_id_token"}:
            raise SettingsError(
                "AGENT_API_AUTH_MODE must be none, service_token, or google_id_token."
            )
        if self.api_auth_mode == "service_token" and not self.api_token:
            raise SettingsError(
                "AGENT_API_TOKEN is required when AGENT_API_AUTH_MODE=service_token."
            )
        if self.api_timeout_seconds <= 0:
            raise SettingsError("AGENT_API_TIMEOUT_SECONDS must be greater than zero.")
        if self.asset_url_ttl_seconds < 60 or self.asset_url_ttl_seconds > 86400:
            raise SettingsError(
                "RAG_ASSET_URL_TTL_SECONDS must be between 60 and 86400."
            )
        if self.asset_max_dimension < 128 or self.asset_max_dimension > 1024:
            raise SettingsError(
                "RAG_ASSET_MAX_DIMENSION must be between 128 and 1024."
            )
        if self.asset_max_bytes < 100_000 or self.asset_max_bytes > 1_000_000:
            raise SettingsError(
                "RAG_ASSET_MAX_BYTES must be between 100000 and 1000000."
            )
        if self.client_id and not self.tenant_id:
            raise SettingsError(
                "TENANT_ID is required alongside CLIENT_ID for a single-tenant "
                "Teams app registration."
            )
        if self.public_base_url:
            parsed_public_url = urlparse(self.public_base_url)
            is_local_playground_url = (
                parsed_public_url.scheme == "http"
                and parsed_public_url.hostname in {"localhost", "127.0.0.1", "::1"}
                and self.allow_unauthenticated_requests
            )
            if (
                not parsed_public_url.netloc
                or (
                    parsed_public_url.scheme != "https"
                    and not is_local_playground_url
                )
            ):
                raise SettingsError(
                    "BOT_PUBLIC_BASE_URL must use HTTPS, except for a localhost "
                    "Playground URL when DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS "
                    "is enabled."
                )
            if not self.asset_signing_key or len(self.asset_signing_key) < 16:
                raise SettingsError(
                    "RAG_ASSET_SIGNING_KEY must contain at least 16 characters "
                    "when BOT_PUBLIC_BASE_URL is configured."
                )
        if self.mode != "api":
            return
        if not self.api_url:
            raise SettingsError("AGENT_API_URL is required when AGENT_MODE=api.")

        parsed_url = urlparse(self.api_url)
        is_local_http = parsed_url.scheme == "http" and parsed_url.hostname in {
            "localhost",
            "127.0.0.1",
        }
        if parsed_url.scheme != "https" and not is_local_http:
            raise SettingsError(
                "AGENT_API_URL must use HTTPS, except for localhost development."
            )
        if self.api_auth_mode == "google_id_token":
            audience = self.api_audience or f"{parsed_url.scheme}://{parsed_url.netloc}"
            if not audience.startswith("https://"):
                raise SettingsError(
                    "AGENT_API_AUDIENCE must be an HTTPS Cloud Run service URL."
                )

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
    def ready(self) -> bool:
        return self.mode == "echo" or bool(self.api_url)

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
        return bool(
            self.asset_dir
            and self.asset_dir.is_dir()
            and self.public_base_url
            and self.asset_signing_key
        )
