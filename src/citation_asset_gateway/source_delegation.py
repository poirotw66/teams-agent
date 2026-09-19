"""Issue Adapter-side source delegation envelopes without importing Backoffice."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

DEFAULT_AUDIENCE = "ai-ops-sources"
DEFAULT_ISSUER = "teams-agent-adapter"
DEFAULT_TTL_SECONDS = 300
DELEGATION_HEADER = "X-Source-Delegation"


class SourceDelegationError(Exception):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def issue_source_delegation(
    *,
    subject: str,
    secret: str,
    tenant_id: str | None = None,
    groups: tuple[str, ...] | list[str] = (),
    display_name: str | None = None,
    correlation_id: str | None = None,
    audience: str = DEFAULT_AUDIENCE,
    issuer: str = DEFAULT_ISSUER,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> str:
    if not secret:
        raise SourceDelegationError("source delegation secret is not configured")
    subject_value = str(subject or "").strip()
    if not subject_value:
        raise SourceDelegationError("source delegation subject is required")
    issued_at = int(now if now is not None else time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject_value,
        "name": (display_name or subject_value).strip(),
        "tenantId": (tenant_id or "default").strip() or "default",
        "groups": [str(item).strip() for item in groups if str(item).strip()],
        "role": "VIEWER",
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
        "jti": uuid.uuid4().hex,
        "correlationId": correlation_id or uuid.uuid4().hex,
    }
    body = _b64url(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    signature = _b64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def verify_source_delegation(
    token: str,
    *,
    secret: str,
    audience: str = DEFAULT_AUDIENCE,
    issuer: str = DEFAULT_ISSUER,
    now: float | None = None,
) -> dict[str, object]:
    """Verify an Adapter-issued delegation envelope (mirrors Backoffice)."""

    if not secret:
        raise SourceDelegationError("source delegation secret is not configured")
    try:
        body, signature = token.split(".", 1)
    except ValueError as error:
        raise SourceDelegationError("malformed source delegation envelope") from error
    expected = _b64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, signature):
        raise SourceDelegationError("invalid source delegation signature")
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SourceDelegationError("invalid source delegation payload") from error
    if not isinstance(payload, dict):
        raise SourceDelegationError("invalid source delegation payload")
    if payload.get("iss") != issuer:
        raise SourceDelegationError("invalid source delegation issuer")
    if payload.get("aud") != audience:
        raise SourceDelegationError("invalid source delegation audience")
    current = int(now if now is not None else time.time())
    if int(payload.get("exp") or 0) < current:
        raise SourceDelegationError("source delegation expired")
    if int(payload.get("iat") or 0) > current + 30:
        raise SourceDelegationError("source delegation issued in the future")
    if not payload.get("sub"):
        raise SourceDelegationError("source delegation missing subject")
    return payload
