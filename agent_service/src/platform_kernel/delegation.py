"""Delegation envelope verify contract (BFF → Portal).

Issue/sign helpers that depend on Backoffice ActorContext remain in
``ai_ops_backoffice.knowledge_bridge.delegation``. Portal only needs verify.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class DelegationError(Exception):
    pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


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
    expected = b64url(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(expected, signature):
        raise DelegationError("invalid delegation signature")
    try:
        payload = json.loads(b64url_decode(body).decode("utf-8"))
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
