"""Shared example create call used by source-specific routes."""

from __future__ import annotations

from ..request_models import ExampleCreateRequest


def create_example_from_payload(
    example_service,
    *,
    source_type: str,
    source_id: str,
    source_version_id: str | None,
    source_correlation_id: str | None,
    owner_unit_id: str,
    payload: ExampleCreateRequest,
    actor,
    idempotency_key: str | None,
    correlation_id: str | None,
) -> dict[str, object]:
    return example_service.create(
        source_type=source_type,
        source_id=source_id,
        source_version_id=source_version_id,
        source_correlation_id=source_correlation_id,
        owner_unit_id=owner_unit_id,
        text=payload.text,
        expected_issue_type_id=payload.expected_issue_type_id,
        expected_route=payload.expected_route,
        label=payload.label,
        reason=payload.reason,
        actor=actor,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
