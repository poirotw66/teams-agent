from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext
from agent_service.operations.masking import mask_text, redact_secrets

from ..faq_domain.errors import (
    FaqAuthorizationError,
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
    FaqVersionConflictError,
)


from .models import *  # noqa: F403
from .repository import *  # noqa: F403


def _cluster_candidates_by_similarity(
    candidates: list[QualityCandidate],
) -> list[list[QualityCandidate]]:
    """Cluster candidates based on normalized token overlap of their question texts."""
    if len(candidates) <= 1:
        return [candidates]

    def tokenize(text: str) -> set[str]:
        tokens = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
        cjk_chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
        tokens.update(cjk_chars)
        for i in range(len(cjk_chars) - 1):
            tokens.add(cjk_chars[i] + cjk_chars[i + 1])
        return {t for t in tokens if len(t) > 1 or ("\u4e00" <= t <= "\u9fff")}

    clusters: list[list[QualityCandidate]] = []
    cluster_tokens: list[set[str]] = []

    for candidate in candidates:
        text = f"{candidate.title} {candidate.description}"
        cand_tokens = tokenize(text)
        assigned = False
        for idx, c_tokens in enumerate(cluster_tokens):
            intersection = cand_tokens & c_tokens
            union = cand_tokens | c_tokens
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard >= 0.3 or len(intersection) >= 2:
                clusters[idx].append(candidate)
                cluster_tokens[idx].update(cand_tokens)
                assigned = True
                break
        if not assigned:
            clusters.append([candidate])
            cluster_tokens.append(set(cand_tokens))

    return clusters


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
        identity = "|".join(
            [source_type, case_type, issue_type_id or "", *sorted(source_event_ids)]
        )
        candidate_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
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
            existing = next(
                (item for item in state.candidates if item.candidate_id == candidate_id),
                None,
            )
            if existing is not None:
                return state.model_copy(update={"revision": state.revision + 1}), {
                    "candidate": existing.model_dump(mode="json")
                }
            audit = self._audit(
                target_type="QUALITY_CANDIDATE",
                target_id=candidate_id,
                action="QUALITY_CANDIDATE_CREATED",
                actor=actor,
                owner_unit_id=owner_unit_id,
                before=None,
                after=candidate,
            )
            next_state = QualityState(
                revision=state.revision + 1,
                candidates=(*state.candidates, candidate),
                cases=state.cases,
                clusters=state.clusters,
                audits=(*state.audits, audit),
            )
            return next_state, {"candidate": candidate.model_dump(mode="json")}

        return self._repository.mutate(operation)

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
            case_types = {item.case_type for item in selected}
            issue_types = {item.issue_type_id for item in selected if item.issue_type_id}
            now = datetime.now(UTC)
            case_id = str(uuid.uuid4())
            frequency = sum(item.frequency for item in selected)
            case = QualityCase(
                case_id=case_id,
                title=title,
                description=mask_text(description).text,
                case_type=next(iter(case_types)) if len(case_types) == 1 else "OTHER",
                issue_type_id=next(iter(issue_types)) if len(issue_types) == 1 else None,
                priority=priority,
                owner_unit_id=owner_unit_id,
                assignee_id=assignee_id,
                source_candidate_ids=tuple(candidate_ids),
                source_event_ids=tuple(dict.fromkeys(event for item in selected for event in item.source_event_ids)),
                conversation_refs=tuple(dict.fromkeys(ref for item in selected for ref in item.conversation_refs)),
                faq_ids=tuple(dict.fromkeys(ref for item in selected for ref in item.faq_ids)),
                document_ids=tuple(dict.fromkeys(ref for item in selected for ref in item.document_ids)),
                frequency=frequency,
                negative_rate=sum(item.negative_rate * item.frequency for item in selected) / frequency,
                handoff_rate=sum(item.handoff_rate * item.frequency for item in selected) / frequency,
                estimated_cost_impact=sum(item.estimated_cost_impact for item in selected),
                target_due_at=target_due_at,
                created_by=actor.user_id,
                created_at=now,
                updated_by=actor.user_id,
                updated_at=now,
            )
            candidates = tuple(
                item.model_copy(
                    update={
                        "status": "MERGED",
                        "merged_case_id": case_id,
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
                target_id=case_id,
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
        terminal = status in {"RESOLVED", "WONT_FIX", "DUPLICATE"}
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
                if faq_id not in current.faq_ids or current.status not in {"IN_PROGRESS", "WAITING_REVIEW"}:
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
                raise FaqTransitionError(f"invalid quality case transition: {current.status} -> {status}")
            now = datetime.now(UTC)
            update = {
                **(changes or {}),
                "etag": current.etag + 1,
                "updated_by": actor.user_id,
                "updated_at": now,
            }
            if status is not None:
                update.update(
                    {
                        "status": status,
                        "resolution_type": resolution_type,
                        "resolution_note": mask_text(reason).text if reason else None,
                        "resolved_at": now if status in {"RESOLVED", "WONT_FIX", "DUPLICATE"} else None,
                    }
                )
            updated = QualityCase.model_validate(
                {**current.model_dump(mode="python"), **update}
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
            groups: dict[tuple[str, str], list[QualityCandidate]] = {}
            for candidate in state.candidates:
                if candidate.status != "OPEN":
                    continue
                self._authorize(actor, "ops.quality.write", candidate.owner_unit_id)
                key = (candidate.owner_unit_id, candidate.issue_type_id or "other.unclassified")
                groups.setdefault(key, []).append(candidate)
            active_keys = {
                item.cluster_key
                for item in state.clusters
                if item.status in {"CANDIDATE", "ACCEPTED"}
            }
            now = datetime.now(UTC)
            created = []
            audits = list(state.audits)
            for (owner_unit_id, issue_type_id), group_candidates in groups.items():
                sub_clusters = _cluster_candidates_by_similarity(group_candidates)
                for sub_idx, candidates in enumerate(sub_clusters):
                    candidate_ids = tuple(sorted(item.candidate_id for item in candidates))
                    cluster_key = hashlib.sha256(
                        f"{owner_unit_id}|{issue_type_id}|{'|'.join(candidate_ids)}".encode()
                    ).hexdigest()[:24]
                    if cluster_key in active_keys:
                        continue
                    issue_distribution: dict[str, int] = {}
                    for candidate in candidates:
                        issue = candidate.issue_type_id or "other.unclassified"
                        issue_distribution[issue] = issue_distribution.get(issue, 0) + candidate.frequency
                    name_suffix = f" #{sub_idx + 1}" if len(sub_clusters) > 1 else ""
                    method = "LEXICAL_SIMILARITY" if len(sub_clusters) > 1 else "OWNER_UNIT_ISSUE_TYPE"
                    cluster = QuestionCluster(
                        cluster_id=str(uuid.uuid4()),
                        cluster_key=cluster_key,
                        revision=1,
                        name=f"{owner_unit_id}｜{issue_type_id}{name_suffix}",
                        representative_question=candidates[0].description or candidates[0].title,
                        owner_unit_id=owner_unit_id,
                        source_candidate_ids=candidate_ids,
                        issue_type_distribution=issue_distribution,
                        frequency=sum(item.frequency for item in candidates),
                        grouping_method=method,
                        created_by=actor.user_id,
                        created_at=now,
                    )
                    created.append(cluster)
                    audits.append(
                        self._audit(
                            target_type="QUESTION_CLUSTER",
                            target_id=cluster.cluster_id,
                            action="QUESTION_GROUP_GENERATED",
                            actor=actor,
                            owner_unit_id=owner_unit_id,
                            before=None,
                            after=cluster,
                            reason="lexical_similarity_grouping" if len(sub_clusters) > 1 else "owner_unit_issue_type_grouping",
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
            if len(selected) != len(set(cluster_ids)):
                raise FaqNotFoundError("one or more clusters were not found")
            if any(item.status not in {"CANDIDATE", "ACCEPTED"} for item in selected):
                raise FaqTransitionError("only active cluster revisions can be corrected")
            owners = {item.owner_unit_id for item in selected}
            if len(owners) != 1:
                raise FaqValidationError("clusters from different owner units cannot be combined")
            owner_unit_id = next(iter(owners))
            self._authorize(actor, "ops.quality.write", owner_unit_id)
            if action in {"RENAME", "ACCEPT", "REJECT", "SPLIT"} and len(selected) != 1:
                raise FaqValidationError(f"{action} requires exactly one cluster")
            if action == "MERGE" and len(selected) < 2:
                raise FaqValidationError("MERGE requires at least two clusters")
            all_candidate_ids = tuple(
                dict.fromkeys(candidate for item in selected for candidate in item.source_candidate_ids)
            )
            if action == "SPLIT":
                flattened = [candidate for group in candidate_groups for candidate in group]
                if any(not group for group in candidate_groups) or sorted(flattened) != sorted(all_candidate_ids):
                    raise FaqValidationError("split groups must partition all source candidates")
                groups = candidate_groups
            else:
                groups = (all_candidate_ids,)
            candidates_by_id = {item.candidate_id: item for item in state.candidates}
            if any(candidate not in candidates_by_id for group in groups for candidate in group):
                raise FaqNotFoundError("cluster references an unknown candidate")
            now = datetime.now(UTC)
            new_clusters = []
            for index, group in enumerate(groups, start=1):
                source_candidates = [candidates_by_id[candidate] for candidate in group]
                issue_distribution: dict[str, int] = {}
                for candidate in source_candidates:
                    issue = candidate.issue_type_id or "other.unclassified"
                    issue_distribution[issue] = issue_distribution.get(issue, 0) + candidate.frequency
                status = (
                    "ACCEPTED" if action == "ACCEPT" else "REJECTED" if action == "REJECT" else "CANDIDATE"
                )
                cluster_name = name or selected[0].name
                if action == "SPLIT" and len(groups) > 1:
                    cluster_name = f"{cluster_name} {index}"
                new_clusters.append(
                    QuestionCluster(
                        cluster_id=str(uuid.uuid4()),
                        cluster_key=hashlib.sha256(
                            f"correction|{action}|{'|'.join(group)}|{now.isoformat()}".encode()
                        ).hexdigest()[:24],
                        revision=max(item.revision for item in selected) + 1,
                        status=status,
                        name=cluster_name,
                        representative_question=source_candidates[0].description or source_candidates[0].title,
                        owner_unit_id=owner_unit_id,
                        source_candidate_ids=group,
                        issue_type_distribution=issue_distribution,
                        frequency=sum(item.frequency for item in source_candidates),
                        grouping_method=selected[0].grouping_method,
                        parent_cluster_ids=cluster_ids,
                        created_by=actor.user_id,
                        created_at=now,
                    )
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
        cutoff = target_now - timedelta(days=retention_days)

        current = self._repository.load()
        has_expired_candidates = any(
            c.status in ("MERGED", "REJECTED") and c.updated_at < cutoff
            for c in current.candidates
        )
        has_expired_cases = any(
            cs.status in ("RESOLVED", "WONT_FIX", "DUPLICATE")
            and (cs.resolved_at or cs.updated_at) < cutoff
            for cs in current.cases
        )
        has_expired_clusters = any(
            cl.status in ("REJECTED", "SUPERSEDED") and cl.created_at < cutoff
            for cl in current.clusters
        )
        if not (has_expired_candidates or has_expired_cases or has_expired_clusters):
            return {
                "purged_candidates": 0,
                "purged_cases": 0,
                "purged_clusters": 0,
                "total": 0,
            }

        def operation(state: QualityState) -> tuple[QualityState, dict[str, Any]]:
            kept_candidates: list[QualityCandidate] = []
            purged_candidate_ids: list[str] = []
            for c in state.candidates:
                if c.status in ("MERGED", "REJECTED") and c.updated_at < cutoff:
                    purged_candidate_ids.append(c.candidate_id)
                else:
                    kept_candidates.append(c)

            kept_cases: list[QualityCase] = []
            purged_case_ids: list[str] = []
            for cs in state.cases:
                if cs.status in ("RESOLVED", "WONT_FIX", "DUPLICATE"):
                    ret_time = cs.resolved_at or cs.updated_at
                    if ret_time < cutoff:
                        purged_case_ids.append(cs.case_id)
                        continue
                kept_cases.append(cs)

            kept_clusters: list[QuestionCluster] = []
            purged_cluster_ids: list[str] = []
            for cl in state.clusters:
                if cl.status in ("REJECTED", "SUPERSEDED") and cl.created_at < cutoff:
                    purged_cluster_ids.append(cl.cluster_id)
                else:
                    kept_clusters.append(cl)

            total_purged = len(purged_candidate_ids) + len(purged_case_ids) + len(purged_cluster_ids)
            if total_purged == 0:
                return state.model_copy(update={"revision": state.revision + 1}), {
                    "purged_candidates": 0,
                    "purged_cases": 0,
                    "purged_clusters": 0,
                    "total": 0,
                }

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
                occurred_at=target_now,
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

        return self._repository.mutate(operation)


