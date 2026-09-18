"""Question-cluster grouping helpers for the quality domain."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Literal

from ..faq_domain.errors import (
    FaqNotFoundError,
    FaqTransitionError,
    FaqValidationError,
)
from .models import QualityCandidate, QuestionCluster

__all__ = [
    "build_corrected_clusters",
    "build_generated_clusters",
    "cluster_candidates_by_similarity",
    "issue_type_distribution",
]


def tokenize_quality_text(text: str) -> set[str]:
    """Tokenize Latin words and CJK unigrams/bigrams for Jaccard clustering."""
    tokens = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
    cjk_chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    tokens.update(cjk_chars)
    for index in range(len(cjk_chars) - 1):
        tokens.add(cjk_chars[index] + cjk_chars[index + 1])
    return {token for token in tokens if len(token) > 1 or ("\u4e00" <= token <= "\u9fff")}


def cluster_candidates_by_similarity(
    candidates: list[QualityCandidate],
) -> list[list[QualityCandidate]]:
    """Cluster candidates based on normalized token overlap of their question texts."""
    if len(candidates) <= 1:
        return [candidates]

    clusters: list[list[QualityCandidate]] = []
    cluster_tokens: list[set[str]] = []

    for candidate in candidates:
        text = f"{candidate.title} {candidate.description}"
        candidate_tokens = tokenize_quality_text(text)
        assigned = False
        for index, existing_tokens in enumerate(cluster_tokens):
            intersection = candidate_tokens & existing_tokens
            union = candidate_tokens | existing_tokens
            jaccard = len(intersection) / len(union) if union else 0.0
            if jaccard >= 0.3 or len(intersection) >= 2:
                clusters[index].append(candidate)
                existing_tokens.update(candidate_tokens)
                assigned = True
                break
        if not assigned:
            clusters.append([candidate])
            cluster_tokens.append(set(candidate_tokens))

    return clusters


def issue_type_distribution(candidates: list[QualityCandidate]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for candidate in candidates:
        issue = candidate.issue_type_id or "other.unclassified"
        distribution[issue] = distribution.get(issue, 0) + candidate.frequency
    return distribution


def group_open_candidates_by_owner_issue(
    candidates: tuple[QualityCandidate, ...],
) -> dict[tuple[str, str], list[QualityCandidate]]:
    groups: dict[tuple[str, str], list[QualityCandidate]] = {}
    for candidate in candidates:
        if candidate.status != "OPEN":
            continue
        key = (candidate.owner_unit_id, candidate.issue_type_id or "other.unclassified")
        groups.setdefault(key, []).append(candidate)
    return groups


def build_generated_clusters(
    *,
    groups: dict[tuple[str, str], list[QualityCandidate]],
    active_keys: set[str],
    actor_user_id: str,
    now: datetime,
) -> list[QuestionCluster]:
    """Build new question clusters from owner-unit / issue-type candidate groups."""
    created: list[QuestionCluster] = []
    for (owner_unit_id, issue_type_id), group_candidates in groups.items():
        sub_clusters = cluster_candidates_by_similarity(group_candidates)
        for sub_index, clustered in enumerate(sub_clusters):
            cluster = _build_generated_cluster(
                owner_unit_id=owner_unit_id,
                issue_type_id=issue_type_id,
                candidates=clustered,
                sub_index=sub_index,
                sub_cluster_count=len(sub_clusters),
                active_keys=active_keys,
                actor_user_id=actor_user_id,
                now=now,
            )
            if cluster is not None:
                created.append(cluster)
    return created


def _build_generated_cluster(
    *,
    owner_unit_id: str,
    issue_type_id: str,
    candidates: list[QualityCandidate],
    sub_index: int,
    sub_cluster_count: int,
    active_keys: set[str],
    actor_user_id: str,
    now: datetime,
) -> QuestionCluster | None:
    candidate_ids = tuple(sorted(item.candidate_id for item in candidates))
    cluster_key = hashlib.sha256(
        f"{owner_unit_id}|{issue_type_id}|{'|'.join(candidate_ids)}".encode()
    ).hexdigest()[:24]
    if cluster_key in active_keys:
        return None
    name_suffix = f" #{sub_index + 1}" if sub_cluster_count > 1 else ""
    method = "LEXICAL_SIMILARITY" if sub_cluster_count > 1 else "OWNER_UNIT_ISSUE_TYPE"
    return QuestionCluster(
        cluster_id=str(uuid.uuid4()),
        cluster_key=cluster_key,
        revision=1,
        name=f"{owner_unit_id}｜{issue_type_id}{name_suffix}",
        representative_question=candidates[0].description or candidates[0].title,
        owner_unit_id=owner_unit_id,
        source_candidate_ids=candidate_ids,
        issue_type_distribution=issue_type_distribution(candidates),
        frequency=sum(item.frequency for item in candidates),
        grouping_method=method,  # type: ignore[arg-type]
        created_by=actor_user_id,
        created_at=now,
    )


def resolve_correction_groups(
    *,
    action: Literal["RENAME", "ACCEPT", "REJECT", "MERGE", "SPLIT"],
    selected: list[QuestionCluster],
    candidate_groups: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Validate correction action constraints and return candidate id groups."""
    if action in {"RENAME", "ACCEPT", "REJECT", "SPLIT"} and len(selected) != 1:
        raise FaqValidationError(f"{action} requires exactly one cluster")
    if action == "MERGE" and len(selected) < 2:
        raise FaqValidationError("MERGE requires at least two clusters")
    all_candidate_ids = tuple(
        dict.fromkeys(candidate for item in selected for candidate in item.source_candidate_ids)
    )
    if action != "SPLIT":
        return (all_candidate_ids,)
    flattened = [candidate for group in candidate_groups for candidate in group]
    if any(not group for group in candidate_groups) or sorted(flattened) != sorted(
        all_candidate_ids
    ):
        raise FaqValidationError("split groups must partition all source candidates")
    return candidate_groups


