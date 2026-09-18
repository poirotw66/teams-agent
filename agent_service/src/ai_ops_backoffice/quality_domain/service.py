"""Quality domain service facade; use-case logic lives in sibling ops modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal

from operations_core.access import ActorContext

from . import candidate_ops, case_lifecycle_ops, cluster_ops
from .case_lifecycle_ops import CASE_TRANSITIONS
from .clustering import cluster_candidates_by_similarity
from .repository import QualityRepository

# Compatibility alias for existing test imports.
_cluster_candidates_by_similarity = cluster_candidates_by_similarity

__all__ = [
    "QualityService",
    "_cluster_candidates_by_similarity",
    "cluster_candidates_by_similarity",
]


class QualityService:
    TRANSITIONS: ClassVar[dict[str, set[str]]] = CASE_TRANSITIONS

    def __init__(self, repository: QualityRepository) -> None:
        self._repository = repository

    def list_candidates(self, *, actor: ActorContext, status: str | None = None) -> list[dict[str, Any]]:
        return candidate_ops.list_candidates(self._repository, actor=actor, status=status)

    def list_cases(
        self,
        *,
        actor: ActorContext,
        status: str | None = None,
        case_type: str | None = None,
        owner_unit_id: str | None = None,
        issue_type_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return case_lifecycle_ops.list_cases(
            self._repository,
            actor=actor,
            status=status,
            case_type=case_type,
            owner_unit_id=owner_unit_id,
            issue_type_id=issue_type_id,
        )

    def case_detail(self, case_id: str, *, actor: ActorContext) -> dict[str, Any]:
        return case_lifecycle_ops.case_detail(self._repository, case_id, actor=actor)

    def list_clusters(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        return cluster_ops.list_clusters(self._repository, actor=actor)

    def add_candidate(
        self,
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
        return candidate_ops.add_candidate(
            self._repository,
            source_type=source_type,
            case_type=case_type,
            title=title,
            description=description,
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
            actor=actor,
        )

    def merge_candidates(
        self,
        candidate_ids: tuple[str, ...],
        *,
        title: str,
        description: str,
        priority: str,
        assignee_id: str | None,
        target_due_at: datetime | None,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return candidate_ops.merge_candidates(
            self._repository,
            candidate_ids,
            title=title,
            description=description,
            priority=priority,
            assignee_id=assignee_id,
            target_due_at=target_due_at,
            actor=actor,
        )

    def update_case(
        self,
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
        return case_lifecycle_ops.update_case(
            self._repository,
            case_id,
            title=title,
            description=description,
            priority=priority,
            assignee_id=assignee_id,
            target_due_at=target_due_at,
            expected_etag=expected_etag,
            actor=actor,
        )

    def transition_case(
        self,
        case_id: str,
        *,
        status: str,
        reason: str | None,
        resolution_type: str | None,
        expected_etag: int,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return case_lifecycle_ops.transition_case(
            self._repository,
            case_id,
            status=status,
            reason=reason,
            resolution_type=resolution_type,
            expected_etag=expected_etag,
            actor=actor,
        )

    def link_content(
        self,
        case_id: str,
        *,
        faq_id: str | None,
        document_id: str | None,
        expected_etag: int,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return case_lifecycle_ops.link_content(
            self._repository,
            case_id,
            faq_id=faq_id,
            document_id=document_id,
            expected_etag=expected_etag,
            actor=actor,
        )

    def observe_faq(
        self,
        faq_id: str,
        *,
        baseline_by_issue: dict[str, dict[str, float]],
        actor: ActorContext,
    ) -> dict[str, Any]:
        return case_lifecycle_ops.observe_faq(
            self._repository,
            faq_id,
            baseline_by_issue=baseline_by_issue,
            actor=actor,
        )

    def record_observation(
        self,
        case_id: str,
        *,
        metrics: dict[str, float],
        expected_etag: int,
        actor: ActorContext,
    ) -> dict[str, Any]:
        return case_lifecycle_ops.record_observation(
            self._repository,
            case_id,
            metrics=metrics,
            expected_etag=expected_etag,
            actor=actor,
        )

    def generate_clusters(self, *, actor: ActorContext) -> dict[str, Any]:
        return cluster_ops.generate_clusters(self._repository, actor=actor)

    def correct_clusters(
        self,
        cluster_ids: tuple[str, ...],
        *,
        action: Literal["RENAME", "ACCEPT", "REJECT", "MERGE", "SPLIT"],
        name: str | None,
        candidate_groups: tuple[tuple[str, ...], ...],
        actor: ActorContext,
    ) -> dict[str, Any]:
        return cluster_ops.correct_clusters(
            self._repository,
            cluster_ids,
            action=action,
            name=name,
            candidate_groups=candidate_groups,
            actor=actor,
        )

    def purge_expired(
        self,
        *,
        retention_days: int = 365,
        actor: ActorContext | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return case_lifecycle_ops.purge_expired(
            self._repository,
            retention_days=retention_days,
            actor=actor,
            now=now,
        )
