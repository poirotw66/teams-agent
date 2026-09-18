"""Retention purge operation for governance policies."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from operations_core.access import ActorContext

from .models import GovernanceState, replace_model


def _protected_version_ids(state: GovernanceState) -> tuple[set[str], set[str], set[str]]:
    active_prompt_ids = {p.active_version_id for p in state.prompts if p.active_version_id}
    healthy_prompt_ids = {
        p.previous_healthy_version_id for p in state.prompts if p.previous_healthy_version_id
    }
    canary_prompt_ids = {p.canary_version_id for p in state.prompts if p.canary_version_id}
    protected_prompt_ids = active_prompt_ids | healthy_prompt_ids | canary_prompt_ids
    active_flag_ids = {f.active_version_id for f in state.flags if f.active_version_id}
    active_model_ids = {m.active_version_id for m in state.model_configs if m.active_version_id}
    healthy_model_ids = {
        m.previous_healthy_version_id for m in state.model_configs if m.previous_healthy_version_id
    }
    return protected_prompt_ids, active_flag_ids, active_model_ids | healthy_model_ids


def _prune_versions(
    state: GovernanceState,
    *,
    protected_prompt_ids: set[str],
    active_flag_ids: set[str],
    protected_model_ids: set[str],
    cutoff: datetime,
    audit_cutoff: datetime,
) -> tuple[
    tuple[Any, ...],
    tuple[Any, ...],
    tuple[Any, ...],
    tuple[Any, ...],
    tuple[Any, ...],
    dict[str, int],
]:
    new_flag_versions = tuple(
        v
        for v in state.flag_versions
        if v.version_id in active_flag_ids
        or v.status in ("ACTIVE", "APPROVED")
        or v.created_at >= cutoff
    )
    new_prompt_versions = tuple(
        v
        for v in state.prompt_versions
        if v.version_id in protected_prompt_ids
        or v.status in ("ACTIVE", "APPROVED", "CANARY")
        or v.created_at >= cutoff
    )
    new_model_versions = tuple(
        v
        for v in state.model_versions
        if v.version_id in protected_model_ids
        or v.status in ("ACTIVE", "APPROVED")
        or v.created_at >= cutoff
    )
    new_audits = tuple(a for a in state.audits if a.occurred_at >= audit_cutoff)
    new_idempotency = tuple(i for i in state.idempotency if i.created_at >= cutoff)
    counts = {
        "pruned_flags": len(state.flag_versions) - len(new_flag_versions),
        "pruned_prompts": len(state.prompt_versions) - len(new_prompt_versions),
        "pruned_models": len(state.model_versions) - len(new_model_versions),
        "pruned_audits": len(state.audits) - len(new_audits),
        "pruned_idempotency": len(state.idempotency) - len(new_idempotency),
    }
    return (
        new_flag_versions,
        new_prompt_versions,
        new_model_versions,
        new_audits,
        new_idempotency,
        counts,
    )


def apply_purge_to_state(
    state: GovernanceState,
    *,
    actor: ActorContext | None,
    retention_days: int,
    effective_audit_days: int,
    cutoff: datetime,
    audit_cutoff: datetime,
    audit_factory: Callable[..., Any],
) -> tuple[GovernanceState, dict[str, Any]]:
    protected_prompt_ids, active_flag_ids, protected_model_ids = _protected_version_ids(state)
    (
        new_flag_versions,
        new_prompt_versions,
        new_model_versions,
        new_audits,
        new_idempotency,
        counts,
    ) = _prune_versions(
        state,
        protected_prompt_ids=protected_prompt_ids,
        active_flag_ids=active_flag_ids,
        protected_model_ids=protected_model_ids,
        cutoff=cutoff,
        audit_cutoff=audit_cutoff,
    )
    total_removed = sum(counts.values())
    audit_events = list(new_audits)
    if actor is not None and total_removed > 0:
        audit_events.append(
            audit_factory(
                action="GOVERNANCE_RETENTION_PURGE",
                actor=actor,
                target_type="RETENTION",
                target_id="GOVERNANCE_RETENTION",
                after={
                    "prunedFlags": counts["pruned_flags"],
                    "prunedPrompts": counts["pruned_prompts"],
                    "prunedModels": counts["pruned_models"],
                    "prunedAudits": counts["pruned_audits"],
                    "prunedIdempotency": counts["pruned_idempotency"],
                    "totalRemoved": total_removed,
                    "retentionDays": retention_days,
                    "auditRetentionDays": effective_audit_days,
                },
            )
        )
    new_state = replace_model(
        state,
        flag_versions=new_flag_versions,
        prompt_versions=new_prompt_versions,
        model_versions=new_model_versions,
        audits=tuple(audit_events),
        idempotency=new_idempotency,
    )
    return new_state, {
        "flagVersions": counts["pruned_flags"],
        "promptVersions": counts["pruned_prompts"],
        "modelVersions": counts["pruned_models"],
        "audits": counts["pruned_audits"],
        "idempotency": counts["pruned_idempotency"],
        "totalRemoved": total_removed,
        "retentionDays": retention_days,
        "auditRetentionDays": effective_audit_days,
        "retentionPolicy": (
            "Core active, approved, canary, and previous-healthy versions retained "
            "permanently for rollback capability; "
            f"expired candidate and retired versions older than {retention_days} days purged; "
            f"audits retained for {effective_audit_days} days."
        ),
    }
