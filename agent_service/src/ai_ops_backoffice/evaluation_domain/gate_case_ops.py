"""Source-impact, quality-case, and schedule helpers for quality gates."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from operations_core.access import ActorContext

from .errors import EvaluationNotFoundError
from .gate_models import EvalSchedule, QualityCaseLink, SourceImpactResult
from .gate_repository import QualityGateRepository
from .repository import EvaluationRepository

__all__ = [
    "analyze_source_impact",
    "create_schedule",
    "link_quality_case",
    "resolve_quality_case",
    "update_schedule",
]


def analyze_source_impact(
    eval_repo: EvaluationRepository,
    *,
    source_type: str,
    source_id: str,
    source_version: str | None = None,
) -> SourceImpactResult:
    """Finds all eval cases and sets affected when an underlying document or FAQ is updated."""
    state = eval_repo.load()
    affected_case_ids: set[str] = set()
    affected_rev_ids: set[str] = set()

    for rev in state.revisions:
        hit = False
        if rev.provenance and rev.provenance.source_id == source_id:
            hit = True
        for req in rev.evidence:
            for item in req.items:
                if item.source_id == source_id:
                    hit = True
                    break
        if hit:
            affected_rev_ids.add(rev.revision_id)
            affected_case_ids.add(rev.case_id)

    affected_set_version_ids: set[str] = set()
    for set_version in state.set_versions:
        if any(rev_id in affected_rev_ids for rev_id in set_version.case_revision_ids):
            affected_set_version_ids.add(set_version.set_version_id)

    return SourceImpactResult(
        source_type=source_type,
        source_id=source_id,
        source_version=source_version,
        affected_case_ids=tuple(sorted(affected_case_ids)),
        affected_revision_ids=tuple(sorted(affected_rev_ids)),
        affected_set_version_ids=tuple(sorted(affected_set_version_ids)),
        has_active_manifest_impact=len(affected_set_version_ids) > 0,
        requires_review_count=len(affected_rev_ids),
    )


def link_quality_case(
    gate_repo: QualityGateRepository,
    *,
    run_id: str,
    execution_id: str,
    root_cause: str,
    actor: ActorContext,
) -> QualityCaseLink:
    """Links an evaluation execution failure to a deduplicated quality case."""
    _ = actor
    existing = gate_repo.get_quality_case_by_execution(execution_id)
    if existing:
        return existing

    now = datetime.now(timezone.utc)
    link = QualityCaseLink(
        quality_case_id=f"qc_{run_id[:8]}_{execution_id[:8]}",
        eval_case_id=execution_id.split("_")[-1] if "_" in execution_id else execution_id,
        run_id=run_id,
        execution_id=execution_id,
        root_cause=root_cause,
        status="OPEN",
        created_at=now,
        updated_at=now,
    )
    gate_repo.save_quality_case(link)
    return link


def resolve_quality_case(
    gate_repo: QualityGateRepository,
    *,
    quality_case_id: str,
    resolution_run_id: str,
) -> QualityCaseLink:
    link = gate_repo.get_quality_case(quality_case_id)
    if not link:
        raise EvaluationNotFoundError(f"Quality case '{quality_case_id}' not found")

    now = datetime.now(timezone.utc)
    resolved = link.model_copy(
        update={
            "status": "RESOLVED",
            "resolution_run_id": resolution_run_id,
            "updated_at": now,
        }
    )
    gate_repo.save_quality_case(resolved)
    return resolved


def create_schedule(
    gate_repo: QualityGateRepository,
    *,
    schedule_id: str,
    tenant_id: str,
    name: str,
    set_version_id: str,
    frequency: str = "DAILY",
    budget_limit_usd: float = 5.0,
    target_refs: dict[str, Any] | None = None,
    created_by: str,
) -> EvalSchedule:
    now = datetime.now(timezone.utc)
    schedule = EvalSchedule(
        schedule_id=schedule_id,
        tenant_id=tenant_id,
        name=name,
        set_version_id=set_version_id,
        frequency=frequency,  # type: ignore[arg-type]
        budget_limit_usd=budget_limit_usd,
        target_refs=target_refs or {},
        is_enabled=True,
        created_by=created_by,
        created_at=now,
        updated_by=created_by,
        updated_at=now,
    )
    gate_repo.save_schedule(schedule)
    return schedule


def update_schedule(
    gate_repo: QualityGateRepository,
    *,
    schedule_id: str,
    is_enabled: bool | None = None,
    frequency: str | None = None,
    budget_limit_usd: float | None = None,
    target_refs: dict[str, Any] | None = None,
    updated_by: str,
) -> EvalSchedule:
    schedule = gate_repo.get_schedule(schedule_id)
    if not schedule:
        raise EvaluationNotFoundError(f"Schedule '{schedule_id}' not found")
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {"updated_by": updated_by, "updated_at": now}
    if is_enabled is not None:
        updates["is_enabled"] = is_enabled
    if frequency is not None:
        updates["frequency"] = frequency
    if budget_limit_usd is not None:
        updates["budget_limit_usd"] = budget_limit_usd
    if target_refs is not None:
        updates["target_refs"] = target_refs

    updated = schedule.model_copy(update=updates)
    gate_repo.save_schedule(updated)
    return updated
