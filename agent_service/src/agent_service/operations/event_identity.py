"""Deterministic identities for operational events.

The producer's idempotency boundary is a logical request, not a correlation
identifier.  Correlation identifiers trace work, but callers may legally
reuse them for more than one request.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _stable_uuid(*parts: object) -> str:
    """Return a UUID-shaped, non-reversible identifier for the supplied parts."""
    encoded = json.dumps(parts, ensure_ascii=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16], version=5))


def _scope(value: str | None) -> str | None:
    # JSON null must not collide with an actual string such as '<none>'.
    return value


def required_utc(value: object, name: str) -> datetime:
    """Reject absent/ambiguous timestamps instead of inventing an occurrence."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{name} must be an aware ISO timestamp") from None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} requires a durable timezone-aware timestamp")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class LogicalRequestIdentity:
    """A tenant-scoped, replay-safe identity for one agent request."""

    tenant_id: str | None
    conversation_id: str | None
    request_id: str

    @property
    def value(self) -> str:
        return _stable_uuid(
            "operations.logical-request.v1",
            _scope(self.tenant_id),
            _scope(self.conversation_id),
            self.request_id,
        )

    def event_id(self, event_type: str, *discriminators: object) -> str:
        return _stable_uuid(
            "operations.event.v1",
            _scope(self.tenant_id),
            self.value,
            event_type,
            *discriminators,
        )

    def issue_occurrence_id(self, issue_id: object) -> str:
        return _stable_uuid("operations.issue-occurrence.v1", self.value, issue_id)


def feedback_event_id(
    *,
    tenant_id: str | None,
    conversation_id: str | None,
    correlation_id: str,
    issue_id: int | None,
    rating: str,
    resolved_status: str | None,
    actor_id: str | None,
    reason: str | None,
) -> str:
    """Build an idempotency key from all feedback fields that identify a fact.

    ``FeedbackRequest`` currently has no tenant or feedback-id field.  The
    optional tenant is accepted for the future contract; without it a global
    tenant collision cannot be ruled out and is documented at the boundary.
    The reason is hashed as input and is never represented in the identifier.
    """
    return _stable_uuid(
        "operations.feedback.v1",
        _scope(tenant_id),
        _scope(conversation_id),
        correlation_id,
        issue_id,
        rating,
        resolved_status,
        _scope(actor_id),
        reason or "",
    )


def conversation_started_event_id(
    *, tenant_id: str | None, conversation_id: str
) -> str:
    """Identify a conversation lifecycle fact independently of any request."""
    return _stable_uuid(
        "operations.conversation-started.v1", _scope(tenant_id), conversation_id
    )


def feedback_submission_event_id(tenant_id: str, submission_id: str) -> str:
    return _stable_uuid("operations.feedback-submission.v1", tenant_id, submission_id)


def event_fingerprint(event: Any) -> str:
    """Canonical fingerprint used only to detect an in-process replay conflict."""
    if hasattr(event, "model_dump"):
        value = event.model_dump(mode="json")
    else:
        value = event
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