def build_corrected_clusters(
    *,
    action: Literal["RENAME", "ACCEPT", "REJECT", "MERGE", "SPLIT"],
    selected: list[QuestionCluster],
    cluster_ids: tuple[str, ...],
    groups: tuple[tuple[str, ...], ...],
    candidates_by_id: dict[str, QualityCandidate],
    name: str | None,
    actor_user_id: str,
    now: datetime,
) -> list[QuestionCluster]:
    """Build replacement clusters for a correction action."""
    if any(candidate not in candidates_by_id for group in groups for candidate in group):
        raise FaqNotFoundError("cluster references an unknown candidate")
    owner_unit_id = selected[0].owner_unit_id
    revision = max(item.revision for item in selected) + 1
    status = "ACCEPTED" if action == "ACCEPT" else "REJECTED" if action == "REJECT" else "CANDIDATE"
    new_clusters: list[QuestionCluster] = []
    for index, group in enumerate(groups, start=1):
        source_candidates = [candidates_by_id[candidate] for candidate in group]
        cluster_name = name or selected[0].name
        if action == "SPLIT" and len(groups) > 1:
            cluster_name = f"{cluster_name} {index}"
        new_clusters.append(
            QuestionCluster(
                cluster_id=str(uuid.uuid4()),
                cluster_key=hashlib.sha256(
                    f"correction|{action}|{'|'.join(group)}|{now.isoformat()}".encode()
                ).hexdigest()[:24],
                revision=revision,
                status=status,
                name=cluster_name,
                representative_question=(
                    source_candidates[0].description or source_candidates[0].title
                ),
                owner_unit_id=owner_unit_id,
                source_candidate_ids=group,
                issue_type_distribution=issue_type_distribution(source_candidates),
                frequency=sum(item.frequency for item in source_candidates),
                grouping_method=selected[0].grouping_method,
                parent_cluster_ids=cluster_ids,
                created_by=actor_user_id,
                created_at=now,
            )
        )
    return new_clusters


def require_active_clusters(
    selected: list[QuestionCluster],
    cluster_ids: tuple[str, ...],
) -> str:
    """Validate selected clusters and return the shared owner unit id."""
    if len(selected) != len(set(cluster_ids)):
        raise FaqNotFoundError("one or more clusters were not found")
    if any(item.status not in {"CANDIDATE", "ACCEPTED"} for item in selected):
        raise FaqTransitionError("only active cluster revisions can be corrected")
    owners = {item.owner_unit_id for item in selected}
    if len(owners) != 1:
        raise FaqValidationError("clusters from different owner units cannot be combined")
    return next(iter(owners))
