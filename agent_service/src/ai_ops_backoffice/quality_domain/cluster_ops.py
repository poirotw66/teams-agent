"""Question-cluster listing and correction use-case helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from operations_core.access import ActorContext

from ..faq_domain.errors import FaqAuthorizationError, FaqValidationError
from .case_ops import build_quality_audit
from .clustering import (
    build_corrected_clusters,
    build_generated_clusters,
    group_open_candidates_by_owner_issue,
    require_active_clusters,
    resolve_correction_groups,
)
from .models import QualityState
from .ops_common import authorize
from .repository import QualityRepository

__all__ = [
    "correct_clusters",
    "generate_clusters",
    "list_clusters",
]


def list_clusters(
    repository: QualityRepository,
    *,
    actor: ActorContext,
) -> list[dict[str, Any]]:
    visible = []
    for item in repository.load().clusters:
        try:
            authorize(actor, "ops.quality.read", item.owner_unit_id)
        except FaqAuthorizationError:
            continue
        visible.append(item.model_dump(mode="json"))
    return visible


def generate_clusters(
    repository: QualityRepository,
    *,
    actor: ActorContext,
) -> dict[str, Any]:
    """Group open candidates by owner unit + issue type and question similarity."""

    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        groups = group_open_candidates_by_owner_issue(state.candidates)
        for owner_unit_id, _issue_type_id in groups:
            authorize(actor, "ops.quality.write", owner_unit_id)
        active_keys = {
            item.cluster_key
            for item in state.clusters
            if item.status in {"CANDIDATE", "ACCEPTED"}
        }
        now = datetime.now(UTC)
        created = build_generated_clusters(
            groups=groups,
            active_keys=active_keys,
            actor_user_id=actor.user_id,
            now=now,
        )
        audits = list(state.audits)
        for cluster in created:
            reason = (
                "lexical_similarity_grouping"
                if " #" in cluster.name
                else "owner_unit_issue_type_grouping"
            )
            audits.append(
                build_quality_audit(
                    target_type="QUESTION_CLUSTER",
                    target_id=cluster.cluster_id,
                    action="QUESTION_GROUP_GENERATED",
                    actor=actor,
                    owner_unit_id=cluster.owner_unit_id,
                    before=None,
                    after=cluster,
                    reason=reason,
                )
            )
        next_state = QualityState(
            revision=state.revision + 1,
            candidates=state.candidates,
            cases=state.cases,
            clusters=(*state.clusters, *created),
            audits=tuple(audits),
        )
        return next_state, {
            "items": [item.model_dump(mode="json") for item in created],
            "groupingMethod": "OWNER_UNIT_ISSUE_TYPE",
            "note": "Groups by owner unit and issue type; not semantic clustering.",
        }

    return repository.mutate(operation)


def correct_clusters(
    repository: QualityRepository,
    cluster_ids: tuple[str, ...],
    *,
    action: Literal["RENAME", "ACCEPT", "REJECT", "MERGE", "SPLIT"],
    name: str | None,
    candidate_groups: tuple[tuple[str, ...], ...],
    actor: ActorContext,
) -> dict[str, Any]:
    if not cluster_ids:
        raise FaqValidationError("at least one cluster is required")

    def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
        selected = [item for item in state.clusters if item.cluster_id in cluster_ids]
        owner_unit_id = require_active_clusters(selected, cluster_ids)
        authorize(actor, "ops.quality.write", owner_unit_id)
        groups = resolve_correction_groups(
            action=action,
            selected=selected,
            candidate_groups=candidate_groups,
        )
        now = datetime.now(UTC)
        new_clusters = build_corrected_clusters(
            action=action,
            selected=selected,
            cluster_ids=cluster_ids,
            groups=groups,
            candidates_by_id={item.candidate_id: item for item in state.candidates},
            name=name,
            actor_user_id=actor.user_id,
            now=now,
        )
        superseded = tuple(
            item.model_copy(update={"status": "SUPERSEDED"})
            if item.cluster_id in cluster_ids
            else item
            for item in state.clusters
        )
        audits = list(state.audits)
        for cluster in new_clusters:
            audits.append(
                build_quality_audit(
                    target_type="QUESTION_CLUSTER",
                    target_id=cluster.cluster_id,
                    action=f"QUESTION_CLUSTER_{action}",
                    actor=actor,
                    owner_unit_id=owner_unit_id,
                    before=selected[0] if len(selected) == 1 else None,
                    after=cluster,
                )
            )
        next_state = QualityState(
            revision=state.revision + 1,
            candidates=state.candidates,
            cases=state.cases,
            clusters=(*superseded, *new_clusters),
            audits=tuple(audits),
        )
        return next_state, {
            "items": [item.model_dump(mode="json") for item in new_clusters]
        }

    return repository.mutate(operation)
