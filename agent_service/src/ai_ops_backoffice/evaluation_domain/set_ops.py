"""Eval set and set-version helpers for EvaluationService."""

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
    EvaluationValidationError,
    EvaluationVersionConflictError,
)
from .models import (
    EvalSet,
    EvalSetVersion,
    EvaluationAuditEvent,
    SetPurpose,
    calculate_manifest_hash,
)
from .repository import EvaluationRepository

__all__ = [
    "create_set",
    "create_set_version_draft",
    "get_set_detail",
    "list_sets",
    "publish_set_version",
]


def create_set(
    repo: EvaluationRepository,
    *,
    name: str,
    owner_unit_ids: tuple[str, ...],
    purpose: SetPurpose = "DEVELOPMENT",
    description: str = "",
    actor: ActorContext,
    tenant_id: str | None = None,
    default_tenant_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    for unit in owner_unit_ids:
        authorize(actor, "ops.evals.write", unit)
    if purpose == "HOLDOUT" and not actor.has_capability("ops.evals.holdout.read"):
        raise EvaluationAuthorizationError("Actor lacks capability ops.evals.holdout.read")

    now = datetime.now(UTC)
    set_id = f"eval_set_{uuid.uuid4().hex[:12]}"
    resolved_tenant = tenant_id or actor.tenant_id or default_tenant_id
    eval_set = EvalSet(
        set_id=set_id,
        tenant_id=resolved_tenant,
        owner_unit_ids=owner_unit_ids,
        name=name.strip(),
        description=description.strip(),
        purpose=purpose,
        lead_owner=actor.user_id,
        created_by=actor.user_id,
        created_at=now,
        updated_by=actor.user_id,
        updated_at=now,
        is_active=True,
    )
    state = repo.load()
    new_state = state.model_copy(update={"sets": (*state.sets, eval_set)})
    audit = EvaluationAuditEvent(
        audit_id=str(uuid.uuid4()),
        entity_type="EVAL_SET",
        entity_id=set_id,
        action="CREATE_SET",
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=owner_unit_ids[0] if owner_unit_ids else "ALL",
        tenant_id=resolved_tenant,
        before=None,
        after=eval_set.model_dump(mode="json"),
        reason="Created eval set",
        occurred_at=now,
        correlation_id=correlation_id,
    )
    repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {"eval_set": eval_set.model_dump(mode="json")}


def get_set_detail(repo: EvaluationRepository, set_id: str, *, actor: ActorContext) -> dict[str, Any]:
    authorize(actor, "ops.evals.read")
    eval_set = repo.get_set(set_id)
    if not eval_set:
        raise EvaluationNotFoundError(f"Set {set_id} not found")
    if eval_set.purpose == "HOLDOUT" and not actor.has_capability("ops.evals.holdout.read"):
        raise EvaluationNotFoundError(f"Set {set_id} not found")
    if not any(actor.allows_owner_unit(unit) for unit in eval_set.owner_unit_ids):
        raise EvaluationAuthorizationError("Actor lacks scope for set owner units")
    versions = repo.list_set_versions(set_id)
    return {
        "eval_set": eval_set.model_dump(mode="json"),
        "versions": [version.model_dump(mode="json") for version in versions],
    }


def list_sets(
    repo: EvaluationRepository,
    *,
    actor: ActorContext,
    purpose: SetPurpose | None = None,
) -> list[dict[str, Any]]:
    authorize(actor, "ops.evals.read")
    visible: list[dict[str, Any]] = []
    can_read_holdout = actor.has_capability("ops.evals.holdout.read")
    for eval_set in repo.list_sets():
        if eval_set.purpose == "HOLDOUT" and not can_read_holdout:
            continue
        if purpose and eval_set.purpose != purpose:
            continue
        if not any(actor.allows_owner_unit(unit) for unit in eval_set.owner_unit_ids):
            continue
        visible.append(eval_set.model_dump(mode="json"))
    return visible


def create_set_version_draft(
    repo: EvaluationRepository,
    set_id: str,
    *,
    case_revision_ids: tuple[str, ...],
    actor: ActorContext,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    _ = correlation_id
    eval_set = repo.get_set(set_id)
    if not eval_set:
        raise EvaluationNotFoundError(f"Set {set_id} not found")
    for unit in eval_set.owner_unit_ids:
        authorize(actor, "ops.evals.write", unit)

    all_versions = repo.list_set_versions(set_id)
    next_ver_num = max((version.version for version in all_versions), default=0) + 1
    now = datetime.now(UTC)
    version = EvalSetVersion(
        set_version_id=f"setver_{uuid.uuid4().hex[:12]}",
        set_id=set_id,
        version=next_ver_num,
        case_revision_ids=case_revision_ids,
        coverage_stats={},
        manifest_hash="",
        status="DRAFT",
        published_by=None,
        published_at=None,
        created_by=actor.user_id,
        created_at=now,
        etag=1,
    )
    state = repo.load()
    new_state = state.model_copy(update={"set_versions": (*state.set_versions, version)})
    repo.commit_mutation(new_state, expected_revision=state.revision)
    return {"version": version.model_dump(mode="json")}


def _validate_publishable_revisions(
    repo: EvaluationRepository,
    case_revision_ids: tuple[str, ...],
) -> tuple[list[tuple[str, str]], dict[str, int], dict[str, int]]:
    revision_pairs: list[tuple[str, str]] = []
    by_behavior: dict[str, int] = {}
    by_criticality: dict[str, int] = {}
    for rev_id in case_revision_ids:
        revision = repo.get_revision(rev_id)
        if not revision:
            raise EvaluationValidationError(f"Revision {rev_id} referenced in set does not exist")
        if revision.status != "APPROVED":
            raise EvaluationValidationError(
                f"Revision {rev_id} is in status {revision.status}; "
                "only APPROVED revisions can be published (GE1-A01)"
            )
        if revision.source_health in ("NEEDS_REVIEW", "SOURCE_UNAVAILABLE"):
            raise EvaluationValidationError(
                f"Revision {rev_id} has source health {revision.source_health}; "
                "cannot publish (GE1-A05)"
            )
        revision_pairs.append((revision.revision_id, revision.content_hash))
        by_behavior[revision.behavior] = by_behavior.get(revision.behavior, 0) + 1
        by_criticality[revision.criticality] = by_criticality.get(revision.criticality, 0) + 1
    return revision_pairs, by_behavior, by_criticality


def publish_set_version(
    repo: EvaluationRepository,
    set_version_id: str,
    *,
    expected_etag: int,
    actor: ActorContext,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    version = repo.get_set_version(set_version_id)
    if not version:
        raise EvaluationNotFoundError(f"Set version {set_version_id} not found")
    eval_set = repo.get_set(version.set_id)
    if not eval_set:
        raise EvaluationNotFoundError(f"Eval set {version.set_id} not found")

    authorize(actor, "ops.evals.sets.publish")
    for unit in eval_set.owner_unit_ids:
        authorize(actor, "ops.evals.sets.publish", unit)
    if version.etag != expected_etag:
        raise EvaluationVersionConflictError(f"Etag mismatch: expected {expected_etag}, got {version.etag}")
    if version.status != "DRAFT":
        raise EvaluationTransitionError(f"Cannot publish version in status {version.status}")
    if not version.case_revision_ids:
        raise EvaluationValidationError("Cannot publish an empty eval set version")

    revision_pairs, by_behavior, by_criticality = _validate_publishable_revisions(
        repo, version.case_revision_ids
    )
    manifest_hash = calculate_manifest_hash(revision_pairs)
    coverage_stats = {
        "total_cases": len(version.case_revision_ids),
        "by_behavior": by_behavior,
        "by_criticality": by_criticality,
    }
    now = datetime.now(UTC)
    published_version = version.model_copy(
        update={
            "status": "PUBLISHED",
            "etag": version.etag + 1,
            "manifest_hash": manifest_hash,
            "coverage_stats": coverage_stats,
            "published_by": actor.user_id,
            "published_at": now,
        }
    )
    state = repo.load()
    updated_versions = tuple(
        item if item.set_version_id != set_version_id else published_version for item in state.set_versions
    )
    new_state = state.model_copy(update={"set_versions": updated_versions})
    audit = EvaluationAuditEvent(
        audit_id=str(uuid.uuid4()),
        entity_type="EVAL_SET_VERSION",
        entity_id=set_version_id,
        action="PUBLISH_SET_VERSION",
        actor_id=actor.user_id,
        actor_role=actor.role,
        owner_unit_id=eval_set.owner_unit_ids[0] if eval_set.owner_unit_ids else "ALL",
        tenant_id=eval_set.tenant_id,
        before={"status": "DRAFT", "etag": version.etag},
        after={"status": "PUBLISHED", "manifest_hash": manifest_hash, "etag": published_version.etag},
        reason="Published immutable eval set version",
        occurred_at=now,
        correlation_id=correlation_id,
    )
    repo.commit_mutation(new_state, audit=audit, expected_revision=state.revision)
    return {"version": published_version.model_dump(mode="json")}
