from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

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
    build_case_from_candidates,
    build_quality_audit,
    candidate_identity_hash,
    empty_purge_result,
    find_associated_active_case,
    purge_expired_quality_state,
    quality_has_expired_records,
    quality_retention_cutoff,
)
from .clustering import (
    build_corrected_clusters,
    build_generated_clusters,
    cluster_candidates_by_similarity,
    group_open_candidates_by_owner_issue,
    require_active_clusters,
    resolve_correction_groups,
)
from .models import *  # noqa: F403
from .repository import *  # noqa: F403

# Compatibility alias for existing test imports.
_cluster_candidates_by_similarity = cluster_candidates_by_similarity

__all__ = [
    "QualityService",
    "_cluster_candidates_by_similarity",
    "cluster_candidates_by_similarity",
]


class QualityService:
    TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        "NEW": {"TRIAGED", "WONT_FIX", "DUPLICATE"},
        "TRIAGED": {"IN_PROGRESS", "WONT_FIX", "DUPLICATE"},
        "IN_PROGRESS": {"WAITING_REVIEW", "OBSERVING", "WONT_FIX", "DUPLICATE"},
        "WAITING_REVIEW": {"IN_PROGRESS", "OBSERVING", "WONT_FIX"},
        "OBSERVING": {"IN_PROGRESS", "RESOLVED", "WONT_FIX"},
        "RESOLVED": set(),
        "WONT_FIX": set(),
        "DUPLICATE": set(),
    }

    def __init__(self, repository: QualityRepository) -> None:
        self._repository = repository

    @staticmethod
    def _authorize(actor: ActorContext, capability: str, owner_unit_id: str) -> None:
        if not actor.has_capability(capability) or not actor.allows_owner_unit(owner_unit_id):
            raise FaqAuthorizationError("quality operation is outside actor capability or scope")

    @staticmethod
    def _audit(
        *,
        target_type: Literal["QUALITY_CANDIDATE", "QUALITY_CASE", "QUESTION_CLUSTER"],
        target_id: str,
        action: str,
        actor: ActorContext,
        owner_unit_id: str,
        before: Any,
        after: Any,
        reason: str | None = None,
    ) -> QualityAuditEvent:
        return build_quality_audit(
            target_type=target_type,
            target_id=target_id,
            action=action,
            actor=actor,
            owner_unit_id=owner_unit_id,
            before=before,
            after=after,
            reason=reason,
        )

    def list_candidates(self, *, actor: ActorContext, status: str | None = None) -> list[dict[str, Any]]:
        visible = []
        for item in self._repository.load().candidates:
            try:
                self._authorize(actor, "ops.quality.read", item.owner_unit_id)
            except FaqAuthorizationError:
                continue
            if status and item.status != status:
                continue
            visible.append(item.model_dump(mode="json"))
        return visible

    def list_cases(
        self,
        *,
        actor: ActorContext,
        status: str | None = None,
        case_type: str | None = None,
        owner_unit_id: str | None = None,
        issue_type_id: str | None = None,
    ) -> list[dict[str, Any]]:
        visible = []
        for item in self._repository.load().cases:
            try:
                self._authorize(actor, "ops.quality.read", item.owner_unit_id)
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

    def case_detail(self, case_id: str, *, actor: ActorContext) -> dict[str, Any]:
        state = self._repository.load()
        case = next((item for item in state.cases if item.case_id == case_id), None)
        if case is None:
            raise FaqNotFoundError(case_id)
        self._authorize(actor, "ops.quality.read", case.owner_unit_id)
        return {
            "case": case.model_dump(mode="json"),
            "audit": [
                item.model_dump(mode="json")
                for item in state.audits
                if item.target_type == "QUALITY_CASE" and item.target_id == case_id
            ],
        }

    def list_clusters(self, *, actor: ActorContext) -> list[dict[str, Any]]:
        visible = []
        for item in self._repository.load().clusters:
            try:
                self._authorize(actor, "ops.quality.read", item.owner_unit_id)
            except FaqAuthorizationError:
                continue
            visible.append(item.model_dump(mode="json"))
        return visible

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
        self._authorize(actor, "ops.quality.write", owner_unit_id)
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
            return self._insert_candidate(
                state,
                candidate=candidate,
                conversation_refs=conversation_refs,
                source_event_ids=source_event_ids,
                actor=actor,
                owner_unit_id=owner_unit_id,
            )

        return self._repository.mutate(operation)

    def _insert_candidate(
        self,
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
        audit = self._audit(
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
            self._authorize(actor, "ops.quality.write", owner_unit_id)
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
            audit = self._audit(
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

        return self._repository.mutate(operation)

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
        return self._change_case(
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
        self,
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
        return self._change_case(
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
        self,
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
            self._authorize(actor, "ops.quality.write", current.owner_unit_id)
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
            audit = self._audit(
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

        return self._repository.mutate(operation)

    def observe_faq(
        self,
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
                self._authorize(actor, "ops.quality.write", current.owner_unit_id)
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
                    self._audit(
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

        return self._repository.mutate(operation)

    def record_observation(
        self,
        case_id: str,
        *,
        metrics: dict[str, float],
        expected_etag: int,
        actor: ActorContext,
    ) -> dict[str, Any]:
        current = self.case_detail(case_id, actor=actor)["case"]
        if current["status"] != "OBSERVING":
            raise FaqTransitionError("observation metrics require an OBSERVING case")
        return self._change_case(
            case_id,
            expected_etag=expected_etag,
            actor=actor,
            action="QUALITY_CASE_OBSERVATION_RECORDED",
            capability="ops.quality.write",
            reason=None,
            changes={"observation_latest": metrics},
        )

    def _change_case(
        self,
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
            self._authorize(actor, capability, current.owner_unit_id)
            if current.etag != expected_etag:
                raise FaqVersionConflictError("quality case was changed by another request")
            if status is not None and status not in self.TRANSITIONS[current.status]:
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
            audit = self._audit(
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

        return self._repository.mutate(operation)

    def generate_clusters(self, *, actor: ActorContext) -> dict[str, Any]:
        """Group open candidates by owner unit + issue type and question similarity."""

        def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
            groups = group_open_candidates_by_owner_issue(state.candidates)
            for owner_unit_id, _issue_type_id in groups:
                self._authorize(actor, "ops.quality.write", owner_unit_id)
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
                    self._audit(
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

        return self._repository.mutate(operation)

    def correct_clusters(
        self,
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
            self._authorize(actor, "ops.quality.write", owner_unit_id)
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
                    self._audit(
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

        return self._repository.mutate(operation)

    def purge_expired(
        self,
        *,
        retention_days: int = 365,
        actor: ActorContext | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        target_now = now or datetime.now(UTC)
        cutoff = quality_retention_cutoff(retention_days=retention_days, now=target_now)
        current = self._repository.load()
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

        return self._repository.mutate(operation)
