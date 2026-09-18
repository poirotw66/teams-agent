from __future__ import annotations

import re
from typing import Any

from agent_service.operations.masking import mask_text
from platform_kernel.hashing import content_hash, fingerprint, short_version, sticky_bucket

from .constants import INJECTION_SIGNATURES, SECRET_REF_PREFIX
from .errors import GovernanceConflictError, GovernanceValidationError
from .models import GovernanceState, IdempotencyRecord

SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|secret|token|password)\s*[:=]\s*[^\s]{8,}"
)
RAW_KEY_PATTERN = re.compile(r"(?i)^(sk-|AIza|ghp_|ya29\.)")

__all__ = [
    "content_hash",
    "fingerprint",
    "public_prompt",
    "reject_secrets_and_injection",
    "replay",
    "require_secret_ref",
    "short_version",
    "sticky_bucket",
    "with_idempotency",
]


def require_secret_ref(value: str) -> str:
    if not value.startswith(SECRET_REF_PREFIX):
        raise GovernanceValidationError("secret values are not allowed; use a secret reference")
    remainder = value[len(SECRET_REF_PREFIX) :]
    if not remainder or any(character in remainder for character in "=\n\r\t "):
        raise GovernanceValidationError("secret reference must not contain a secret value")
    if RAW_KEY_PATTERN.search(remainder):
        raise GovernanceValidationError("secret reference must not contain a secret value")
    return value


def reject_secrets_and_injection(text: str, *, label: str) -> None:
    lowered = text.casefold()
    if SECRET_VALUE_PATTERN.search(text) or mask_text(text).contains_credential:
        raise GovernanceValidationError(f"{label} failed secret inspection")
    if any(signature in lowered for signature in INJECTION_SIGNATURES):
        raise GovernanceValidationError(f"{label} failed prompt injection inspection")


def replay(
    state: GovernanceState,
    *,
    key: str | None,
    action: str,
    request_fingerprint: str,
) -> dict[str, Any] | None:
    if not key:
        return None
    for record in state.idempotency:
        if record.key != key:
            continue
        if record.action != action or record.request_fingerprint != request_fingerprint:
            raise GovernanceConflictError("idempotency key was reused with a different request")
        return record.result
    return None


def with_idempotency(
    state: GovernanceState,
    *,
    key: str | None,
    action: str,
    request_fingerprint: str,
    result: dict[str, Any],
    created_at: Any,
) -> tuple[IdempotencyRecord, ...]:
    if not key:
        return state.idempotency
    record = IdempotencyRecord(
        key=key,
        action=action,
        request_fingerprint=request_fingerprint,
        result=result,
        created_at=created_at,
    )
    return (*state.idempotency, record)


def public_prompt(version: Any, *, include_content: bool) -> dict[str, Any]:
    payload = version.model_dump(mode="json")
    if not include_content:
        payload.pop("template", None)
    return payload
