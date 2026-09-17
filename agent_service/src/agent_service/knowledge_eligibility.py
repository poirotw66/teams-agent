"""Deterministic generation eligibility for governed knowledge chunks."""

from __future__ import annotations

from datetime import UTC, datetime

from .documents import DocumentChunk

ACTIVE_CONTENT_STATE = "ACTIVE"


def _parse_timestamp(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_chunk_generation_eligible(
    chunk: DocumentChunk,
    *,
    environment: str,
    evaluated_at: datetime | None = None,
) -> bool:
    """Return whether a caller may consider a chunk for answer generation."""

    return is_generation_metadata_eligible(
        content_state=chunk.content_state,
        effective_at=chunk.effective_at,
        expires_at=chunk.expires_at,
        applicable_environments=chunk.applicable_environments,
        environment=environment,
        evaluated_at=evaluated_at,
    )


def is_generation_metadata_eligible(
    *,
    content_state: str,
    effective_at: str | None,
    expires_at: str | None,
    applicable_environments: list[str],
    environment: str,
    evaluated_at: datetime | None = None,
) -> bool:
    """Evaluate release metadata without requiring a materialized chunk."""

    if content_state.strip().upper() != ACTIVE_CONTENT_STATE:
        return False

    now = evaluated_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    if effective_at:
        parsed_effective_at = _parse_timestamp(effective_at)
        if parsed_effective_at is None or parsed_effective_at > now:
            return False
    if expires_at:
        parsed_expires_at = _parse_timestamp(expires_at)
        if parsed_expires_at is None or parsed_expires_at <= now:
            return False

    allowed_environments = {
        candidate.strip().casefold() for candidate in applicable_environments if candidate.strip()
    }
    return not allowed_environments or environment.strip().casefold() in allowed_environments


__all__ = [
    "ACTIVE_CONTENT_STATE",
    "is_chunk_generation_eligible",
    "is_generation_metadata_eligible",
]
