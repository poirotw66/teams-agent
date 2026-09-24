"""Dual-mode Gemini client factory for the PDF Vision converter.

This module is copied into the upstream checkout. It must not import
``agent_service``; the converter process only has upstream dependencies.
"""

from __future__ import annotations

import os
from typing import Any

DEVELOPER_API = "DEVELOPER_API"
VERTEX_AI = "VERTEX_AI"
UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER = "global"
_KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


class GeminiBackendError(RuntimeError):
    """Fail-closed Gemini backend configuration error."""


def resolve_backend() -> str:
    value = (os.environ.get("GEMINI_API_BACKEND") or "").strip() or DEVELOPER_API
    if value not in {DEVELOPER_API, VERTEX_AI}:
        raise GeminiBackendError(
            f"GEMINI_API_BACKEND must be {DEVELOPER_API} or {VERTEX_AI}; got {value!r}."
        )
    return value


def present_key_names() -> tuple[str, ...]:
    return tuple(name for name in _KEY_NAMES if (os.environ.get(name) or "").strip())


def _resolve_vertex_project() -> str:
    explicit = (os.environ.get("VERTEX_AI_PROJECT") or "").strip()
    if explicit:
        return explicit
    unique = {
        value
        for name in ("GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT")
        if (value := (os.environ.get(name) or "").strip())
    }
    if len(unique) == 1:
        return next(iter(unique))
    if not unique:
        raise GeminiBackendError(
            "VERTEX_AI PDF Vision requires VERTEX_AI_PROJECT, or a single explicit "
            "GCP_PROJECT_ID / GOOGLE_CLOUD_PROJECT value."
        )
    raise GeminiBackendError(
        "VERTEX_AI requires a single explicit project. "
        "GCP_PROJECT_ID and GOOGLE_CLOUD_PROJECT disagree; set VERTEX_AI_PROJECT."
    )


def build_genai_client(genai_module: Any, *, fallback_api_key: str | None = None) -> Any:
    """Construct ``genai.Client`` for the selected backend. Never mix key and SA."""
    backend = resolve_backend()
    if backend == DEVELOPER_API:
        api_key = (fallback_api_key or "").strip()
        if not api_key:
            for name in _KEY_NAMES:
                api_key = (os.environ.get(name) or "").strip()
                if api_key:
                    break
        if not api_key:
            raise GeminiBackendError(
                "DEVELOPER_API PDF Vision requires GEMINI_API_KEY or GOOGLE_API_KEY. "
                "VERTEX_AI is not used as a fallback."
            )
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
        return genai_module.Client(api_key=api_key)

    present = present_key_names()
    if present:
        raise GeminiBackendError(
            "VERTEX_AI refuses Gemini/Google API keys in the process environment "
            f"({', '.join(present)}). Unset them before constructing the Vision client."
        )
    project = _resolve_vertex_project()
    location = (os.environ.get("VERTEX_AI_PDF_LOCATION") or "").strip()
    if not location:
        raise GeminiBackendError(
            "VERTEX_AI PDF Vision requires VERTEX_AI_PDF_LOCATION."
        )
    if location.casefold() == UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER:
        raise GeminiBackendError(
            "VERTEX_AI_PDF_LOCATION is the unapproved P0 placeholder 'global'. "
            "Set a BU-approved Vertex location."
        )
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project
    os.environ["GOOGLE_CLOUD_LOCATION"] = location
    return genai_module.Client(vertexai=True, project=project, location=location)
