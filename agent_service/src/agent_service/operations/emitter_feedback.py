"""Feedback event construction and provenance recovery."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..contracts import FeedbackRequest
from .contracts import OperationalEvent, utc_now
from .emitter_exceptions import OperationalEventReplayConflict
from .emitter_replay import ReplayFingerprintStore
from .event_identity import (
    LogicalRequestIdentity,
    event_fingerprint,
    feedback_event_id,
    feedback_submission_event_id,
    required_utc,
)
from .ingestion import EventIngestionService
from .masking import mask_text, pseudonymous_actor_id
from .policy_runtime import active_retention_days
from .settings import OpsSettings

FeedbackProvenance = tuple[str, str, str | None, str]
FeedbackProvenanceMap = dict[tuple[str, str], FeedbackProvenance | None]
FeedbackEventCache = dict[str, tuple[str, OperationalEvent]]
ResolvedFeedbackIdentity = tuple[str, str | None, str, str]


def _resolve_feedback_identity(
    payload: FeedbackRequest,
    feedback_provenance: FeedbackProvenanceMap,
    *,
    tenant_id: str | None,
    actor_id: str | None,
    request_id: str | None,
) -> ResolvedFeedbackIdentity:
    provenance_key = (payload.correlationId, payload.conversationId or "")
    trusted = feedback_provenance.get(provenance_key)
    if provenance_key in feedback_provenance and trusted is None:
        raise ValueError("feedback provenance is ambiguous")
    canonical_conversation_id = payload.conversationId
    if trusted is not None:
        trusted_tenant, trusted_request, trusted_actor, canonical_conversation_id = trusted
        if tenant_id is not None and tenant_id != trusted_tenant:
            raise OperationalEventReplayConflict("feedback tenant does not match turn")
        if request_id is not None and request_id != trusted_request:
            raise OperationalEventReplayConflict("feedback request does not match turn")
        if actor_id is not None and actor_id != trusted_actor:
            raise OperationalEventReplayConflict("feedback actor does not match turn")
        tenant_id, request_id, actor_id = trusted_tenant, trusted_request, trusted_actor
    if not tenant_id or not actor_id:
        raise ValueError("trusted feedback tenant and actor provenance are required")
    if payload.userId is not None and payload.userId != actor_id:
        raise OperationalEventReplayConflict("feedback user does not match turn actor")
    return tenant_id, request_id, actor_id, canonical_conversation_id


def _new_feedback_event(
    *,
    payload: FeedbackRequest,
    settings: OpsSettings,
    tenant_id: str,
    request_id: str | None,
    actor_id: str,
    conversation_id: str,
    feedback_id: str,
    occurred_at: datetime | None,
) -> OperationalEvent:
    timestamp = required_utc(occurred_at or utc_now(), "feedback occurred_at")
    identity = (
        LogicalRequestIdentity(tenant_id, conversation_id, request_id)
        if request_id
        else None
    )
    return OperationalEvent(
        event_id=feedback_submission_event_id(tenant_id, feedback_id),
        event_type="feedback.recorded",
        occurred_at=timestamp,
        retention_expires_at=timestamp + timedelta(days=active_retention_days(settings)),
        environment=settings.environment,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        request_id=request_id,
        turn_id=identity.value if identity else None,
        issue_occurrence_id=(
            identity.issue_occurrence_id(payload.issueId)
            if identity and payload.issueId is not None
            else None
        ),
        correlation_id=payload.correlationId,
        actor_ref=pseudonymous_actor_id(actor_id),
        data_classification="CONFIDENTIAL",
        payload={
            "rating": payload.rating,
            "issueId": payload.issueId,
            "reason": mask_text(payload.reason).text if payload.reason else None,
            "resolvedStatus": payload.resolvedStatus,
        },
    )


def build_feedback_event(
    *,
    payload: FeedbackRequest,
    settings: OpsSettings,
    replay: ReplayFingerprintStore,
    feedback_provenance: FeedbackProvenanceMap,
    feedback_events: FeedbackEventCache,
    tenant_id: str | None = None,
    feedback_id: str | None = None,
    occurred_at: datetime | None = None,
    actor_id: str | None = None,
    request_id: str | None = None,
) -> OperationalEvent:
    tenant_id, request_id, actor_id, conversation_id = _resolve_feedback_identity(
        payload,
        feedback_provenance,
        tenant_id=tenant_id,
        actor_id=actor_id,
        request_id=request_id,
    )
    feedback_id = feedback_id or feedback_event_id(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        correlation_id=payload.correlationId,
        issue_id=payload.issueId,
        rating=payload.rating,
        resolved_status=payload.resolvedStatus,
        actor_id=actor_id,
        reason=payload.reason,
    )
    feedback_fact = event_fingerprint(payload.model_dump(mode="json"))
    existing = feedback_events.get(feedback_id)
    if existing is not None:
        if existing[0] != feedback_fact:
            raise OperationalEventReplayConflict("feedback replay changed immutable facts")
        return existing[1]
    event = _new_feedback_event(
        payload=payload,
        settings=settings,
        tenant_id=tenant_id,
        request_id=request_id,
        actor_id=actor_id,
        conversation_id=conversation_id,
        feedback_id=feedback_id,
        occurred_at=occurred_at,
    )
    replay.assert_immutable(event.event_id, payload.model_dump(mode="json"), [event])
    feedback_events[feedback_id] = (feedback_fact, event)
    return event

async def persisted_feedback_exists(
    *,
    payload: FeedbackRequest,
    ingestion: EventIngestionService,
    feedback_provenance: FeedbackProvenanceMap,
) -> bool:
    provenance = feedback_provenance.get(
        (payload.correlationId, payload.conversationId or "")
    )
    if provenance is None:
        return False
    tenant_id, request_id, actor_id, conversation_id = provenance
    feedback_id = feedback_event_id(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        correlation_id=payload.correlationId,
        issue_id=payload.issueId,
        rating=payload.rating,
        resolved_status=payload.resolvedStatus,
        actor_id=actor_id,
        reason=payload.reason,
    )
    event_id = feedback_submission_event_id(tenant_id, feedback_id)
    events = await ingestion.find_events(correlation_id=payload.correlationId)
    existing = next((event for event in events if event.event_id == event_id), None)
    if existing is None:
        return False
    expected_payload = {
        "rating": payload.rating,
        "issueId": payload.issueId,
        "reason": mask_text(payload.reason).text if payload.reason else None,
        "resolvedStatus": payload.resolvedStatus,
    }
    identity_conflict = any(
        (
            existing.tenant_id != tenant_id,
            existing.request_id != request_id,
            existing.conversation_id != conversation_id,
            existing.actor_ref != pseudonymous_actor_id(actor_id),
            any(
                existing.payload.get(key) != value
                for key, value in expected_payload.items()
            ),
        )
    )
    if identity_conflict:
        raise OperationalEventReplayConflict("persisted feedback identity conflict")
    return True


async def restore_feedback_provenance(
    *,
    payload: FeedbackRequest,
    ingestion: EventIngestionService,
    feedback_provenance: FeedbackProvenanceMap,
) -> None:
    events = await ingestion.find_events(correlation_id=payload.correlationId)
    turns = [event for event in events if event.event_type == "turn.received"]
    if payload.conversationId:
        canonical_matches = [
            event for event in turns if event.conversation_id == payload.conversationId
        ]
        if canonical_matches:
            turns = canonical_matches
    actor_ref = pseudonymous_actor_id(payload.userId)
    if actor_ref is not None:
        turns = [event for event in turns if event.actor_ref == actor_ref]
    candidates = {
        (
            event.tenant_id,
            event.request_id,
            event.actor_ref,
            event.conversation_id,
        )
        for event in turns
        if event.tenant_id and event.request_id and event.actor_ref and event.conversation_id
    }
    if len(candidates) != 1 or payload.userId is None:
        raise ValueError("feedback provenance cannot be resolved uniquely")
    tenant_id, request_id, trusted_actor_ref, conversation_id = candidates.pop()
    if pseudonymous_actor_id(payload.userId) != trusted_actor_ref:
        raise OperationalEventReplayConflict("feedback user does not match turn actor")
    feedback_provenance[(payload.correlationId, payload.conversationId or "")] = (
        tenant_id,
        request_id,
        payload.userId,
        conversation_id,
    )


async def emit_feedback(
    *,
    payload: FeedbackRequest,
    settings: OpsSettings,
    ingestion: EventIngestionService,
    replay: ReplayFingerprintStore,
    feedback_provenance: FeedbackProvenanceMap,
    feedback_events: FeedbackEventCache,
    provenance: dict[str, Any],
) -> None:
    provenance_key = (payload.correlationId, payload.conversationId or "")
    if not provenance and provenance_key not in feedback_provenance:
        await restore_feedback_provenance(
            payload=payload,
            ingestion=ingestion,
            feedback_provenance=feedback_provenance,
        )
    if not provenance and await persisted_feedback_exists(
        payload=payload,
        ingestion=ingestion,
        feedback_provenance=feedback_provenance,
    ):
        return
    await ingestion.ingest(
        build_feedback_event(
            payload=payload,
            settings=settings,
            replay=replay,
            feedback_provenance=feedback_provenance,
            feedback_events=feedback_events,
            **provenance,
        )
    )
