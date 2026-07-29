from dataclasses import dataclass
from os import environ
from urllib.parse import urlparse


class SettingsError(ValueError):
    """Raised when application configuration is invalid."""


@dataclass(frozen=True)
class AgentSettings:
    mode: str = "echo"
    api_url: str | None = None
    api_token: str | None = None
    api_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "AgentSettings":
        mode = environ.get("AGENT_MODE", "echo").strip().lower()
        api_url = environ.get("AGENT_API_URL", "").strip() or None
        api_token = environ.get("AGENT_API_TOKEN", "").strip() or None

        try:
            timeout = float(environ.get("AGENT_API_TIMEOUT_SECONDS", "10"))
        except ValueError as error:
            raise SettingsError("AGENT_API_TIMEOUT_SECONDS must be a number.") from error

        settings = cls(
            mode=mode,
            api_url=api_url,
            api_token=api_token,
            api_timeout_seconds=timeout,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode not in {"echo", "api"}:
            raise SettingsError("AGENT_MODE must be either 'echo' or 'api'.")
        if self.api_timeout_seconds <= 0:
            raise SettingsError("AGENT_API_TIMEOUT_SECONDS must be greater than zero.")
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

    @property
    def ready(self) -> bool:
        return self.mode == "echo" or bool(self.api_url)

