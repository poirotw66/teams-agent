"""Quality case query and lifecycle mutation use-case helpers."""

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
    FaqVersionConflictError,
)
from .case_ops import (
    TERMINAL_CASE_STATUSES,
    apply_case_status_update,
    build_quality_audit,
    empty_purge_result,
    purge_expired_quality_state,
    quality_has_expired_records,
    quality_retention_cutoff,
)
from .models import QualityCase, QualityState
from .ops_common import authorize
from .repository import QualityRepository

__all__ = [
    "CASE_TRANSITIONS",
    "case_detail",
    "link_content",
    "list_cases",
    "observe_faq",
    "purge_expired",
    "record_observation",
    "transition_case",
    "update_case",
]


CASE_TRANSITIONS: dict[str, set[str]] = {
    "NEW": {"TRIAGED", "WONT_FIX", "DUPLICATE"},
    "TRIAGED": {"IN_PROGRESS", "WONT_FIX", "DUPLICATE"},
    "IN_PROGRESS": {"WAITING_REVIEW", "OBSERVING", "WONT_FIX", "DUPLICATE"},
    "WAITING_REVIEW": {"IN_PROGRESS", "OBSERVING", "WONT_FIX"},
    "OBSERVING": {"IN_PROGRESS", "RESOLVED", "WONT_FIX"},
    "RESOLVED": set(),
    "WONT_FIX": set(),
    "DUPLICATE": set(),
}


def list_cases(
    repository: QualityRepository,
    *,
    actor: ActorContext,
    status: str | None = None,
    case_type: str | None = None,
    owner_unit_id: str | None = None,
    issue_type_id: str | None = None,
) -> list[dict[str, Any]]:
    visible = []
    for item in repository.load().cases:
        try:
            authorize(actor, "ops.quality.read", item.owner_unit_id)
        except FaqAuthorizationError:
            continue
        if status and item.status != status:
            continue
        if case_type and item.case_type != case_type:
            continue
        if owner_unit_id and item.owner_unit_id != owner_unit_id:
            continue
        if issue_type_id and item.issue_type_id != issue_type_id:
            continue
        visible.append(item.model_dump(mode="json"))
    return visible


def case_detail(
    repository: QualityRepository,
    case_id: str,
    *,
    actor: ActorContext,
) -> dict[str, Any]:
    state = repository.load()
    case = next((item for item in state.cases if item.case_id == case_id), None)
    if case is None:
        raise FaqNotFoundError(case_id)
    authorize(actor, "ops.quality.read", case.owner_unit_id)
    return {
        "case": case.model_dump(mode="json"),
        "audit": [
            item.model_dump(mode="json")
            for item in state.audits
            if item.target_type == "QUALITY_CASE" and item.target_id == case_id
        ],
    }


def update_case(
    repository: QualityRepository,
    case_id: str,
    *,
    title: str,
    description: str,
    priority: str,
    assignee_id: str | None,
    target_due_at: datetime | None,
    expected_etag: int,
    actor: ActorContext,
) -> dict[str, Any]:
    return _change_case(
        repository,
        case_id,
        expected_etag=expected_etag,
        actor=actor,
        action="QUALITY_CASE_UPDATED",
        capability="ops.quality.write",
        reason=None,
        changes={
            "title": title,
            "description": mask_text(description).text,
            "priority": priority,
            "assignee_id": assignee_id,
            "target_due_at": target_due_at,
        },
    )


def transition_case(
    repository: QualityRepository,
    case_id: str,
    *,
    status: str,
    reason: str | None,
    resolution_type: str | None,
    expected_etag: int,
    actor: ActorContext,
) -> dict[str, Any]:
    terminal = status in TERMINAL_CASE_STATUSES
    if terminal and not (reason or "").strip():
        raise FaqValidationError("terminal quality case transitions require a reason")
    return _change_case(
        repository,
        case_id,
        expected_etag=expected_etag,
        actor=actor,
        action=f"QUALITY_CASE_{status}",
        capability="ops.quality.resolve" if terminal else "ops.quality.write",
        reason=reason,
        status=status,
        resolution_type=resolution_type if terminal else None,
    )


def link_content(
    repository: QualityRepository,
    case_id: str,
    *,
    faq_id: str | None,
    document_id: str | None,
    expected_etag: int,
    actor: ActorContext,
) -> dict[str, Any]:
    if not faq_id and not document_id:
        raise FaqValidationError("a FAQ or document reference is required")

    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        current = next((item for item in state.cases if item.case_id == case_id), None)
        if current is None:
            raise FaqNotFoundError(case_id)
        authorize(actor, "ops.quality.write", current.owner_unit_id)
        if current.etag != expected_etag:
            raise FaqVersionConflictError("quality case was changed by another request")
        updated = current.model_copy(
            update={
                "faq_ids": tuple(dict.fromkeys((*current.faq_ids, *((faq_id,) if faq_id else ())))),
                "document_ids": tuple(
                    dict.fromkeys((*current.document_ids, *((document_id,) if document_id else ())))
                ),
                "etag": current.etag + 1,
                "updated_by": actor.user_id,
                "updated_at": datetime.now(UTC),
            }
        )
        cases = tuple(updated if item.case_id == case_id else item for item in state.cases)
        audit = build_quality_audit(
            target_type="QUALITY_CASE",
            target_id=case_id,
            action="QUALITY_CASE_CONTENT_LINKED",
            actor=actor,
            owner_unit_id=current.owner_unit_id,
            before=current,
            after=updated,
        )
        return QualityState(
            revision=state.revision + 1,
            candidates=state.candidates,
            cases=cases,
            clusters=state.clusters,
            audits=(*state.audits, audit),
        ), {"case": updated.model_dump(mode="json")}

    return repository.mutate(operation)


