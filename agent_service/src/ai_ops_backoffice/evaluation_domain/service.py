from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from agent_service.operations.access import ActorContext

from .errors import (
    EvaluationAuthorizationError,
    EvaluationNotFoundError,
    EvaluationTransitionError,
    EvaluationValidationError,
    EvaluationVersionConflictError,
)
from .models import (
    CaseRevision,
    Criticality,
    EvalBehaviorType,
    EvalCase,
    EvalSet,
    EvalSetVersion,
    EvaluationAuditEvent,
    EvaluationCriteria,
    EvaluationIdempotencyRecord,
    EvidenceRequirement,
    ProvenanceSourceType,
    ProvenanceSpec,
    SetPurpose,
    ToolConstraintsSpec,
    TurnSpec,
    calculate_manifest_hash,
    calculate_revision_content_hash,
)
from .repository import EvaluationRepository


class EvaluationService:
    def __init__(self, repository: EvaluationRepository, *, default_tenant_id: str = "local-development") -> None:
        self._repo = repository
        self._default_tenant_id = default_tenant_id

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str | None = None) -> None:
        if not actor.has_capability(capability):
            raise EvaluationAuthorizationError(f"Actor lacks capability: {capability}")
        if owner_unit_id and not actor.allows_owner_unit(owner_unit_id):
            raise EvaluationAuthorizationError(f"Actor lacks scope for owner unit: {owner_unit_id}")

    @staticmethod
    def _fingerprint(actor: ActorContext, payload: dict[str, Any]) -> str:
        value = {"actor_id": actor.user_id, **payload}
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def create_case(
        self,
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
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        self._authorize(actor, "ops.evals.write", owner_unit_id)
        if not title.strip() or not query.strip():
            raise EvaluationValidationError("Title and query must not be empty")

        resolved_criteria = criteria or EvaluationCriteria()
        resolved_tool_constraints = tool_constraints or ToolConstraintsSpec()
        resolved_tenant_id = tenant_id or actor.tenant_id or self._default_tenant_id

        fingerprint = self._fingerprint(
            actor,
            {
                "title": title,
                "query": query,
                "owner_unit_id": owner_unit_id,
                "behavior": behavior,
            },
        )
        replayed = self._repo.replay_idempotency(idempotency_key, "CREATE_CASE", fingerprint)
        if replayed:
            return replayed

        now = datetime.now(UTC)
        case_id = f"case_{uuid.uuid4().hex[:12]}"
        revision_id = f"rev_{uuid.uuid4().hex[:12]}"

        content_hash = calculate_revision_content_hash(
            query=query,
            turns=turns,
            criteria=resolved_criteria,
            evidence=evidence,
            behavior=behavior,
            tool_constraints=resolved_tool_constraints,
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
            criteria=resolved_criteria,
            evidence=evidence,
            behavior=behavior,
            tool_constraints=resolved_tool_constraints,
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
            tenant_id=resolved_tenant_id,
            owner_unit_id=owner_unit_id,
            title=title.strip(),
            current_revision_id=revision_id,
            created_by=actor.user_id,
            created_at=now,
            updated_by=actor.user_id,
            updated_at=now,
            tags=tags,
            metadata=metadata or {},
        )

        state = self._repo.load()
        new_state = state.model_copy(
            update={
                "cases": (*state.cases, case),
                "revisions": (*state.revisions, revision),
            }
        )

        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="EVAL_CASE",
            entity_id=case_id,
            action="CREATE_CASE",
            actor_id=actor.user_id,
            actor_role=actor.role,
            owner_unit_id=owner_unit_id,
            tenant_id=resolved_tenant_id,
            before=None,
            after={"case": case.model_dump(mode="json"), "revision": revision.model_dump(mode="json")},
            reason="Created eval case",
            occurred_at=now,
            correlation_id=correlation_id,
        )

        result = {"case": case.model_dump(mode="json"), "revision": revision.model_dump(mode="json")}
        idempotency_rec = (
            EvaluationIdempotencyRecord(
                key=idempotency_key,
                action="CREATE_CASE",
                request_fingerprint=fingerprint,
                result=result,
            )
            if idempotency_key
            else None
        )

        self._repo.commit_mutation(new_state, audit=audit, idempotency_record=idempotency_rec)
        return result

    def get_case_detail(self, case_id: str, *, actor: ActorContext) -> dict[str, Any]:
        self._authorize(actor, "ops.evals.read")
        case = self._repo.get_case(case_id)
        if not case:
            raise EvaluationNotFoundError(f"Case {case_id} not found")
        self._authorize(actor, "ops.evals.read", case.owner_unit_id)

        revisions = self._repo.list_revisions_for_case(case_id)
        current_rev = next((r for r in revisions if r.revision_id == case.current_revision_id), None)
        return {
            "case": case.model_dump(mode="json"),
            "current_revision": current_rev.model_dump(mode="json") if current_rev else None,
            "revisions": [r.model_dump(mode="json") for r in revisions],
        }

    def list_cases(
        self,
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
        self._authorize(actor, "ops.evals.read")
        cases = self._repo.list_cases()
        matched: list[dict[str, Any]] = []

        q_lower = q.lower().strip() if q else None
        for case in cases:
            if not actor.allows_owner_unit(case.owner_unit_id):
                continue
            if owner_unit_id and case.owner_unit_id != owner_unit_id:
                continue

            current_rev = self._repo.get_revision(case.current_revision_id)
            if not current_rev:
                continue

            if source_type and current_rev.provenance.source_type != source_type:
                continue
            if source_id and current_rev.provenance.source_id != source_id:
                continue

            if status and current_rev.status != status:
                continue
            if behavior and current_rev.behavior != behavior:
                continue
            if criticality and current_rev.criticality != criticality:
                continue
            if source_health and current_rev.source_health != source_health:
                continue
            if tags and not all(t in current_rev.tags for t in tags):
                continue
            if q_lower:
                in_title = q_lower in case.title.lower()
                in_query = q_lower in current_rev.query.lower()
                if not (in_title or in_query):
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

    def create_revision(
        self,
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
        case = self._repo.get_case(case_id)
        if not case:
            raise EvaluationNotFoundError(f"Case {case_id} not found")
        self._authorize(actor, "ops.evals.write", case.owner_unit_id)

        all_revs = self._repo.list_revisions_for_case(case_id)
        base_rev = next((r for r in all_revs if r.revision_id == (base_revision_id or case.current_revision_id)), None)
        if not base_rev:
            raise EvaluationNotFoundError(f"Base revision not found for case {case_id}")

        next_number = max((r.revision_number for r in all_revs), default=0) + 1
        now = datetime.now(UTC)
        revision_id = f"rev_{uuid.uuid4().hex[:12]}"

        resolved_behavior = behavior or base_rev.behavior
        resolved_criteria = criteria if criteria is not None else base_rev.criteria
        resolved_evidence = evidence if evidence is not None else base_rev.evidence
        resolved_turns = turns if turns is not None else base_rev.turns
        resolved_tool_constraints = tool_constraints if tool_constraints is not None else base_rev.tool_constraints
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

        new_rev = CaseRevision(
            revision_id=revision_id,
            case_id=case_id,
            revision_number=next_number,
            query=query,
            turns=resolved_turns,
            criteria=resolved_criteria,
            evidence=resolved_evidence,
            behavior=resolved_behavior,
            tool_constraints=resolved_tool_constraints,
            tags=resolved_tags,
            criticality=resolved_criticality,
            provenance=base_rev.provenance,
            status="DRAFT",
            source_health="VALID",
            etag=1,
            content_hash=content_hash,
            created_by=actor.user_id,
            created_at=now,
            updated_by=actor.user_id,
            updated_at=now,
        )

        state = self._repo.load()
        new_state = state.model_copy(update={"revisions": (*state.revisions, new_rev)})

        audit = EvaluationAuditEvent(
            audit_id=str(uuid.uuid4()),
            entity_type="CASE_REVISION",
            entity_id=revision_id,
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
        self._repo.commit_mutation(new_state, audit=audit)
        return {"revision": new_rev.model_dump(mode="json")}

    def submit_revision(
        self,
        revision_id: str,
        *,
        expected_etag: int,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        rev = self._repo.get_revision(revision_id)
        if not rev:
            raise EvaluationNotFoundError(f"Revision {revision_id} not found")
        case = self._repo.get_case(rev.case_id)
        if not case:
            raise EvaluationNotFoundError(f"Case {rev.case_id} not found")
        self._authorize(actor, "ops.evals.write", case.owner_unit_id)

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

        state = self._repo.load()
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
        self._repo.commit_mutation(new_state, audit=audit)
        return {"revision": updated_rev.model_dump(mode="json")}

    def review_revision(
        self,
        revision_id: str,
        *,
        approve: bool,
        reason: str,
        expected_etag: int,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        rev = self._repo.get_revision(revision_id)
        if not rev:
            raise EvaluationNotFoundError(f"Revision {revision_id} not found")
        case = self._repo.get_case(rev.case_id)
        if not case:
            raise EvaluationNotFoundError(f"Case {rev.case_id} not found")

        self._authorize(actor, "ops.evals.review", case.owner_unit_id)

        if rev.etag != expected_etag:
            raise EvaluationVersionConflictError(f"Etag mismatch: expected {expected_etag}, got {rev.etag}")
        if rev.status != "IN_REVIEW":
            raise EvaluationTransitionError(f"Cannot review revision in status {rev.status}")

        # Separation of duties check
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

        state = self._repo.load()
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
        self._repo.commit_mutation(new_state, audit=audit)
        return {"revision": updated_rev.model_dump(mode="json")}

    def retire_case(
        self,
        case_id: str,
        *,
        reason: str,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        case = self._repo.get_case(case_id)
        if not case:
            raise EvaluationNotFoundError(f"Case {case_id} not found")
        self._authorize(actor, "ops.evals.write", case.owner_unit_id)

        now = datetime.now(UTC)
        rev = self._repo.get_revision(case.current_revision_id)
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
            state = self._repo.load()
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
            self._repo.commit_mutation(new_state, audit=audit)
        return {"case_id": case_id, "status": "RETIRED"}

    def mark_source_needs_review(
        self,
        *,
        source_type: ProvenanceSourceType,
        source_id: str,
        new_version_id: str,
        actor: ActorContext,
    ) -> list[str]:
        """Marks active revisions referencing an updated source as NEEDS_REVIEW."""
        state = self._repo.load()
        affected_revision_ids: list[str] = []
        updated_revisions = []

        now = datetime.now(UTC)
        for r in state.revisions:
            is_match = (
                r.provenance.source_type == source_type
                and r.provenance.source_id == source_id
                and r.provenance.source_version_id != new_version_id
                and r.status in ("DRAFT", "IN_REVIEW", "APPROVED")
            )
            if is_match:
                affected_revision_ids.append(r.revision_id)
                updated_revisions.append(
                    r.model_copy(update={"source_health": "NEEDS_REVIEW", "updated_at": now})
                )
            else:
                updated_revisions.append(r)

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
                tenant_id=self._default_tenant_id,
                before=None,
                after={"affected_revision_ids": affected_revision_ids, "new_version_id": new_version_id},
                reason="Source version changed; marked revisions for review",
                occurred_at=now,
            )
            self._repo.commit_mutation(new_state, audit=audit)

        return affected_revision_ids

    # --- Sets and SetVersions ---

    def create_set(
        self,
        *,
        name: str,
        owner_unit_ids: tuple[str, ...],
        purpose: SetPurpose = "DEVELOPMENT",
        description: str = "",
        actor: ActorContext,
        tenant_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        for unit in owner_unit_ids:
            self._authorize(actor, "ops.evals.write", unit)

        if purpose == "HOLDOUT" and not actor.has_capability("ops.evals.holdout.read"):
            raise EvaluationAuthorizationError("Actor lacks capability ops.evals.holdout.read")

        now = datetime.now(UTC)
        set_id = f"eval_set_{uuid.uuid4().hex[:12]}"
        resolved_tenant = tenant_id or actor.tenant_id or self._default_tenant_id

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

        state = self._repo.load()
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
        self._repo.commit_mutation(new_state, audit=audit)
        return {"eval_set": eval_set.model_dump(mode="json")}

    def get_set_detail(self, set_id: str, *, actor: ActorContext) -> dict[str, Any]:
        self._authorize(actor, "ops.evals.read")
        eval_set = self._repo.get_set(set_id)
        if not eval_set:
            raise EvaluationNotFoundError(f"Set {set_id} not found")

        if eval_set.purpose == "HOLDOUT" and not actor.has_capability("ops.evals.holdout.read"):
            raise EvaluationNotFoundError(f"Set {set_id} not found")

        if not any(actor.allows_owner_unit(u) for u in eval_set.owner_unit_ids):
            raise EvaluationAuthorizationError("Actor lacks scope for set owner units")

        versions = self._repo.list_set_versions(set_id)
        return {
            "eval_set": eval_set.model_dump(mode="json"),
            "versions": [v.model_dump(mode="json") for v in versions],
        }

    def list_sets(self, *, actor: ActorContext, purpose: SetPurpose | None = None) -> list[dict[str, Any]]:
        self._authorize(actor, "ops.evals.read")
        sets = self._repo.list_sets()
        visible: list[dict[str, Any]] = []

        can_read_holdout = actor.has_capability("ops.evals.holdout.read")
        for s in sets:
            if s.purpose == "HOLDOUT" and not can_read_holdout:
                continue
            if purpose and s.purpose != purpose:
                continue
            if not any(actor.allows_owner_unit(u) for u in s.owner_unit_ids):
                continue
            visible.append(s.model_dump(mode="json"))

        return visible

    def create_set_version_draft(
        self,
        set_id: str,
        *,
        case_revision_ids: tuple[str, ...],
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        eval_set = self._repo.get_set(set_id)
        if not eval_set:
            raise EvaluationNotFoundError(f"Set {set_id} not found")
        for unit in eval_set.owner_unit_ids:
            self._authorize(actor, "ops.evals.write", unit)

        all_versions = self._repo.list_set_versions(set_id)
        next_ver_num = max((v.version for v in all_versions), default=0) + 1

        now = datetime.now(UTC)
        set_ver_id = f"setver_{uuid.uuid4().hex[:12]}"

        version = EvalSetVersion(
            set_version_id=set_ver_id,
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

        state = self._repo.load()
        new_state = state.model_copy(update={"set_versions": (*state.set_versions, version)})
        self._repo.commit_mutation(new_state)
        return {"version": version.model_dump(mode="json")}

    def publish_set_version(
        self,
        set_version_id: str,
        *,
        expected_etag: int,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        version = self._repo.get_set_version(set_version_id)
        if not version:
            raise EvaluationNotFoundError(f"Set version {set_version_id} not found")

        eval_set = self._repo.get_set(version.set_id)
        if not eval_set:
            raise EvaluationNotFoundError(f"Eval set {version.set_id} not found")

        # Must have publish capability and scope
        self._authorize(actor, "ops.evals.sets.publish")
        for unit in eval_set.owner_unit_ids:
            self._authorize(actor, "ops.evals.sets.publish", unit)

        if version.etag != expected_etag:
            raise EvaluationVersionConflictError(f"Etag mismatch: expected {expected_etag}, got {version.etag}")
        if version.status != "DRAFT":
            raise EvaluationTransitionError(f"Cannot publish version in status {version.status}")
        if not version.case_revision_ids:
            raise EvaluationValidationError("Cannot publish an empty eval set version")

        # Validate all member revisions
        revision_pairs: list[tuple[str, str]] = []
        by_behavior: dict[str, int] = {}
        by_criticality: dict[str, int] = {}
        for rev_id in version.case_revision_ids:
            rev = self._repo.get_revision(rev_id)
            if not rev:
                raise EvaluationValidationError(f"Revision {rev_id} referenced in set does not exist")
            if rev.status != "APPROVED":
                raise EvaluationValidationError(
                    f"Revision {rev_id} is in status {rev.status}; only APPROVED revisions can be published (GE1-A01)"
                )
            if rev.source_health in ("NEEDS_REVIEW", "SOURCE_UNAVAILABLE"):
                raise EvaluationValidationError(
                    f"Revision {rev_id} has source health {rev.source_health}; cannot publish (GE1-A05)"
                )
            revision_pairs.append((rev.revision_id, rev.content_hash))
            by_behavior[rev.behavior] = by_behavior.get(rev.behavior, 0) + 1
            by_criticality[rev.criticality] = by_criticality.get(rev.criticality, 0) + 1

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

        state = self._repo.load()
        updated_versions = tuple(
            v if v.set_version_id != set_version_id else published_version for v in state.set_versions
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
        self._repo.commit_mutation(new_state, audit=audit)
        return {"version": published_version.model_dump(mode="json")}
