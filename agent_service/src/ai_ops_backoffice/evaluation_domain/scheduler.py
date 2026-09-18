"""Evaluation schedule scanner and dispatcher."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from operations_core.access import ActorContext

from .gate_models import ScheduleDispatchResult
from .gate_repository import QualityGateRepositoryProtocol
from .gate_service import QualityGateService
from .repository import EvaluationRepository
from .run_service import EvaluationRunService
from .scheduler_dispatch import (
    budget_skip_result,
    coalesce_misfire,
    create_scheduled_run,
    overlap_skip_result,
    resolve_schedule_targets,
)
from .scheduler_timing import compute_next_due_time

logger = logging.getLogger(__name__)

SYSTEM_SCHEDULER_ACTOR = ActorContext(
    user_id="scheduler_daemon",
    display_name="Evaluation Scheduler Daemon",
    role="SYSTEM_ADMIN",
    owner_unit_ids=("ALL",),
    tenant_id="default",
)

__all__ = ["SYSTEM_SCHEDULER_ACTOR", "EvalScheduler", "compute_next_due_time"]


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

    def _overlap_result_if_active(self, schedule, current_due: datetime, now: datetime):
        if not schedule.last_run_id:
            return None
        try:
            state = self._eval_repo.load()
            last_run = next(
                (run for run in state.runs if run.run_id == schedule.last_run_id),
                None,
            )
            if last_run and last_run.status in {"PENDING", "RUNNING"}:
                return overlap_skip_result(schedule, current_due, now, last_run.status)
        except Exception as exc:
            logger.warning(
                "Error checking last_run status for schedule %s: %s",
                schedule.schedule_id,
                exc,
            )
        return None

    def _save_budget_skip(
        self,
        schedule,
        *,
        current_due: datetime,
        next_due: datetime,
        now: datetime,
        missed_count_delta: int,
        logical_key: str,
        dispatch_id: str,
        estimated_cost: float,
    ) -> ScheduleDispatchResult | None:
        dispatch_record = budget_skip_result(
            schedule,
            current_due=current_due,
            now=now,
            logical_key=logical_key,
            dispatch_id=dispatch_id,
            estimated_cost=estimated_cost,
        )
        if not self._gate_repo.save_schedule_dispatch(dispatch_record):
            return None
        self._gate_repo.save_schedule(
            schedule.model_copy(
                update={
                    "next_due_at": next_due,
                    "missed_count": schedule.missed_count + missed_count_delta,
                    "revision": schedule.revision + 1,
                    "updated_at": now,
                }
            )
        )
        return dispatch_record

    def _claim_and_create_run(
        self,
        schedule,
        *,
        current_due: datetime,
        next_due: datetime,
        now: datetime,
        missed_count_delta: int,
        logical_key: str,
        dispatch_id: str,
        estimated_cost: float,
    ) -> ScheduleDispatchResult:
        dispatch_record = ScheduleDispatchResult(
            dispatch_id=dispatch_id,
            schedule_id=schedule.schedule_id,
            logical_key=logical_key,
            scheduled_at=current_due,
            dispatched_at=now,
            status="DISPATCHED",
            estimated_cost_usd=estimated_cost,
        )
        if not self._gate_repo.save_schedule_dispatch(dispatch_record):
            return ScheduleDispatchResult(
                dispatch_id=dispatch_id,
                schedule_id=schedule.schedule_id,
                logical_key=logical_key,
                scheduled_at=current_due,
                dispatched_at=now,
                status="DUPLICATE_IGNORED",
                reason=(
                    "Logical run key already claimed by concurrent scheduler "
                    "or previous dispatch"
                ),
            )

        baseline_target, candidate_target = resolve_schedule_targets(
            schedule, self._gate_service
        )
        try:
            run_res = create_scheduled_run(
                self._run_service, schedule, baseline_target, candidate_target
            )
            dispatch_record = dispatch_record.model_copy(
                update={"run_id": run_res["run"]["run_id"]}
            )
        except Exception as err:
            logger.error("Failed creating run for schedule %s: %s", schedule.schedule_id, err)
            dispatch_record = dispatch_record.model_copy(
                update={"status": "DUPLICATE_IGNORED", "reason": str(err)}
            )

        self._gate_repo.save_schedule(
            schedule.model_copy(
                update={
                    "last_run_id": dispatch_record.run_id,
                    "last_run_at": now,
                    "next_due_at": next_due,
                    "missed_count": schedule.missed_count + missed_count_delta,
                    "revision": schedule.revision + 1,
                    "updated_at": now,
                }
            )
        )
        return dispatch_record

    def _dispatch_due_schedule(
        self,
        schedule,
        *,
        now: datetime,
    ) -> ScheduleDispatchResult | None:
        current_due = schedule.next_due_at
        if current_due is None:
            current_due = now
            schedule = schedule.model_copy(update={"next_due_at": current_due})
            self._gate_repo.save_schedule(schedule)
        if current_due > now:
            return None

        overlap = self._overlap_result_if_active(schedule, current_due, now)
        if overlap is not None:
            return overlap

        current_due, next_due, missed_count_delta = coalesce_misfire(
            schedule, current_due, now
        )
        logical_key = f"{schedule.schedule_id}:{current_due.isoformat()}:{schedule.tenant_id}"
        dispatch_id = f"disp_{uuid.uuid4().hex[:12]}"
        estimated_cost = float(schedule.target_refs.get("estimated_cost_usd", 0.05))

        if schedule.budget_limit_usd is not None and estimated_cost > schedule.budget_limit_usd:
            return self._save_budget_skip(
                schedule,
                current_due=current_due,
                next_due=next_due,
                now=now,
                missed_count_delta=missed_count_delta,
                logical_key=logical_key,
                dispatch_id=dispatch_id,
                estimated_cost=estimated_cost,
            )

        return self._claim_and_create_run(
            schedule,
            current_due=current_due,
            next_due=next_due,
            now=now,
            missed_count_delta=missed_count_delta,
            logical_key=logical_key,
            dispatch_id=dispatch_id,
            estimated_cost=estimated_cost,
        )

    def scan_and_dispatch_due_schedules(
        self,
        now_utc: datetime | None = None,
        max_catchup_runs: int = 1,
    ) -> list[ScheduleDispatchResult]:
        """Scans all enabled schedules and dispatches due evaluations with atomic logical-key deduping.

        Guarantees that dual schedulers, process restarts, or queue retries will never create duplicate
        logical evaluation runs (Spec 7.2, F06-T1).
        """
        del max_catchup_runs
        now = now_utc or datetime.now(timezone.utc)
        results: list[ScheduleDispatchResult] = []
        for schedule in self._gate_repo.list_schedules():
            if not schedule.is_enabled:
                continue
            result = self._dispatch_due_schedule(schedule, now=now)
            if result is not None:
                results.append(result)
        return results
