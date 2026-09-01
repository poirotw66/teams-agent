from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .contracts import MASKING_POLICY_VERSION

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\b(?:\+886|0)\d{1,2}[- ]?\d{3,4}[- ]?\d{3,4}\b")
_EMPLOYEE_ID_PATTERN = re.compile(r"\b[A-Z]{1,3}\d{5,8}\b")
_CREDENTIAL_MARKERS = (
    "password",
    "api key",
    "apikey",
    "secret",
    "token",
    "otp",
    "verification code",
    "密碼",
    "驗證碼",
)


@dataclass(frozen=True)
class MaskingResult:
    text: str
    was_masked: bool
    contains_credential: bool
    policy_version: str = MASKING_POLICY_VERSION


def pseudonymous_actor_id(raw_id: str | None) -> str | None:
    if not raw_id:
        return None
    digest = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
    return f"actor_{digest[:16]}"


def mask_text(text: str, *, reveal: bool = False) -> MaskingResult:
    if reveal:
        return MaskingResult(text=text, was_masked=False, contains_credential=False)
    lowered = text.lower()
    contains_credential = any(marker in lowered for marker in _CREDENTIAL_MARKERS)
    if contains_credential:
        return MaskingResult(
            text="[REDACTED_CREDENTIAL]",
            was_masked=True,
            contains_credential=True,
        )
    masked = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    masked = _PHONE_PATTERN.sub("[REDACTED_PHONE]", masked)
    masked = _EMPLOYEE_ID_PATTERN.sub("[REDACTED_ID]", masked)
    return MaskingResult(
        text=masked,
        was_masked=masked != text,
        contains_credential=False,
    )


def redact_secrets(payload: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(token in lowered for token in ("password", "secret", "token", "api_key", "credential")):
            redacted[key] = "[REDACTED]"
            continue
        if isinstance(value, dict):
            redacted[key] = redact_secrets(value)  # type: ignore[arg-type]
        elif isinstance(value, str):
            redacted[key] = mask_text(value).text
        else:
            redacted[key] = value
    return redacted
