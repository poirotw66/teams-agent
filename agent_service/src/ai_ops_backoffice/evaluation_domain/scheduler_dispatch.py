"""Per-schedule dispatch helpers for EvalScheduler."""

from __future__ import annotations

import uuid
from datetime import datetime

from operations_core.access import ActorContext

from .gate_models import ScheduleDispatchResult
from .scheduler_timing import compute_next_due_time


def overlap_skip_result(schedule, current_due: datetime, now: datetime, last_run_status: str):
    dispatch_id = f"disp_skip_overlap_{uuid.uuid4().hex[:8]}"
    logical_key = f"{schedule.schedule_id}:{current_due.isoformat()}:{schedule.tenant_id}"
    return ScheduleDispatchResult(
        dispatch_id=dispatch_id,
        schedule_id=schedule.schedule_id,
        logical_key=logical_key,
        scheduled_at=current_due,
        dispatched_at=now,
        status="SKIPPED_OVERLAP",
        reason=(
            f"Previous run '{schedule.last_run_id}' is still active ({last_run_status})"
        ),
    )


def coalesce_misfire(schedule, current_due: datetime, now: datetime) -> tuple[datetime, datetime, int]:
    next_due = compute_next_due_time(current_due, schedule.frequency, schedule.timezone)
    missed_count_delta = 0
    interval_seconds = max((next_due - current_due).total_seconds(), 60.0)
    elapsed_seconds = (now - current_due).total_seconds()
    periods_elapsed = int(elapsed_seconds // interval_seconds)
    if periods_elapsed > 1 and schedule.misfire_policy == "COALESCE_LATEST":
        missed_count_delta = periods_elapsed - 1
        for _ in range(missed_count_delta):
            current_due = compute_next_due_time(
                current_due, schedule.frequency, schedule.timezone
            )
        next_due = compute_next_due_time(current_due, schedule.frequency, schedule.timezone)
    return current_due, next_due, missed_count_delta


def budget_skip_result(
    schedule,
    *,
    current_due: datetime,
    now: datetime,
    logical_key: str,
    dispatch_id: str,
    estimated_cost: float,
) -> ScheduleDispatchResult:
    return ScheduleDispatchResult(
        dispatch_id=dispatch_id,
        schedule_id=schedule.schedule_id,
        logical_key=logical_key,
        scheduled_at=current_due,
        dispatched_at=now,
        status="SKIPPED_BUDGET",
        estimated_cost_usd=estimated_cost,
        reason=(
            f"Estimated run cost ${estimated_cost:.4f} exceeds budget limit "
            f"${schedule.budget_limit_usd:.4f}"
        ),
    )


def resolve_schedule_targets(schedule, gate_service) -> tuple[dict, dict]:
    baseline_target = schedule.target_refs.get("baseline_target", {})
    candidate_target = schedule.target_refs.get("candidate_target", {})
    if schedule.target_selector == "CURRENT_ACTIVE" and gate_service:
        active_ptr = gate_service.get_active_pointer(
            tenant_id=schedule.tenant_id,
            environment="prod",
            target_type="KNOWLEDGE",
        )
        if active_ptr and active_ptr.active_target_manifest:
            baseline_target = dict(active_ptr.active_target_manifest)
    if not baseline_target:
        baseline_target = {
            "target_id": f"sched_{schedule.schedule_id[:6]}_baseline",
            "knowledge_release_id": schedule.target_refs.get(
                "knowledge_release_id", "rel-001"
            ),
        }
    if not candidate_target:
        candidate_target = {
            "target_id": f"sched_{schedule.schedule_id[:6]}_candidate",
            "knowledge_release_id": schedule.target_refs.get(
                "knowledge_release_id", "rel-001"
            ),
        }
    return baseline_target, candidate_target


def create_scheduled_run(run_service, schedule, baseline_target, candidate_target):
    actor = ActorContext(
        user_id="scheduler_daemon",
        display_name="Evaluation Scheduler Daemon",
        role="SYSTEM_ADMIN",
        owner_unit_ids=("ALL",),
        tenant_id=schedule.tenant_id,
    )
    return run_service.create_run(
        set_version_id=schedule.set_version_id,
        baseline_target=baseline_target,
        candidate_target=candidate_target,
        mode=schedule.target_refs.get("mode", "REAL_RAG"),
        actor=actor,
    )
