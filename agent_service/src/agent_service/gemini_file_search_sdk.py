"""Lazy google-genai SDK bootstrap for the File Search spike adapter."""

from __future__ import annotations

_SDK_INSTALL_HINT = (
    "google-genai is required for GeminiFileSearchKnowledgeService. "
    "Install the spike extra: pip install 'teams-agent-rag-service[spike]' "
    "(or `uv sync --extra spike` from agent_service/)."
)


def import_genai():
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - exercised only without SDK
        raise ImportError(_SDK_INSTALL_HINT) from exc
    return genai, types
