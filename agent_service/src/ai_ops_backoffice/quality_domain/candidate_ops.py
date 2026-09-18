"""Quality candidate listing and mutation use-case helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from operations_core.access import ActorContext
from operations_core.masking import mask_text

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
)
from .case_ops import (
    build_case_from_candidates,
    build_quality_audit,
    candidate_identity_hash,
    find_associated_active_case,
)
from .models import QualityCandidate, QualityState
from .ops_common import authorize
from .repository import QualityRepository

__all__ = [
    "add_candidate",
    "list_candidates",
    "merge_candidates",
]


def list_candidates(
    repository: QualityRepository,
    *,
    actor: ActorContext,
    status: str | None = None,
) -> list[dict[str, Any]]:
    visible = []
    for item in repository.load().candidates:
        try:
            authorize(actor, "ops.quality.read", item.owner_unit_id)
        except FaqAuthorizationError:
            continue
        if status and item.status != status:
            continue
        visible.append(item.model_dump(mode="json"))
    return visible


def add_candidate(
    repository: QualityRepository,
    *,
    source_type: str,
    case_type: str,
    title: str,
    description: str,
    issue_type_id: str | None,
    question_cluster_id: str | None,
    owner_unit_id: str,
    source_event_ids: tuple[str, ...] = (),
    conversation_refs: tuple[str, ...] = (),
    faq_ids: tuple[str, ...] = (),
    document_ids: tuple[str, ...] = (),
    frequency: int = 1,
    negative_rate: float = 0,
    handoff_rate: float = 0,
    estimated_cost_impact: float = 0,
    actor: ActorContext,
) -> dict[str, Any]:
    authorize(actor, "ops.quality.write", owner_unit_id)
    masked = mask_text(description)
    if masked.contains_credential:
        raise FaqValidationError("credentials are not allowed in quality candidates")
    candidate_id = candidate_identity_hash(
        source_type=source_type,
        case_type=case_type,
        issue_type_id=issue_type_id,
        source_event_ids=source_event_ids,
    )
    now = datetime.now(UTC)
    candidate = QualityCandidate(
        candidate_id=candidate_id,
        source_type=source_type,
        case_type=case_type,
        title=title,
        description=masked.text,
        issue_type_id=issue_type_id,
        question_cluster_id=question_cluster_id,
        owner_unit_id=owner_unit_id,
        source_event_ids=source_event_ids,
        conversation_refs=conversation_refs,
        faq_ids=faq_ids,
        document_ids=document_ids,
        frequency=frequency,
        negative_rate=negative_rate,
        handoff_rate=handoff_rate,
        estimated_cost_impact=estimated_cost_impact,
        created_at=now,
        updated_at=now,
    )

    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        return _insert_candidate(
            state,
            candidate=candidate,
            conversation_refs=conversation_refs,
            source_event_ids=source_event_ids,
            actor=actor,
            owner_unit_id=owner_unit_id,
        )

    return repository.mutate(operation)


def _insert_candidate(
    state: QualityState,
    *,
    candidate: QualityCandidate,
    conversation_refs: tuple[str, ...],
    source_event_ids: tuple[str, ...],
    actor: ActorContext,
    owner_unit_id: str,
) -> tuple[QualityState, dict[str, Any]]:
    existing = next(
        (item for item in state.candidates if item.candidate_id == candidate.candidate_id),
        None,
    )
    if existing is not None:
        return state.model_copy(update={"revision": state.revision + 1}), {
            "candidate": existing.model_dump(mode="json")
        }

    associated_case = find_associated_active_case(
        state.cases,
        conversation_refs=conversation_refs,
        source_event_ids=source_event_ids,
    )
    resolved_candidate = candidate
    if associated_case is not None:
        resolved_candidate = candidate.model_copy(
            update={"status": "MERGED", "merged_case_id": associated_case.case_id}
        )
    audit = build_quality_audit(
        target_type="QUALITY_CANDIDATE",
        target_id=candidate.candidate_id,
        action="QUALITY_CANDIDATE_CREATED",
        actor=actor,
        owner_unit_id=owner_unit_id,
        before=None,
        after=resolved_candidate,
        reason=(
            f"auto_linked_to_in_progress_case:{associated_case.case_id}"
            if associated_case
            else None
        ),
    )
    next_state = QualityState(
        revision=state.revision + 1,
        candidates=(*state.candidates, resolved_candidate),
        cases=state.cases,
        clusters=state.clusters,
        audits=(*state.audits, audit),
    )
    return next_state, {"candidate": resolved_candidate.model_dump(mode="json")}


def merge_candidates(
    repository: QualityRepository,
    candidate_ids: tuple[str, ...],
    *,
    title: str,
    description: str,
    priority: str,
    assignee_id: str | None,
    target_due_at: datetime | None,
    actor: ActorContext,
) -> dict[str, Any]:
    if not candidate_ids:
        raise FaqValidationError("at least one candidate is required")

    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        selected = [item for item in state.candidates if item.candidate_id in candidate_ids]
        if len(selected) != len(set(candidate_ids)):
            raise FaqNotFoundError("one or more quality candidates were not found")
        if any(item.status != "OPEN" for item in selected):
            raise FaqTransitionError("only open candidates can be merged")
        owners = {item.owner_unit_id for item in selected}
        if len(owners) != 1:
            raise FaqValidationError("candidates from different owner units cannot be merged")
        owner_unit_id = next(iter(owners))
        authorize(actor, "ops.quality.write", owner_unit_id)
        now = datetime.now(UTC)
        case = build_case_from_candidates(
            selected,
            candidate_ids=candidate_ids,
            title=title,
            description=description,
            priority=priority,
            assignee_id=assignee_id,
            target_due_at=target_due_at,
            actor=actor,
            owner_unit_id=owner_unit_id,
            now=now,
        )
        candidates = tuple(
            item.model_copy(
                update={
                    "status": "MERGED",
                    "merged_case_id": case.case_id,
                    "etag": item.etag + 1,
                    "updated_at": now,
                }
            )
            if item.candidate_id in candidate_ids
            else item
            for item in state.candidates
        )
        audit = build_quality_audit(
            target_type="QUALITY_CASE",
            target_id=case.case_id,
            action="QUALITY_CASE_CREATED_FROM_CANDIDATES",
            actor=actor,
            owner_unit_id=owner_unit_id,
            before=None,
            after=case,
        )
        next_state = QualityState(
            revision=state.revision + 1,
            candidates=candidates,
            cases=(*state.cases, case),
            clusters=state.clusters,
            audits=(*state.audits, audit),
        )
        return next_state, {"case": case.model_dump(mode="json")}

    return repository.mutate(operation)
