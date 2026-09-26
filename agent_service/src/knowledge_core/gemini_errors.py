"""Classify Gemini startup and request failures without leaking credentials."""

from __future__ import annotations

import re
from enum import StrEnum

from .gemini_backend import GeminiConfigurationError

__all__ = [
    "GeminiErrorClass",
    "GeminiStartupError",
    "classify_gemini_error",
    "raise_classified_gemini_error",
    "safe_gemini_error_text",
]

_SECRET_PATTERN = re.compile(
    r"(?:AIza[0-9A-Za-z_\-]{20,}|ya29\.[0-9A-Za-z_\-\.]+|GOOG[0-9A-Za-z_\-]{10,}"
    r"|Bearer\s+[A-Za-z0-9._\-]+)",
    re.IGNORECASE,
)
_KEY_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|token|credential|secret)\s*[:=]\s*)\S+"
)


class GeminiErrorClass(StrEnum):
    MISSING_API_KEY = "missing_api_key"
    MISSING_ADC = "missing_adc"
    IAM_DENIED = "iam_403"
    MODEL_OR_LOCATION_UNAVAILABLE = "model_or_location_unavailable"
    QUOTA_EXCEEDED = "quota_429"
    UNSUPPORTED_PARAMETER = "unsupported_param_400"
    CONFIGURATION_CONFLICT = "configuration_conflict"
    UNKNOWN = "unknown"


class GeminiStartupError(RuntimeError):
    """Classified Gemini failure safe to log (no credentials or tokens)."""

    def __init__(self, error_class: GeminiErrorClass, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class


def safe_gemini_error_text(error: BaseException) -> str:
    text = f"{type(error).__name__}: {error}"
    text = _SECRET_PATTERN.sub("<redacted>", text)
    return _KEY_ASSIGNMENT_PATTERN.sub(r"\1<redacted>", text)


def classify_gemini_error(error: BaseException) -> GeminiErrorClass:
    if isinstance(error, GeminiConfigurationError):
        text = str(error).lower()
        if "refuses" in text or "process environment" in text:
            return GeminiErrorClass.CONFIGURATION_CONFLICT
        if "requires gemini_api_key" in text or "google_api_key" in text:
            return GeminiErrorClass.MISSING_API_KEY
        return GeminiErrorClass.CONFIGURATION_CONFLICT

    type_name = type(error).__name__
    text = safe_gemini_error_text(error).lower()
    if type_name in {"DefaultCredentialsError", "RefreshError"} or (
        "could not automatically determine credentials" in text
        or "reauthentication is needed" in text
        or "adc" in text
        and "credential" in text
    ):
        return GeminiErrorClass.MISSING_ADC
    if (
        type_name in {"PermissionDenied", "Forbidden"}
        or "permission_denied" in text
        or "permissiondenied" in text
        or "permission denied" in text
        or "403" in text
    ):
        return GeminiErrorClass.IAM_DENIED
    if (
        type_name in {"ResourceExhausted", "TooManyRequests"}
        or "429" in text
        or "resource_exhausted" in text
        or ("quota" in text and ("exceed" in text or "exhausted" in text))
    ):
        return GeminiErrorClass.QUOTA_EXCEEDED
    if (
        "invalid argument" in text
        or "unsupported" in text
        and ("temperature" in text or "top_p" in text or "top_k" in text or "parameter" in text)
        or "unknown field" in text
        or (" 400" in text and "temperature" in text)
    ):
        return GeminiErrorClass.UNSUPPORTED_PARAMETER
    if (
        type_name in {"NotFound"}
        or " 404" in text
        or "not found" in text
        or "not available" in text
        or "does not have access to model" in text
        or "location" in text
        and ("unavailable" in text or "not supported" in text)
    ):
        return GeminiErrorClass.MODEL_OR_LOCATION_UNAVAILABLE
    if "api key" in text or "gemini_api_key" in text or "google_api_key" in text:
        return GeminiErrorClass.MISSING_API_KEY
    return GeminiErrorClass.UNKNOWN


def raise_classified_gemini_error(error: BaseException, *, context: str) -> None:
    """Re-raise a classified error. Never includes tokens or credentials."""
    if isinstance(error, GeminiStartupError):
        raise error
    error_class = classify_gemini_error(error)
    message = f"{context}: {error_class.value}: {safe_gemini_error_text(error)}"
    if isinstance(error, GeminiConfigurationError):
        raise GeminiConfigurationError(message) from error
    raise GeminiStartupError(error_class, message) from error
