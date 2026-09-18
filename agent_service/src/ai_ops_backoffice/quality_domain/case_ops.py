"""Case and retention mutation helpers for the quality domain."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from operations_core.access import ActorContext
from operations_core.masking import mask_text, redact_secrets

from .models import (
    QualityAuditEvent,
    QualityCandidate,
    QualityCase,
    QualityState,
    QuestionCluster,
)

__all__ = [
    "ACTIVE_CASE_STATUSES",
    "TERMINAL_CASE_STATUSES",
    "build_case_from_candidates",
    "build_quality_audit",
    "empty_purge_result",
    "find_associated_active_case",
    "purge_expired_quality_state",
    "quality_has_expired_records",
]


ACTIVE_CASE_STATUSES = frozenset(
    {"NEW", "TRIAGED", "IN_PROGRESS", "WAITING_REVIEW", "OBSERVING"}
)
TERMINAL_CASE_STATUSES = frozenset({"RESOLVED", "WONT_FIX", "DUPLICATE"})
PURGEABLE_CANDIDATE_STATUSES = frozenset({"MERGED", "REJECTED"})
PURGEABLE_CLUSTER_STATUSES = frozenset({"REJECTED", "SUPERSEDED"})


def build_quality_audit(
    *,
    target_type: Literal["QUALITY_CANDIDATE", "QUALITY_CASE", "QUESTION_CLUSTER"],
    target_id: str,
    action: str,
    actor: ActorContext,
    owner_unit_id: str,
    before: BaseModel | None,
    after: BaseModel | None,
    reason: str | None = None,
) -> QualityAuditEvent:
    return QualityAuditEvent(
        audit_id=str(uuid.uuid4()),
        target_type=target_type,
        target_id=target_id,
        action=action,
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=owner_unit_id,
        before=redact_secrets(before.model_dump(mode="json")) if before else None,
        after=redact_secrets(after.model_dump(mode="json")) if after else None,
        reason=mask_text(reason).text if reason else None,
        occurred_at=datetime.now(UTC),
    )


def candidate_identity_hash(
    *,
    source_type: str,
    case_type: str,
    issue_type_id: str | None,
    source_event_ids: tuple[str, ...],
) -> str:
    identity = "|".join(
        [source_type, case_type, issue_type_id or "", *sorted(source_event_ids)]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def find_associated_active_case(
    cases: tuple[QualityCase, ...],
    *,
    conversation_refs: tuple[str, ...],
    source_event_ids: tuple[str, ...],
) -> QualityCase | None:
    active_cases = [case for case in cases if case.status in ACTIVE_CASE_STATUSES]
    return next(
        (
            case
            for case in active_cases
            if (
                any(ref in case.conversation_refs for ref in conversation_refs)
                if conversation_refs
                else False
            )
            or (
                any(event_id in case.source_event_ids for event_id in source_event_ids)
                if source_event_ids
                else False
            )
        ),
        None,
    )


def build_case_from_candidates(
    selected: list[QualityCandidate],
    *,
    candidate_ids: tuple[str, ...],
    title: str,
    description: str,
    priority: str,
    assignee_id: str | None,
    target_due_at: datetime | None,
    actor: ActorContext,
    owner_unit_id: str,
    now: datetime,
) -> QualityCase:
    case_types = {item.case_type for item in selected}
    issue_types = {item.issue_type_id for item in selected if item.issue_type_id}
    frequency = sum(item.frequency for item in selected)
    return QualityCase(
        case_id=str(uuid.uuid4()),
        title=title,
        description=mask_text(description).text,
        case_type=next(iter(case_types)) if len(case_types) == 1 else "OTHER",
        issue_type_id=next(iter(issue_types)) if len(issue_types) == 1 else None,
        priority=priority,
        owner_unit_id=owner_unit_id,
        assignee_id=assignee_id,
        source_candidate_ids=tuple(candidate_ids),
        source_event_ids=tuple(
            dict.fromkeys(event for item in selected for event in item.source_event_ids)
        ),
        conversation_refs=tuple(
            dict.fromkeys(ref for item in selected for ref in item.conversation_refs)
        ),
        faq_ids=tuple(dict.fromkeys(ref for item in selected for ref in item.faq_ids)),
        document_ids=tuple(
            dict.fromkeys(ref for item in selected for ref in item.document_ids)
        ),
        frequency=frequency,
        negative_rate=sum(item.negative_rate * item.frequency for item in selected)
        / frequency,
        handoff_rate=sum(item.handoff_rate * item.frequency for item in selected)
        / frequency,
        estimated_cost_impact=sum(item.estimated_cost_impact for item in selected),
        target_due_at=target_due_at,
        created_by=actor.user_id,
        created_at=now,
        updated_by=actor.user_id,
        updated_at=now,
    )


def apply_case_status_update(
    current: QualityCase,
    *,
    status: str | None,
    resolution_type: str | None,
    reason: str | None,
    changes: dict[str, Any] | None,
    actor: ActorContext,
    now: datetime,
) -> QualityCase:
    update: dict[str, Any] = {
        **(changes or {}),
        "etag": current.etag + 1,
        "updated_by": actor.user_id,
        "updated_at": now,
    }
    if status is not None:
        observation_started = current.observation_started_at
        if status == "OBSERVING" and observation_started is None:
            observation_started = now
        update.update(
            {
                "status": status,
                "resolution_type": resolution_type,
                "resolution_note": mask_text(reason).text if reason else None,
                "resolved_at": now if status in TERMINAL_CASE_STATUSES else None,
                "observation_started_at": observation_started,
            }
        )
    return QualityCase.model_validate({**current.model_dump(mode="python"), **update})


def empty_purge_result() -> dict[str, Any]:
    return {
        "purged_candidates": 0,
        "purged_cases": 0,
        "purged_clusters": 0,
        "total": 0,
    }


def quality_retention_cutoff(*, retention_days: int, now: datetime | None = None) -> datetime:
    target_now = now or datetime.now(UTC)
    return target_now - timedelta(days=retention_days)


def quality_has_expired_records(state: QualityState, *, cutoff: datetime) -> bool:
    has_expired_candidates = any(
        candidate.status in PURGEABLE_CANDIDATE_STATUSES and candidate.updated_at < cutoff
        for candidate in state.candidates
    )
    has_expired_cases = any(
        case.status in TERMINAL_CASE_STATUSES
        and (case.resolved_at or case.updated_at) < cutoff
        for case in state.cases
    )
    has_expired_clusters = any(
        cluster.status in PURGEABLE_CLUSTER_STATUSES and cluster.created_at < cutoff
        for cluster in state.clusters
    )
    return has_expired_candidates or has_expired_cases or has_expired_clusters


def partition_purged_quality_records(
    state: QualityState,
    *,
    cutoff: datetime,
) -> tuple[
    list[QualityCandidate],
    list[str],
    list[QualityCase],
    list[str],
    list[QuestionCluster],
    list[str],
]:
    kept_candidates: list[QualityCandidate] = []
    purged_candidate_ids: list[str] = []
    for candidate in state.candidates:
        if (
            candidate.status in PURGEABLE_CANDIDATE_STATUSES
            and candidate.updated_at < cutoff
        ):
            purged_candidate_ids.append(candidate.candidate_id)
        else:
            kept_candidates.append(candidate)

    kept_cases: list[QualityCase] = []
    purged_case_ids: list[str] = []
    for case in state.cases:
        if case.status in TERMINAL_CASE_STATUSES:
            retention_time = case.resolved_at or case.updated_at
            if retention_time < cutoff:
                purged_case_ids.append(case.case_id)
                continue
        kept_cases.append(case)

    kept_clusters: list[QuestionCluster] = []
    purged_cluster_ids: list[str] = []
    for cluster in state.clusters:
        if (
            cluster.status in PURGEABLE_CLUSTER_STATUSES
            and cluster.created_at < cutoff
        ):
            purged_cluster_ids.append(cluster.cluster_id)
        else:
            kept_clusters.append(cluster)

    return (
        kept_candidates,
        purged_candidate_ids,
        kept_cases,
        purged_case_ids,
        kept_clusters,
        purged_cluster_ids,
    )


def purge_expired_quality_state(
    state: QualityState,
    *,
    cutoff: datetime,
    retention_days: int,
    actor: ActorContext | None,
    occurred_at: datetime,
) -> tuple[QualityState, dict[str, Any]]:
    (
        kept_candidates,
        purged_candidate_ids,
        kept_cases,
        purged_case_ids,
        kept_clusters,
        purged_cluster_ids,
    ) = partition_purged_quality_records(state, cutoff=cutoff)
    total_purged = (
        len(purged_candidate_ids) + len(purged_case_ids) + len(purged_cluster_ids)
    )
    if total_purged == 0:
        return (
            state.model_copy(update={"revision": state.revision + 1}),
            empty_purge_result(),
        )

    audit = QualityAuditEvent(
        audit_id=str(uuid.uuid4()),
        target_type="QUALITY_CASE",
        target_id="RETENTION_PURGE",
        action="QUALITY_RETENTION_PURGED",
        actor_id=actor.user_id if actor else "system.retention",
        actor_role=actor.role if actor else "SYSTEM",
        owner_unit_id="ALL",
        before={
            "candidate_count": len(state.candidates),
            "case_count": len(state.cases),
            "cluster_count": len(state.clusters),
        },
        after={
            "purged_candidates": purged_candidate_ids,
            "purged_cases": purged_case_ids,
            "purged_clusters": purged_cluster_ids,
        },
        reason=f"Purged {total_purged} quality records past {retention_days} days retention.",
        occurred_at=occurred_at,
    )
    next_state = QualityState(
        revision=state.revision + 1,
        candidates=tuple(kept_candidates),
        cases=tuple(kept_cases),
        clusters=tuple(kept_clusters),
        audits=(*state.audits, audit),
    )
    return next_state, {
        "purged_candidates": len(purged_candidate_ids),
        "purged_cases": len(purged_case_ids),
        "purged_clusters": len(purged_cluster_ids),
        "total": total_purged,
    }
