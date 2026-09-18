"""Case create/list helpers for EvaluationService."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from operations_core.access import ActorContext

from .errors import (
    EvaluationAuthorizationError,
    EvaluationNotFoundError,
    EvaluationValidationError,
)
from .models import (
    CaseRevision,
    Criticality,
    EvalBehaviorType,
    EvalCase,
    EvaluationAuditEvent,
    EvaluationCriteria,
    EvaluationIdempotencyRecord,
    EvidenceRequirement,
    ProvenanceSourceType,
    ProvenanceSpec,
    ToolConstraintsSpec,
    TurnSpec,
    calculate_revision_content_hash,
)
from .repository import EvaluationRepository

__all__ = [
    "authorize",
    "create_case",
    "fingerprint",
    "get_case_detail",
    "list_cases",
    "mark_source_needs_review",
]

def authorize(actor: ActorContext, capability: str, owner_unit_id: str | None = None) -> None:
    if not actor.has_capability(capability):
        raise EvaluationAuthorizationError(f"Actor lacks capability: {capability}")
    if owner_unit_id and not actor.allows_owner_unit(owner_unit_id):
        raise EvaluationAuthorizationError(f"Actor lacks scope for owner unit: {owner_unit_id}")

def fingerprint(actor: ActorContext, payload: dict[str, Any]) -> str:
    value = {"actor_id": actor.user_id, **payload}
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

def _build_initial_case_entities(
    *,
    title: str,
    query: str,
    owner_unit_id: str,
    behavior: EvalBehaviorType,
    criteria: EvaluationCriteria,
    evidence: tuple[EvidenceRequirement, ...],
    turns: tuple[TurnSpec, ...],
    tool_constraints: ToolConstraintsSpec,
    tags: tuple[str, ...],
    criticality: Criticality,
    provenance: ProvenanceSpec,
    actor: ActorContext,
    tenant_id: str,
    metadata: dict[str, Any],
    now: datetime,
) -> tuple[EvalCase, CaseRevision]:
    case_id = f"case_{uuid.uuid4().hex[:12]}"
    revision_id = f"rev_{uuid.uuid4().hex[:12]}"
    content_hash = calculate_revision_content_hash(
        query=query,
        turns=turns,
        criteria=criteria,
        evidence=evidence,
        behavior=behavior,
        tool_constraints=tool_constraints,
        tags=tags,
        criticality=criticality,
        provenance=provenance,
    )
    revision = CaseRevision(
        revision_id=revision_id,
        case_id=case_id,
        revision_number=1,
        query=query,
        turns=turns,
        criteria=criteria,
        evidence=evidence,
        behavior=behavior,
        tool_constraints=tool_constraints,
        tags=tags,
        criticality=criticality,
        provenance=provenance,
        status="DRAFT",
        source_health="VALID",
        etag=1,
        content_hash=content_hash,
        created_by=actor.user_id,
        created_at=now,
        updated_by=actor.user_id,
        updated_at=now,
    )
    case = EvalCase(
        case_id=case_id,
        tenant_id=tenant_id,
        owner_unit_id=owner_unit_id,
        title=title.strip(),
        current_revision_id=revision_id,
        created_by=actor.user_id,
        created_at=now,
        updated_by=actor.user_id,
        updated_at=now,
        tags=tags,
        metadata=metadata,
    )
    return case, revision

def _commit_created_case(
    repo: EvaluationRepository,
    *,
    case: EvalCase,
    revision: CaseRevision,
    actor: ActorContext,
    owner_unit_id: str,
    tenant_id: str,
    request_fingerprint: str,
    idempotency_key: str | None,
    correlation_id: str | None,
    now: datetime,
) -> dict[str, Any]:
    state = repo.load()
    new_state = state.model_copy(
        update={"cases": (*state.cases, case), "revisions": (*state.revisions, revision)}
    )
    result = {"case": case.model_dump(mode="json"), "revision": revision.model_dump(mode="json")}
    audit = EvaluationAuditEvent(
        audit_id=str(uuid.uuid4()),
        entity_type="EVAL_CASE",
        entity_id=case.case_id,
        action="CREATE_CASE",
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=owner_unit_id,
        tenant_id=tenant_id,
        before=None,
        after=result,
        reason="Created eval case",
        occurred_at=now,
        correlation_id=correlation_id,
    )
    idempotency_rec = (
        EvaluationIdempotencyRecord(
            key=idempotency_key,
            action="CREATE_CASE",
            request_fingerprint=request_fingerprint,
            result=result,
        )
        if idempotency_key
        else None
    )
    repo.commit_mutation(
        new_state,
        audit=audit,
        idempotency_record=idempotency_rec,
        expected_revision=state.revision,
    )
    return result


def create_case(
    repo: EvaluationRepository,
    *,
    title: str,
    query: str,
    owner_unit_id: str,
    behavior: EvalBehaviorType = "ANSWER_WITH_CITATION",
    criteria: EvaluationCriteria | None = None,
    evidence: tuple[EvidenceRequirement, ...] = (),
    turns: tuple[TurnSpec, ...] = (),
    tool_constraints: ToolConstraintsSpec | None = None,
    tags: tuple[str, ...] = (),
    criticality: Criticality = "NORMAL",
    provenance: ProvenanceSpec,
    actor: ActorContext,
    tenant_id: str | None = None,
    default_tenant_id: str,
    metadata: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    authorize(actor, "ops.evals.write", owner_unit_id)
    if not title.strip() or not query.strip():
        raise EvaluationValidationError("Title and query must not be empty")
    resolved_criteria = criteria or EvaluationCriteria()
    resolved_tool_constraints = tool_constraints or ToolConstraintsSpec()
    resolved_tenant_id = tenant_id or actor.tenant_id or default_tenant_id
    request_fingerprint = fingerprint(
        actor,
        {"title": title, "query": query, "owner_unit_id": owner_unit_id, "behavior": behavior},
    )
    replayed = repo.replay_idempotency(idempotency_key, "CREATE_CASE", request_fingerprint)
    if replayed:
        return replayed
    now = datetime.now(UTC)
    case, revision = _build_initial_case_entities(
        title=title,
        query=query,
        owner_unit_id=owner_unit_id,
        behavior=behavior,
        criteria=resolved_criteria,
        evidence=evidence,
        turns=turns,
        tool_constraints=resolved_tool_constraints,
        tags=tags,
        criticality=criticality,
        provenance=provenance,
        actor=actor,
        tenant_id=resolved_tenant_id,
        metadata=metadata or {},
        now=now,
    )
    return _commit_created_case(
        repo,
        case=case,
        revision=revision,
        actor=actor,
        owner_unit_id=owner_unit_id,
        tenant_id=resolved_tenant_id,
        request_fingerprint=request_fingerprint,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        now=now,
    )


def get_case_detail(repo: EvaluationRepository, case_id: str, *, actor: ActorContext) -> dict[str, Any]:
    authorize(actor, "ops.evals.read")
    case = repo.get_case(case_id)
    if not case:
        raise EvaluationNotFoundError(f"Case {case_id} not found")
    authorize(actor, "ops.evals.read", case.owner_unit_id)
    revisions = repo.list_revisions_for_case(case_id)
    current_rev = next((r for r in revisions if r.revision_id == case.current_revision_id), None)
    return {
        "case": case.model_dump(mode="json"),
        "current_revision": current_rev.model_dump(mode="json") if current_rev else None,
        "revisions": [r.model_dump(mode="json") for r in revisions],
    }

def _case_matches_filters(
    case: EvalCase,
    current_rev: CaseRevision,
    *,
    actor: ActorContext,
    q_lower: str | None,
    owner_unit_id: str | None,
    status: str | None,
    behavior: str | None,
    tags: tuple[str, ...] | None,
    criticality: str | None,
    source_health: str | None,
    source_type: ProvenanceSourceType | None,
    source_id: str | None,
) -> bool:
    if not actor.allows_owner_unit(case.owner_unit_id):
        return False
    if owner_unit_id and case.owner_unit_id != owner_unit_id:
        return False
    if source_type and current_rev.provenance.source_type != source_type:
        return False
    if source_id and current_rev.provenance.source_id != source_id:
        return False
    if status and current_rev.status != status:
        return False
    if behavior and current_rev.behavior != behavior:
        return False
    if criticality and current_rev.criticality != criticality:
        return False
    if source_health and current_rev.source_health != source_health:
        return False
    if tags and not all(tag in current_rev.tags for tag in tags):
        return False
    if q_lower:
        in_title = q_lower in case.title.lower()
        in_query = q_lower in current_rev.query.lower()
        if not (in_title or in_query):
            return False
    return True

def list_cases(
    repo: EvaluationRepository,
    *,
    actor: ActorContext,
    q: str | None = None,
    owner_unit_id: str | None = None,
    status: str | None = None,
    behavior: str | None = None,
    tags: tuple[str, ...] | None = None,
    criticality: str | None = None,
    source_health: str | None = None,
    source_type: ProvenanceSourceType | None = None,
    source_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    authorize(actor, "ops.evals.read")
    matched: list[dict[str, Any]] = []
    q_lower = q.lower().strip() if q else None
    for case in repo.list_cases():
        current_rev = repo.get_revision(case.current_revision_id)
        if not current_rev:
            continue
        if not _case_matches_filters(
            case,
            current_rev,
            actor=actor,
            q_lower=q_lower,
            owner_unit_id=owner_unit_id,
            status=status,
            behavior=behavior,
            tags=tags,
            criticality=criticality,
            source_health=source_health,
            source_type=source_type,
            source_id=source_id,
        ):
            continue
        matched.append(
            {
                "case": case.model_dump(mode="json"),
                "current_revision": current_rev.model_dump(mode="json"),
            }
        )
        if len(matched) >= limit:
            break
    return matched

def mark_source_needs_review(
    repo: EvaluationRepository,
    *,
    source_type: ProvenanceSourceType,
    source_id: str,
    new_version_id: str,
    actor: ActorContext,
    default_tenant_id: str,
) -> list[str]:
    """Marks active revisions referencing an updated source as NEEDS_REVIEW."""
    state = repo.load()
    affected_revision_ids: list[str] = []
    updated_revisions = []
    now = datetime.now(UTC)
    for revision in state.revisions:
        is_match = (
            revision.provenance.source_type == source_type
            and revision.provenance.source_id == source_id
            and revision.provenance.source_version_id != new_version_id
            and revision.status in ("DRAFT", "IN_REVIEW", "APPROVED")
        )
        if is_match:
            affected_revision_ids.append(revision.revision_id)
            updated_revisions.append(
                revision.model_copy(update={"source_health": "NEEDS_REVIEW", "updated_at": now})
            )
        else:
            updated_revisions.append(revision)

    if affected_revision_ids:
        new_state = state.model_copy(update={"revisions": tuple(updated_revisions)})
        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="SOURCE_HEALTH",
            entity_id=f"{source_type}:{source_id}",
            action="SOURCE_VERSION_UPDATED",
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id="ALL",
            tenant_id=default_tenant_id,
            before=None,
            after={"affected_revision_ids": affected_revision_ids, "new_version_id": new_version_id},
            reason="Source version changed; marked revisions for review",
            occurred_at=now,
        )
        repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return affected_revision_ids
