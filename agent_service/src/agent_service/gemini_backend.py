"""Process-fixed Gemini API backend resolution.

``GEMINI_API_BACKEND`` selects Developer API (API key) or Vertex AI (ADC).
Resolution is cached for the process lifetime and never falls back across
modes because a key, ADC, or a single request error exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from os import environ
from pathlib import Path

__all__ = [
    "DEVELOPER_API_KEY_ENV_NAMES",
    "EVAL_API_KEY_ENV_NAMES",
    "GEMINI_DOTENV_KEY_NAMES",
    "GOOGLE_GENAI_PROVIDER",
    "UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER",
    "GeminiApiBackend",
    "GeminiBackendConfig",
    "GeminiConfigurationError",
    "apply_gemini_sdk_env_flags",
    "assert_vertex_process_has_no_api_keys",
    "developer_api_key_available",
    "file_search_supported",
    "is_google_genai_model",
    "load_dotenv_for_gemini_backend",
    "parse_gemini_api_backend",
    "peek_gemini_api_backend",
    "present_developer_api_key_names",
    "require_developer_api_for_file_search",
    "require_developer_api_key",
    "reset_gemini_backend_for_tests",
    "resolve_gemini_backend",
    "strip_model_provider",
]

GOOGLE_GENAI_PROVIDER = "google_genai"
DEVELOPER_API_KEY_ENV_NAMES: tuple[str, ...] = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
EVAL_API_KEY_ENV_NAMES: tuple[str, ...] = ("GEMINI_EVAL_API_KEY", "GOOGLE_EVAL_API_KEY")
GEMINI_DOTENV_KEY_NAMES: frozenset[str] = frozenset(
    (*DEVELOPER_API_KEY_ENV_NAMES, *EVAL_API_KEY_ENV_NAMES)
)

_VERTEX_PROJECT_ALIASES: tuple[str, ...] = ("GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT")
_SDK_USE_VERTEX_FLAG = "GOOGLE_GENAI_USE_VERTEXAI"
UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER = "global"


class GeminiApiBackend(StrEnum):
    DEVELOPER_API = "DEVELOPER_API"
    VERTEX_AI = "VERTEX_AI"


class GeminiConfigurationError(RuntimeError):
    """Invalid Gemini backend configuration. Fail closed; do not fallback."""


@dataclass(frozen=True)
class GeminiBackendConfig:
    backend: GeminiApiBackend
    vertex_project: str | None = None
    chat_location: str | None = None
    embedding_location: str | None = None
    pdf_location: str | None = None
    eval_project: str | None = None
    eval_chat_location: str | None = None
    eval_embedding_location: str | None = None

    @property
    def is_vertex(self) -> bool:
        return self.backend is GeminiApiBackend.VERTEX_AI

    @property
    def is_developer_api(self) -> bool:
        return self.backend is GeminiApiBackend.DEVELOPER_API

    def location_for_chat(self, *, eval_mode: bool = False) -> str | None:
        if eval_mode and self.eval_chat_location:
            return self.eval_chat_location
        return self.chat_location

    def location_for_embedding(self, *, eval_mode: bool = False) -> str | None:
        if eval_mode and self.eval_embedding_location:
            return self.eval_embedding_location
        return self.embedding_location

    def project_for_requests(self, *, eval_mode: bool = False) -> str | None:
        if eval_mode and self.eval_project:
            return self.eval_project
        return self.vertex_project


_RESOLVED: GeminiBackendConfig | None = None


def parse_gemini_api_backend(raw: str | None) -> GeminiApiBackend:
    value = (raw or "").strip()
    if not value:
        return GeminiApiBackend.DEVELOPER_API
    try:
        return GeminiApiBackend(value)
    except ValueError as error:
        supported = ", ".join(item.value for item in GeminiApiBackend)
        raise GeminiConfigurationError(
            f"GEMINI_API_BACKEND must be {supported}; got {value!r}."
        ) from error


def peek_gemini_api_backend(
    *,
    dotenv_path: Path | str | None = None,
    environ_map: Mapping[str, str] | None = None,
) -> GeminiApiBackend:
    """Read the backend from process env, then dotenv, without loading keys."""
    env = environ if environ_map is None else environ_map
    raw = (env.get("GEMINI_API_BACKEND") or "").strip()
    if raw:
        return parse_gemini_api_backend(raw)
    values = _read_dotenv_values(dotenv_path)
    return parse_gemini_api_backend(values.get("GEMINI_API_BACKEND"))


def load_dotenv_for_gemini_backend(
    *,
    dotenv_path: Path | str | None = None,
    override: bool = False,
) -> GeminiApiBackend:
    """Load dotenv fields required by the selected backend.

    Vertex mode never copies Gemini/Google API keys from ``.env`` into the
    process environment. Existing non-empty process keys are left untouched
    so the client constructor can fail closed.
    """
    backend = peek_gemini_api_backend(dotenv_path=dotenv_path)
    exclude = GEMINI_DOTENV_KEY_NAMES if backend is GeminiApiBackend.VERTEX_AI else frozenset()
    _apply_dotenv_values(dotenv_path, exclude=exclude, override=override)
    return backend


def resolve_gemini_backend(
    *,
    require_pdf_location: bool = False,
    eval_mode: bool = False,
    environ_map: Mapping[str, str] | None = None,
) -> GeminiBackendConfig:
    """Return the process-fixed backend configuration.

    Subsequent calls ignore environment changes. Tests must call
    ``reset_gemini_backend_for_tests``.
    """
    global _RESOLVED
    if _RESOLVED is not None:
        if require_pdf_location:
            _require_pdf_location(_RESOLVED)
        return _RESOLVED

    env = environ if environ_map is None else environ_map
    config = _resolve_once(
        env,
        require_pdf_location=require_pdf_location,
        eval_mode=eval_mode,
    )
    apply_gemini_sdk_env_flags(config, environ_map=environ if environ_map is None else None)
    _RESOLVED = config
    return config


def reset_gemini_backend_for_tests() -> None:
    """Clear the process-fixed backend cache. Tests only."""
    global _RESOLVED
    _RESOLVED = None


def apply_gemini_sdk_env_flags(
    config: GeminiBackendConfig,
    *,
    environ_map: dict[str, str] | None = None,
) -> None:
    """Set SDK helper flags. Callers still pass explicit client kwargs."""
    env = environ if environ_map is None else environ_map
    if config.is_vertex:
        env[_SDK_USE_VERTEX_FLAG] = "true"
        project = config.project_for_requests()
        if project:
            env["GOOGLE_CLOUD_PROJECT"] = project
        location = config.location_for_chat()
        if location:
            env["GOOGLE_CLOUD_LOCATION"] = location
        return
    env[_SDK_USE_VERTEX_FLAG] = "false"


def assert_vertex_process_has_no_api_keys(
    *,
    environ_map: Mapping[str, str] | None = None,
) -> None:
    """Fail closed when Vertex mode sees injected Gemini/Google API keys."""
    present = present_developer_api_key_names(environ_map=environ_map)
    if present:
        raise GeminiConfigurationError(
            "VERTEX_AI refuses Gemini/Google API keys in the process environment "
            f"({', '.join(present)}). Unset them before constructing Gemini clients."
        )


def present_developer_api_key_names(
    *,
    environ_map: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    env = environ if environ_map is None else environ_map
    return tuple(name for name in DEVELOPER_API_KEY_ENV_NAMES if (env.get(name) or "").strip())


def developer_api_key_available(
    *,
    environ_map: Mapping[str, str] | None = None,
) -> bool:
    return bool(present_developer_api_key_names(environ_map=environ_map))


def require_developer_api_key(
    *,
    environ_map: Mapping[str, str] | None = None,
) -> str:
    env = environ if environ_map is None else environ_map
    for name in DEVELOPER_API_KEY_ENV_NAMES:
        value = (env.get(name) or "").strip()
        if value:
            return value
    raise GeminiConfigurationError(
        "DEVELOPER_API requires GEMINI_API_KEY or GOOGLE_API_KEY. "
        "VERTEX_AI is not used as a fallback."
    )


def file_search_supported(config: GeminiBackendConfig | None = None) -> bool:
    if config is not None:
        return config.is_developer_api
    return peek_gemini_api_backend() is GeminiApiBackend.DEVELOPER_API


def require_developer_api_for_file_search(
    *,
    feature: str = "Gemini File Search",
) -> None:
    if file_search_supported():
        return
    raise GeminiConfigurationError(
        f"{feature} is not supported on VERTEX_AI. File Search remains a "
        "Developer API capability; disable sync and parity together on Vertex."
    )


def is_google_genai_model(model_name: str | None) -> bool:
    if not model_name:
        return False
    provider, _, remainder = model_name.partition(":")
    if remainder:
        return provider.strip() == GOOGLE_GENAI_PROVIDER
    return model_name.strip().startswith("gemini")


def strip_model_provider(model_name: str) -> str:
    normalized = model_name.strip()
    if ":" in normalized:
        return normalized.split(":", 1)[1].strip()
    return normalized


def _resolve_once(
    env: Mapping[str, str],
    *,
    require_pdf_location: bool,
    eval_mode: bool,
) -> GeminiBackendConfig:
    backend = parse_gemini_api_backend(env.get("GEMINI_API_BACKEND"))
    if backend is GeminiApiBackend.DEVELOPER_API:
        return GeminiBackendConfig(backend=backend)

    project = _resolve_vertex_project(env)
    chat_location = _required_vertex_field(env, "VERTEX_AI_CHAT_LOCATION")
    embedding_location = _required_vertex_field(env, "VERTEX_AI_EMBEDDING_LOCATION")
    pdf_location = _optional_approved_vertex_location(env, "VERTEX_AI_PDF_LOCATION")
    config = GeminiBackendConfig(
        backend=backend,
        vertex_project=project,
        chat_location=chat_location,
        embedding_location=embedding_location,
        pdf_location=pdf_location,
        eval_project=(env.get("VERTEX_AI_EVAL_PROJECT") or "").strip() or None,
        eval_chat_location=_optional_approved_vertex_location(
            env, "VERTEX_AI_EVAL_CHAT_LOCATION"
        ),
        eval_embedding_location=_optional_approved_vertex_location(
            env, "VERTEX_AI_EVAL_EMBEDDING_LOCATION"
        ),
    )
    if require_pdf_location or eval_mode and require_pdf_location:
        _require_pdf_location(config)
    return config


def _require_pdf_location(config: GeminiBackendConfig) -> None:
    if config.is_vertex and not config.pdf_location:
        raise GeminiConfigurationError(
            "VERTEX_AI PDF Vision requires VERTEX_AI_PDF_LOCATION."
        )


def _resolve_vertex_project(env: Mapping[str, str]) -> str:
    """Return one explicit Vertex project.

    ``VERTEX_AI_PROJECT`` wins when set. Otherwise ``GCP_PROJECT_ID`` and
    ``GOOGLE_CLOUD_PROJECT`` may map only when they contribute a single
    shared value. Locations are never inferred here.
    """
    explicit = (env.get("VERTEX_AI_PROJECT") or "").strip()
    if explicit:
        return explicit
    unique_values = {
        value
        for name in _VERTEX_PROJECT_ALIASES
        if (value := (env.get(name) or "").strip())
    }
    if len(unique_values) == 1:
        return next(iter(unique_values))
    if not unique_values:
        raise GeminiConfigurationError(
            "VERTEX_AI requires VERTEX_AI_PROJECT, or a single explicit "
            "GCP_PROJECT_ID / GOOGLE_CLOUD_PROJECT value."
        )
    raise GeminiConfigurationError(
        "VERTEX_AI requires a single explicit project. "
        "GCP_PROJECT_ID and GOOGLE_CLOUD_PROJECT disagree; set VERTEX_AI_PROJECT."
    )


def _required_vertex_field(env: Mapping[str, str], name: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise GeminiConfigurationError(f"VERTEX_AI requires {name}.")
    return _approved_vertex_location(name, value)


def _optional_approved_vertex_location(
    env: Mapping[str, str], name: str
) -> str | None:
    value = (env.get(name) or "").strip()
    if not value:
        return None
    return _approved_vertex_location(name, value)


def _approved_vertex_location(name: str, value: str) -> str:
    if value.casefold() == UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER:
        raise GeminiConfigurationError(
            f"{name}={value!r} is the unapproved P0 placeholder. "
            "Set a BU-approved Vertex location; do not use 'global' until P0 "
            "records approval."
        )
    return value


def _read_dotenv_values(dotenv_path: Path | str | None) -> dict[str, str | None]:
    from dotenv import dotenv_values, find_dotenv

    if dotenv_path is not None:
        return dict(dotenv_values(dotenv_path))
    found = find_dotenv(usecwd=True)
    if not found:
        return {}
    return dict(dotenv_values(found))


def _apply_dotenv_values(
    dotenv_path: Path | str | None,
    *,
    exclude: frozenset[str],
    override: bool,
) -> None:
    values = _read_dotenv_values(dotenv_path)
    for key, value in values.items():
        if not key or key in exclude or value is None:
            continue
        if not override and key in environ:
            continue
        environ[key] = value.replace("\r", "") if "\r" in value else value
