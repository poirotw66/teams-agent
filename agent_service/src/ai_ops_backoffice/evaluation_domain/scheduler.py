from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from agent_service.operations.access import ActorContext

from .errors import EvaluationNotFoundError, EvaluationValidationError
from .gate_models import (
    EvalSchedule,
    ScheduleDispatchResult,
    ScheduleFrequency,
)
from .gate_repository import QualityGateRepositoryProtocol
from .gate_service import QualityGateService
from .repository import EvaluationRepository
from .run_service import EvaluationRunService
from .runner_models import TargetManifest

logger = logging.getLogger(__name__)

SYSTEM_SCHEDULER_ACTOR = ActorContext(
    user_id="scheduler_daemon",
    display_name="Evaluation Scheduler Daemon",
    role="SYSTEM_ADMIN",
    owner_unit_ids=("ALL",),
    tenant_id="default",
)


def compute_next_due_time(
    current_due: datetime,
    frequency: ScheduleFrequency,
    tz_name: str = "UTC",
) -> datetime:
    """Calculates the next due datetime in UTC, preserving local wall-clock time across DST transitions (Spec 7.2)."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    local_dt = current_due.astimezone(tz)

    if frequency == "HOURLY":
        next_local = local_dt + timedelta(hours=1)
    elif frequency == "DAILY":
        # Advance by 1 calendar day, keeping local wall-clock hour and minute constant across DST
        next_date = local_dt.date() + timedelta(days=1)
        next_local = datetime.combine(next_date, local_dt.time(), tzinfo=tz)
    elif frequency == "WEEKLY":
        next_date = local_dt.date() + timedelta(weeks=1)
        next_local = datetime.combine(next_date, local_dt.time(), tzinfo=tz)
    elif frequency == "ON_CHANGE":
        return current_due
    else:
        next_date = local_dt.date() + timedelta(days=1)
        next_local = datetime.combine(next_date, local_dt.time(), tzinfo=tz)

    return next_local.astimezone(timezone.utc)


class EvalScheduler:
    """Manages scheduled evaluation runs, atomic logical-key deduping, and misfire coalescing (F06-T1)."""

    def __init__(
        self,
        gate_repository: QualityGateRepositoryProtocol,
        eval_repository: EvaluationRepository,
        run_service: EvaluationRunService,
        gate_service: QualityGateService | None = None,
    ) -> None:
        self._gate_repo = gate_repository
        self._eval_repo = eval_repository
        self._run_service = run_service
        self._gate_service = gate_service

    def scan_and_dispatch_due_schedules(
        self,
        now_utc: datetime | None = None,
        max_catchup_runs: int = 1,
    ) -> list[ScheduleDispatchResult]:
        """Scans all enabled schedules and dispatches due evaluations with atomic logical-key deduping.
        
        Guarantees that dual schedulers, process restarts, or queue retries will never create duplicate
        logical evaluation runs (Spec 7.2, F06-T1).
        """
        now = now_utc or datetime.now(timezone.utc)
        results: list[ScheduleDispatchResult] = []
        schedules = self._gate_repo.list_schedules()

        for schedule in schedules:
            if not schedule.is_enabled:
                continue

            # Initialize next_due_at if missing
            current_due = schedule.next_due_at
            if current_due is None:
                current_due = now
                schedule = schedule.model_copy(update={"next_due_at": current_due})
                self._gate_repo.save_schedule(schedule)

            if current_due > now:
                continue

            # Check overlap protection (Spec 7.2: 預設禁止同 schedule 重疊)
            if schedule.last_run_id:
                try:
                    state = self._eval_repo.load()
                    last_run = next((r for r in state.runs if r.run_id == schedule.last_run_id), None)
                    if last_run and last_run.status in {"PENDING", "RUNNING"}:
                        dispatch_id = f"disp_skip_overlap_{uuid.uuid4().hex[:8]}"
                        logical_key = f"{schedule.schedule_id}:{current_due.isoformat()}:{schedule.tenant_id}"
                        res = ScheduleDispatchResult(
                            dispatch_id=dispatch_id,
                            schedule_id=schedule.schedule_id,
                            logical_key=logical_key,
                            scheduled_at=current_due,
                            dispatched_at=now,
                            status="SKIPPED_OVERLAP",
                            reason=f"Previous run '{schedule.last_run_id}' is still active ({last_run.status})",
                        )
                        results.append(res)
                        continue
                except Exception as exc:
                    logger.warning("Error checking last_run status for schedule %s: %s", schedule.schedule_id, exc)

            # Misfire check (Spec 7.2: misfire 預設合併成一次最新補跑，標示漏過次數)
            next_due = compute_next_due_time(current_due, schedule.frequency, schedule.timezone)
            missed_count_delta = 0

            # If current_due is far in the past (more than one period missed)
            interval_seconds = max((next_due - current_due).total_seconds(), 60.0)
            elapsed_seconds = (now - current_due).total_seconds()
            periods_elapsed = int(elapsed_seconds // interval_seconds)

            if periods_elapsed > 1 and schedule.misfire_policy == "COALESCE_LATEST":
                missed_count_delta = periods_elapsed - 1
                # Advance current_due to the latest due slot
                for _ in range(missed_count_delta):
                    current_due = compute_next_due_time(current_due, schedule.frequency, schedule.timezone)
                next_due = compute_next_due_time(current_due, schedule.frequency, schedule.timezone)

            # Construct unique logical key (scheduleId + scheduledAt + tenant)
            logical_key = f"{schedule.schedule_id}:{current_due.isoformat()}:{schedule.tenant_id}"
            dispatch_id = f"disp_{uuid.uuid4().hex[:12]}"

            # Check Budget Limit (Spec 7.2: 預算不足保存 SKIPPED_BUDGET，不無限重試)
            estimated_cost = float(schedule.target_refs.get("estimated_cost_usd", 0.05))
            if schedule.budget_limit_usd is not None and estimated_cost > schedule.budget_limit_usd:
                dispatch_record = ScheduleDispatchResult(
                    dispatch_id=dispatch_id,
                    schedule_id=schedule.schedule_id,
                    logical_key=logical_key,
                    scheduled_at=current_due,
                    dispatched_at=now,
                    status="SKIPPED_BUDGET",
                    estimated_cost_usd=estimated_cost,
                    reason=f"Estimated run cost ${estimated_cost:.4f} exceeds budget limit ${schedule.budget_limit_usd:.4f}",
                )
                saved = self._gate_repo.save_schedule_dispatch(dispatch_record)
                if saved:
                    results.append(dispatch_record)
                    # Advance schedule next_due_at so it doesn't loop forever
                    updated_schedule = schedule.model_copy(
                        update={
                            "next_due_at": next_due,
                            "missed_count": schedule.missed_count + missed_count_delta,
                            "revision": schedule.revision + 1,
                            "updated_at": now,
                        }
                    )
                    self._gate_repo.save_schedule(updated_schedule)
                continue

            # Atomic logical-key dispatch lock (Spec 7.2, F06-T1)
            dispatch_record = ScheduleDispatchResult(
                dispatch_id=dispatch_id,
                schedule_id=schedule.schedule_id,
                logical_key=logical_key,
                scheduled_at=current_due,
                dispatched_at=now,
                status="DISPATCHED",
                estimated_cost_usd=estimated_cost,
            )
            saved = self._gate_repo.save_schedule_dispatch(dispatch_record)
            if not saved:
                # Slot was already claimed by another scheduler instance or retry
                results.append(
                    ScheduleDispatchResult(
                        dispatch_id=dispatch_id,
                        schedule_id=schedule.schedule_id,
                        logical_key=logical_key,
                        scheduled_at=current_due,
                        dispatched_at=now,
                        status="DUPLICATE_IGNORED",
                        reason="Logical run key already claimed by concurrent scheduler or previous dispatch",
                    )
                )
                continue

            # Resolve target manifests
            baseline_target = schedule.target_refs.get("baseline_target", {})
            candidate_target = schedule.target_refs.get("candidate_target", {})

            # Target selector resolution (Spec 7.2: 可指向「目前正式／指定候選」，每次派工解析成不可變 manifest)
            if schedule.target_selector == "CURRENT_ACTIVE" and self._gate_service:
                active_ptr = self._gate_service.get_active_pointer(
                    tenant_id=schedule.tenant_id,
                    environment="prod",
                    target_type="KNOWLEDGE",
                )
                if active_ptr and active_ptr.active_target_manifest:
                    baseline_target = dict(active_ptr.active_target_manifest)

            if not baseline_target:
                baseline_target = {
                    "target_id": f"sched_{schedule.schedule_id[:6]}_baseline",
                    "knowledge_release_id": schedule.target_refs.get("knowledge_release_id", "rel-001"),
                }
            if not candidate_target:
                candidate_target = {
                    "target_id": f"sched_{schedule.schedule_id[:6]}_candidate",
                    "knowledge_release_id": schedule.target_refs.get("knowledge_release_id", "rel-001"),
                }

            # Create the actual Evaluation Run
            actor = ActorContext(
                user_id="scheduler_daemon",
                display_name="Evaluation Scheduler Daemon",
                role="SYSTEM_ADMIN",
                owner_unit_ids=("ALL",),
                tenant_id=schedule.tenant_id,
            )
            try:
                run_res = self._run_service.create_run(
                    set_version_id=schedule.set_version_id,
                    baseline_target=baseline_target,
                    candidate_target=candidate_target,
                    mode=schedule.target_refs.get("mode", "REAL_RAG"),
                    actor=actor,
                )
                run_id = run_res["run"]["run_id"]
                dispatch_record = dispatch_record.model_copy(update={"run_id": run_id})
            except Exception as err:
                logger.error("Failed creating run for schedule %s: %s", schedule.schedule_id, err)
                dispatch_record = dispatch_record.model_copy(
                    update={"status": "DUPLICATE_IGNORED", "reason": str(err)}
                )

            results.append(dispatch_record)

            # Update schedule state
            updated_schedule = schedule.model_copy(
                update={
                    "last_run_id": dispatch_record.run_id,
                    "last_run_at": now,
                    "next_due_at": next_due,
                    "missed_count": schedule.missed_count + missed_count_delta,
                    "revision": schedule.revision + 1,
                    "updated_at": now,
                }
            )
            self._gate_repo.save_schedule(updated_schedule)

        return results
