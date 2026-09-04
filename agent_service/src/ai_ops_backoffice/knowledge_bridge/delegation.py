"""Signed user-delegation envelope for BFF → Portal calls.

Service identity uses Authorization: Bearer <portal service token>.
User identity uses X-Knowledge-Delegation (never X-Portal-* from the browser).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from agent_service.operations.access import ActorContext

from .capabilities import knowledge_capabilities_for, portal_role_for

DELEGATION_HEADER = "X-Knowledge-Delegation"
DEFAULT_TTL_SECONDS = 300


class DelegationError(Exception):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_delegation_envelope(
    actor: ActorContext,
    *,
    secret: str,
    correlation_id: str,
    audience: str = "knowledge-portal",
    issuer: str = "ai-ops-backoffice",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> str:
    if not secret:
        raise DelegationError("delegation secret is not configured")
    issued_at = int(now if now is not None else time.time())
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": actor.user_id,
        "name": actor.display_name,
        "tenantId": actor.tenant_id or "local-development",
        "ownerUnitIds": list(actor.owner_unit_ids),
        "capabilities": sorted(knowledge_capabilities_for(actor)),
        "portalRole": portal_role_for(actor),
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
        "jti": uuid.uuid4().hex,
        "correlationId": correlation_id,
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


def verify_delegation_envelope(
    token: str,
    *,
    secret: str,
    audience: str = "knowledge-portal",
    issuer: str = "ai-ops-backoffice",
    now: float | None = None,
) -> dict[str, Any]:
    if not secret:
        raise DelegationError("delegation secret is not configured")
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise DelegationError("malformed delegation envelope") from exc
    expected = _b64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, signature):
        raise DelegationError("invalid delegation signature")
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DelegationError("invalid delegation payload") from exc
    if payload.get("iss") != issuer:
        raise DelegationError("invalid delegation issuer")
    if payload.get("aud") != audience:
        raise DelegationError("invalid delegation audience")
    current = int(now if now is not None else time.time())
    if int(payload.get("exp") or 0) < current:
        raise DelegationError("delegation expired")
    if int(payload.get("iat") or 0) > current + 30:
        raise DelegationError("delegation issued in the future")
    if not payload.get("sub"):
        raise DelegationError("delegation missing subject")
    return payload
