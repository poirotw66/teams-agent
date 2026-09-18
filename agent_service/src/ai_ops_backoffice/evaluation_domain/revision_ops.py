"""Revision lifecycle helpers for EvaluationService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from operations_core.access import ActorContext

from .case_ops import authorize
from .errors import (
    EvaluationAuthorizationError,
    EvaluationNotFoundError,
    EvaluationTransitionError,
    EvaluationVersionConflictError,
)
from .models import (
    CaseRevision,
    Criticality,
    EvalBehaviorType,
    EvaluationAuditEvent,
    EvaluationCriteria,
    EvidenceRequirement,
    ToolConstraintsSpec,
    TurnSpec,
    calculate_revision_content_hash,
)
from .repository import EvaluationRepository

__all__ = [
    "create_revision",
    "retire_case",
    "review_revision",
    "submit_revision",
]

def _resolve_revision_fields(
    base_rev: CaseRevision,
    *,
    query: str,
    behavior: EvalBehaviorType | None,
    criteria: EvaluationCriteria | None,
    evidence: tuple[EvidenceRequirement, ...] | None,
    turns: tuple[TurnSpec, ...] | None,
    tool_constraints: ToolConstraintsSpec | None,
    tags: tuple[str, ...] | None,
    criticality: Criticality | None,
) -> dict[str, Any]:
    resolved_behavior = behavior or base_rev.behavior
    resolved_criteria = criteria if criteria is not None else base_rev.criteria
    resolved_evidence = evidence if evidence is not None else base_rev.evidence
    resolved_turns = turns if turns is not None else base_rev.turns
    resolved_tool_constraints = (
        tool_constraints if tool_constraints is not None else base_rev.tool_constraints
    )
    resolved_tags = tags if tags is not None else base_rev.tags
    resolved_criticality = criticality or base_rev.criticality
    content_hash = calculate_revision_content_hash(
        query=query,
        turns=resolved_turns,
        criteria=resolved_criteria,
        evidence=resolved_evidence,
        behavior=resolved_behavior,
        tool_constraints=resolved_tool_constraints,
        tags=resolved_tags,
        criticality=resolved_criticality,
        provenance=base_rev.provenance,
    )
    return {
        "query": query,
        "turns": resolved_turns,
        "criteria": resolved_criteria,
        "evidence": resolved_evidence,
        "behavior": resolved_behavior,
        "tool_constraints": resolved_tool_constraints,
        "tags": resolved_tags,
        "criticality": resolved_criticality,
        "provenance": base_rev.provenance,
        "content_hash": content_hash,
    }

def create_revision(
    repo: EvaluationRepository,
    case_id: str,
    *,
    query: str,
    base_revision_id: str | None = None,
    behavior: EvalBehaviorType | None = None,
    criteria: EvaluationCriteria | None = None,
    evidence: tuple[EvidenceRequirement, ...] | None = None,
    turns: tuple[TurnSpec, ...] | None = None,
    tool_constraints: ToolConstraintsSpec | None = None,
    tags: tuple[str, ...] | None = None,
    criticality: Criticality | None = None,
    actor: ActorContext,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    _ = idempotency_key
    case = repo.get_case(case_id)
    if not case:
        raise EvaluationNotFoundError(f"Case {case_id} not found")
    authorize(actor, "ops.evals.write", case.owner_unit_id)

    all_revs = repo.list_revisions_for_case(case_id)
    base_rev = next((r for r in all_revs if r.revision_id == (base_revision_id or case.current_revision_id)), None)
    if not base_rev:
        raise EvaluationNotFoundError(f"Base revision not found for case {case_id}")

    fields = _resolve_revision_fields(
        base_rev,
        query=query,
        behavior=behavior,
        criteria=criteria,
        evidence=evidence,
        turns=turns,
        tool_constraints=tool_constraints,
        tags=tags,
        criticality=criticality,
    )
    now = datetime.now(UTC)
    next_number = max((r.revision_number for r in all_revs), default=0) + 1
    new_rev = CaseRevision(
        revision_id=f"rev_{uuid.uuid4().hex[:12]}",
        case_id=case_id,
        revision_number=next_number,
        status="DRAFT",
        source_health="VALID",
        etag=1,
        created_by=actor.user_id,
        created_at=now,
        updated_by=actor.user_id,
        updated_at=now,
        **fields,
    )
    state = repo.load()
    new_state = state.model_copy(update={"revisions": (*state.revisions, new_rev)})
    audit = EvaluationAuditEvent(
        audit_id=str(uuid.uuid4()),
        entity_type="CASE_REVISION",
        entity_id=new_rev.revision_id,
        action="CREATE_REVISION",
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=case.owner_unit_id,
        tenant_id=case.tenant_id,
        before={"revision_id": base_rev.revision_id, "status": base_rev.status},
        after=new_rev.model_dump(mode="json"),
        reason=f"Created revision {next_number}",
        occurred_at=now,
        correlation_id=correlation_id,
    )
    repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {"revision": new_rev.model_dump(mode="json")}

def submit_revision(
    repo: EvaluationRepository,
    revision_id: str,
    *,
    expected_etag: int,
    actor: ActorContext,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    rev = repo.get_revision(revision_id)
    if not rev:
        raise EvaluationNotFoundError(f"Revision {revision_id} not found")
    case = repo.get_case(rev.case_id)
    if not case:
        raise EvaluationNotFoundError(f"Case {rev.case_id} not found")
    authorize(actor, "ops.evals.write", case.owner_unit_id)
    if rev.etag != expected_etag:
        raise EvaluationVersionConflictError(f"Etag mismatch: expected {expected_etag}, got {rev.etag}")
    if rev.status not in ("DRAFT", "REJECTED"):
        raise EvaluationTransitionError(f"Cannot submit revision with status {rev.status}")

    now = datetime.now(UTC)
    updated_rev = rev.model_copy(
        update={
            "status": "IN_REVIEW",
            "etag": rev.etag + 1,
            "updated_by": actor.user_id,
            "updated_at": now,
        }
    )
    state = repo.load()
    updated_revisions = tuple(r if r.revision_id != revision_id else updated_rev for r in state.revisions)
    new_state = state.model_copy(update={"revisions": updated_revisions})
    audit = EvaluationAuditEvent(
        audit_id=str(uuid.uuid4()),
        entity_type="CASE_REVISION",
        entity_id=revision_id,
        action="SUBMIT_REVISION",
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=case.owner_unit_id,
        tenant_id=case.tenant_id,
        before={"status": rev.status, "etag": rev.etag},
        after={"status": "IN_REVIEW", "etag": updated_rev.etag},
        reason="Submitted for review",
        occurred_at=now,
        correlation_id=correlation_id,
    )
    repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {"revision": updated_rev.model_dump(mode="json")}

def review_revision(
    repo: EvaluationRepository,
    revision_id: str,
    *,
    approve: bool,
    reason: str,
    expected_etag: int,
    actor: ActorContext,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    rev = repo.get_revision(revision_id)
    if not rev:
        raise EvaluationNotFoundError(f"Revision {revision_id} not found")
    case = repo.get_case(rev.case_id)
    if not case:
        raise EvaluationNotFoundError(f"Case {rev.case_id} not found")
    authorize(actor, "ops.evals.review", case.owner_unit_id)
    if rev.etag != expected_etag:
        raise EvaluationVersionConflictError(f"Etag mismatch: expected {expected_etag}, got {rev.etag}")
    if rev.status != "IN_REVIEW":
        raise EvaluationTransitionError(f"Cannot review revision in status {rev.status}")
    if approve and rev.created_by == actor.user_id:
        raise EvaluationAuthorizationError("Authors cannot approve their own revisions")

    now = datetime.now(UTC)
    new_status = "APPROVED" if approve else "REJECTED"
    updated_rev = rev.model_copy(
        update={
            "status": new_status,
            "etag": rev.etag + 1,
            "reviewed_by": actor.user_id,
            "reviewed_at": now,
            "review_reason": reason,
            "updated_by": actor.user_id,
            "updated_at": now,
        }
    )
    state = repo.load()
    updated_revisions = tuple(r if r.revision_id != revision_id else updated_rev for r in state.revisions)
    updated_cases = state.cases
    if approve:
        updated_case = case.model_copy(
            update={"current_revision_id": revision_id, "updated_by": actor.user_id, "updated_at": now}
        )
        updated_cases = tuple(c if c.case_id != case.case_id else updated_case for c in state.cases)
    new_state = state.model_copy(update={"revisions": updated_revisions, "cases": updated_cases})
    audit = EvaluationAuditEvent(
        audit_id=str(uuid.uuid4()),
        entity_type="CASE_REVISION",
        entity_id=revision_id,
        action="APPROVE_REVISION" if approve else "REJECT_REVISION",
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=case.owner_unit_id,
        tenant_id=case.tenant_id,
        before={"status": rev.status, "etag": rev.etag},
        after={"status": new_status, "etag": updated_rev.etag, "reviewed_by": actor.user_id},
        reason=reason,
        occurred_at=now,
        correlation_id=correlation_id,
    )
    repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {"revision": updated_rev.model_dump(mode="json")}

def retire_case(
    repo: EvaluationRepository,
    case_id: str,
    *,
    reason: str,
    actor: ActorContext,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    case = repo.get_case(case_id)
    if not case:
        raise EvaluationNotFoundError(f"Case {case_id} not found")
    authorize(actor, "ops.evals.write", case.owner_unit_id)
    now = datetime.now(UTC)
    rev = repo.get_revision(case.current_revision_id)
    if rev and rev.status != "RETIRED":
        updated_rev = rev.model_copy(
            update={
                "status": "RETIRED",
                "etag": rev.etag + 1,
                "retired_by": actor.user_id,
                "retired_at": now,
                "updated_by": actor.user_id,
                "updated_at": now,
            }
        )
        state = repo.load()
        updated_revisions = tuple(r if r.revision_id != rev.revision_id else updated_rev for r in state.revisions)
        new_state = state.model_copy(update={"revisions": updated_revisions})
        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="EVAL_CASE",
            entity_id=case_id,
            action="RETIRE_CASE",
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id=case.owner_unit_id,
            tenant_id=case.tenant_id,
            before={"current_revision_id": case.current_revision_id, "status": rev.status},
            after={"status": "RETIRED", "retired_by": actor.user_id},
            reason=reason,
            occurred_at=now,
            correlation_id=correlation_id,
        )
        repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {"case_id": case_id, "status": "RETIRED"}
