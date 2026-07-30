from dataclasses import dataclass
from os import environ
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
    public_base_url: str | None = None
    asset_signing_key: str | None = None
    asset_url_ttl_seconds: int = 3600
    asset_max_dimension: int = 1024
    asset_max_bytes: int = 1_000_000

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
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in {"echo", "api"}:
            raise SettingsError("AGENT_MODE must be either 'echo' or 'api'.")
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
        if self.public_base_url:
            parsed_public_url = urlparse(self.public_base_url)
            if parsed_public_url.scheme != "https" or not parsed_public_url.netloc:
                raise SettingsError("BOT_PUBLIC_BASE_URL must be an absolute HTTPS URL.")
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
    def ready(self) -> bool:
        return self.mode == "echo" or bool(self.api_url)

    @property
    def images_ready(self) -> bool:
        return bool(
            self.asset_dir
            and self.asset_dir.is_dir()
            and self.public_base_url
            and self.asset_signing_key
        )
