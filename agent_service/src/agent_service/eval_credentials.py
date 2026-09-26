"""Credential selection for offline / live evaluation entrypoints.

Developer API keeps ``GEMINI_EVAL_API_KEY`` isolation from Playground keys.
Vertex eval uses the eval project/location and ADC and never falls back to
a Gemini/Google API key.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .gemini_backend import (
    DEVELOPER_API_KEY_ENV_NAMES,
    EVAL_API_KEY_ENV_NAMES,
    GeminiApiBackend,
    GeminiConfigurationError,
    assert_vertex_process_has_no_api_keys,
    load_dotenv_for_gemini_backend,
    resolve_gemini_backend,
)

logger = logging.getLogger(__name__)


def _first_nonempty(*names: str) -> tuple[str, str] | None:
    from os import environ

    for name in names:
        value = (environ.get(name) or "").strip()
        if value:
            return name, value
    return None


def apply_eval_gemini_credentials(*, dotenv_path: Path | None = None) -> str:
    """Load dotenv and apply the selected backend's eval credentials.

    Returns the credential source name for logs. Does not log secret values.
    """
    return apply_eval_gemini_preflight(dotenv_path=dotenv_path)


def apply_eval_gemini_preflight(*, dotenv_path: Path | None = None) -> str:
    """Shared eval preflight used by live eval scripts."""
    from os import environ

    if dotenv_path is not None:
        load_dotenv_for_gemini_backend(dotenv_path=dotenv_path, override=False)
    config = resolve_gemini_backend(eval_mode=True)
    if config.backend is GeminiApiBackend.DEVELOPER_API:
        return _apply_developer_api_eval_key()

    assert_vertex_process_has_no_api_keys()
    project = config.project_for_requests(eval_mode=True)
    chat_location = config.location_for_chat(eval_mode=True)
    embedding_location = config.location_for_embedding(eval_mode=True)
    if not project or not chat_location or not embedding_location:
        raise GeminiConfigurationError(
            "VERTEX_AI eval requires VERTEX_AI_PROJECT (or VERTEX_AI_EVAL_PROJECT) "
            "and chat/embedding locations. Developer API keys are not a fallback."
        )
    environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    environ["GOOGLE_CLOUD_PROJECT"] = project
    environ["GOOGLE_CLOUD_LOCATION"] = chat_location
    logger.info(
        "eval_credentials_applied source=VERTEX_AI_ADC project_set=%s "
        "chat_location_set=%s embedding_location_set=%s",
        bool(project),
        bool(chat_location),
        bool(embedding_location),
    )
    return "VERTEX_AI_ADC"


def _apply_developer_api_eval_key() -> str:
    from os import environ

    selected = _first_nonempty(*EVAL_API_KEY_ENV_NAMES)
    if selected is not None:
        source_name, api_key = selected
        for runtime_name in DEVELOPER_API_KEY_ENV_NAMES:
            environ[runtime_name] = api_key
        logger.info(
            "eval_credentials_applied source=%s runtime=GEMINI_API_KEY+GOOGLE_API_KEY",
            source_name,
        )
        return source_name

    fallback = _first_nonempty(*DEVELOPER_API_KEY_ENV_NAMES)
    if fallback is not None:
        source_name, _api_key = fallback
        logger.warning(
            "eval_credentials_fallback source=%s "
            "(set GEMINI_EVAL_API_KEY to isolate eval quota from Playground)",
            source_name,
        )
        return source_name

    raise GeminiConfigurationError(
        "No Gemini API key for eval. Set GEMINI_EVAL_API_KEY (preferred) "
        "or GEMINI_API_KEY / GOOGLE_API_KEY in agent_service/.env. "
        "VERTEX_AI is not used as a fallback."
    )


def eval_gemini_report_fields() -> dict[str, str | None]:
    """Backend/project/location labels for eval reports. Never includes secrets."""
    config = resolve_gemini_backend(eval_mode=True)
    return {
        "geminiBackend": config.backend.value,
        "vertexProject": config.project_for_requests(eval_mode=True),
        "vertexChatLocation": config.location_for_chat(eval_mode=True),
        "vertexEmbeddingLocation": config.location_for_embedding(eval_mode=True),
    }


__all__ = [
    "apply_eval_gemini_credentials",
    "apply_eval_gemini_preflight",
    "eval_gemini_report_fields",
]
