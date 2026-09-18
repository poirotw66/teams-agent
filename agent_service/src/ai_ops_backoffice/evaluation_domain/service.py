"""Evaluation case/set service facade."""

from __future__ import annotations

from typing import Any

from operations_core.access import ActorContext

from . import case_ops, revision_ops, set_ops
from .models import (
    Criticality,
    EvalBehaviorType,
    EvaluationCriteria,
    EvidenceRequirement,
    ProvenanceSourceType,
    ProvenanceSpec,
    SetPurpose,
    ToolConstraintsSpec,
    TurnSpec,
)
from .repository import EvaluationRepository

__all__ = ["EvaluationService"]


class EvaluationService:
    def __init__(self, repository: EvaluationRepository, *, default_tenant_id: str = "local-development") -> None:
        self._repo = repository
        self._default_tenant_id = default_tenant_id

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str | None = None) -> None:
        case_ops.authorize(actor, capability, owner_unit_id)

    @staticmethod
    def _fingerprint(actor: ActorContext, payload: dict[str, Any]) -> str:
        return case_ops.fingerprint(actor, payload)

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
        return case_ops.create_case(
            self._repo,
            title=title,
            query=query,
            owner_unit_id=owner_unit_id,
            behavior=behavior,
            criteria=criteria,
            evidence=evidence,
            turns=turns,
            tool_constraints=tool_constraints,
            tags=tags,
            criticality=criticality,
            provenance=provenance,
            actor=actor,
            tenant_id=tenant_id,
            default_tenant_id=self._default_tenant_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def get_case_detail(self, case_id: str, *, actor: ActorContext) -> dict[str, Any]:
        return case_ops.get_case_detail(self._repo, case_id, actor=actor)

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
        return case_ops.list_cases(
            self._repo,
            actor=actor,
            q=q,
            owner_unit_id=owner_unit_id,
            status=status,
            behavior=behavior,
            tags=tags,
            criticality=criticality,
            source_health=source_health,
            source_type=source_type,
            source_id=source_id,
            limit=limit,
        )

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
        return revision_ops.create_revision(
            self._repo,
            case_id,
            query=query,
            base_revision_id=base_revision_id,
            behavior=behavior,
            criteria=criteria,
            evidence=evidence,
            turns=turns,
            tool_constraints=tool_constraints,
            tags=tags,
            criticality=criticality,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    def submit_revision(
        self,
        revision_id: str,
        *,
        expected_etag: int,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        return revision_ops.submit_revision(
            self._repo,
            revision_id,
            expected_etag=expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )

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
        return revision_ops.review_revision(
            self._repo,
            revision_id,
            approve=approve,
            reason=reason,
            expected_etag=expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )

    def retire_case(
        self,
        case_id: str,
        *,
        reason: str,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        return revision_ops.retire_case(
            self._repo,
            case_id,
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )

    def mark_source_needs_review(
        self,
        *,
        source_type: ProvenanceSourceType,
        source_id: str,
        new_version_id: str,
        actor: ActorContext,
    ) -> list[str]:
        return case_ops.mark_source_needs_review(
            self._repo,
            source_type=source_type,
            source_id=source_id,
            new_version_id=new_version_id,
            actor=actor,
            default_tenant_id=self._default_tenant_id,
        )

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
        return set_ops.create_set(
            self._repo,
            name=name,
            owner_unit_ids=owner_unit_ids,
            purpose=purpose,
            description=description,
            actor=actor,
            tenant_id=tenant_id,
            default_tenant_id=self._default_tenant_id,
            correlation_id=correlation_id,
        )

    def get_set_detail(self, set_id: str, *, actor: ActorContext) -> dict[str, Any]:
        return set_ops.get_set_detail(self._repo, set_id, actor=actor)

    def list_sets(self, *, actor: ActorContext, purpose: SetPurpose | None = None) -> list[dict[str, Any]]:
        return set_ops.list_sets(self._repo, actor=actor, purpose=purpose)

    def create_set_version_draft(
        self,
        set_id: str,
        *,
        case_revision_ids: tuple[str, ...],
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        return set_ops.create_set_version_draft(
            self._repo,
            set_id,
            case_revision_ids=case_revision_ids,
            actor=actor,
            correlation_id=correlation_id,
        )

    def publish_set_version(
        self,
        set_version_id: str,
        *,
        expected_etag: int,
        actor: ActorContext,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        return set_ops.publish_set_version(
            self._repo,
            set_version_id,
            expected_etag=expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )
