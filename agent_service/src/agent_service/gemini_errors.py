"""Compatibility shim. Implementation lives in ``knowledge_core.gemini_errors``."""

from knowledge_core.gemini_errors import (
    GeminiErrorClass,
    GeminiStartupError,
    classify_gemini_error,
    raise_classified_gemini_error,
    safe_gemini_error_text,
)

__all__ = [
    "GeminiErrorClass",
    "GeminiStartupError",
    "classify_gemini_error",
    "raise_classified_gemini_error",
    "safe_gemini_error_text",
]
