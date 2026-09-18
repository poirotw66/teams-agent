"""Signed user-delegation envelope for BFF → Portal calls.

Service identity uses Authorization: Bearer <portal service token>.
User identity uses X-Knowledge-Delegation (never X-Portal-* from the browser).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from agent_service.operations.access import ActorContext
from platform_kernel.delegation import (
    DelegationError,
    b64url,
    verify_delegation_envelope,
)

from .capabilities import knowledge_capabilities_for, portal_role_for

DELEGATION_HEADER = "X-Knowledge-Delegation"
DEFAULT_TTL_SECONDS = 300

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "DELEGATION_HEADER",
    "DelegationError",
    "issue_delegation_envelope",
    "verify_delegation_envelope",
]


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
    body = b64url(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    )
    signature = b64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{signature}"