def observe_faq(
    repository: QualityRepository,
    faq_id: str,
    *,
    baseline_by_issue: dict[str, dict[str, float]],
    actor: ActorContext,
) -> dict[str, Any]:
    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        now = datetime.now(UTC)
        changed: dict[str, QualityCase] = {}
        audits = list(state.audits)
        for current in state.cases:
            if faq_id not in current.faq_ids or current.status not in {
                "IN_PROGRESS",
                "WAITING_REVIEW",
            }:
                continue
            authorize(actor, "ops.quality.write", current.owner_unit_id)
            baseline = baseline_by_issue.get(current.issue_type_id or "", {})
            updated = current.model_copy(
                update={
                    "status": "OBSERVING",
                    "observation_started_at": now,
                    "observation_baseline": baseline,
                    "observation_latest": baseline,
                    "etag": current.etag + 1,
                    "updated_by": actor.user_id,
                    "updated_at": now,
                }
            )
            changed[current.case_id] = updated
            audits.append(
                build_quality_audit(
                    target_type="QUALITY_CASE",
                    target_id=current.case_id,
                    action="QUALITY_CASE_OBSERVING",
                    actor=actor,
                    owner_unit_id=current.owner_unit_id,
                    before=current,
                    after=updated,
                    reason=f"FAQ activated: {faq_id}",
                )
            )
        return QualityState(
            revision=state.revision + 1,
            candidates=state.candidates,
            cases=tuple(changed.get(item.case_id, item) for item in state.cases),
            clusters=state.clusters,
            audits=tuple(audits),
        ), {"items": [item.model_dump(mode="json") for item in changed.values()]}

    return repository.mutate(operation)


def record_observation(
    repository: QualityRepository,
    case_id: str,
    *,
    metrics: dict[str, float],
    expected_etag: int,
    actor: ActorContext,
) -> dict[str, Any]:
    current = case_detail(repository, case_id, actor=actor)["case"]
    if current["status"] != "OBSERVING":
        raise FaqTransitionError("observation metrics require an OBSERVING case")
    return _change_case(
        repository,
        case_id,
        expected_etag=expected_etag,
        actor=actor,
        action="QUALITY_CASE_OBSERVATION_RECORDED",
        capability="ops.quality.write",
        reason=None,
        changes={"observation_latest": metrics},
    )


def _change_case(
    repository: QualityRepository,
    case_id: str,
    *,
    expected_etag: int,
    actor: ActorContext,
    action: str,
    capability: str,
    reason: str | None,
    status: str | None = None,
    resolution_type: str | None = None,
    changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        current = next((item for item in state.cases if item.case_id == case_id), None)
        if current is None:
            raise FaqNotFoundError(case_id)
        authorize(actor, capability, current.owner_unit_id)
        if current.etag != expected_etag:
            raise FaqVersionConflictError("quality case was changed by another request")
        if status is not None and status not in CASE_TRANSITIONS[current.status]:
            raise FaqTransitionError(
                f"invalid quality case transition: {current.status} -> {status}"
            )
        now = datetime.now(UTC)
        updated = apply_case_status_update(
            current,
            status=status,
            resolution_type=resolution_type,
            reason=reason,
            changes=changes,
            actor=actor,
            now=now,
        )
        cases = tuple(updated if item.case_id == case_id else item for item in state.cases)
        audit = build_quality_audit(
            target_type="QUALITY_CASE",
            target_id=case_id,
            action=action,
            actor=actor,
            owner_unit_id=current.owner_unit_id,
            before=current,
            after=updated,
            reason=reason,
        )
        next_state = QualityState(
            revision=state.revision + 1,
            candidates=state.candidates,
            cases=cases,
            clusters=state.clusters,
            audits=(*state.audits, audit),
        )
        return next_state, {"case": updated.model_dump(mode="json")}

    return repository.mutate(operation)


def purge_expired(
    repository: QualityRepository,
    *,
    retention_days: int = 365,
    actor: ActorContext | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    target_now = now or datetime.now(UTC)
    cutoff = quality_retention_cutoff(retention_days=retention_days, now=target_now)
    current = repository.load()
    if not quality_has_expired_records(current, cutoff=cutoff):
        return empty_purge_result()

    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        return purge_expired_quality_state(
            state,
            cutoff=cutoff,
            retention_days=retention_days,
            actor=actor,
            occurred_at=target_now,
        )

    return repository.mutate(operation)
