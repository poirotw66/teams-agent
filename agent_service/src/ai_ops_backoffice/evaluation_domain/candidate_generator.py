"""Candidate evaluation case generation jobs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from operations_core.access import ActorContext

from .candidate_case_build import build_synthetic_candidate_case
from .errors import EvaluationNotFoundError, EvaluationValidationError
from .models import CandidateGenerationJob
from .service import EvaluationService


class CandidateGenerationManager:
    def __init__(self, service: EvaluationService) -> None:
        self._service = service

    def start_generation_job(
        self,
        *,
        source_refs: tuple[dict[str, Any], ...],
        target_types: tuple[str, ...],
        requested_count: int,
        owner_unit_id: str,
        actor: ActorContext,
        limits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._service._authorize(actor, "ops.evals.write", owner_unit_id)
        if requested_count <= 0 or requested_count > 100:
            raise EvaluationValidationError("requested_count must be between 1 and 100")
        if not source_refs:
            raise EvaluationValidationError("source_refs must not be empty")

        now = datetime.now(UTC)
        job_id = f"candjob_{uuid.uuid4().hex[:12]}"
        limits_resolved = limits or {"max_tokens": 8000, "max_cost_usd": 0.50}
        created_case_ids = self._create_candidate_cases(
            source_refs=source_refs,
            target_types=target_types,
            requested_count=requested_count,
            owner_unit_id=owner_unit_id,
            actor=actor,
            limits_resolved=limits_resolved,
        )
        tokens_per_case = 150
        cost_per_case = 0.002
        total_tokens = tokens_per_case * len(created_case_ids)
        total_cost = cost_per_case * len(created_case_ids)

        job = CandidateGenerationJob(
            job_id=job_id,
            tenant_id=actor.tenant_id or "local-development",
            owner_unit_id=owner_unit_id,
            source_refs=source_refs,
            target_types=target_types,
            requested_count=requested_count,
            limits=limits_resolved,
            status="COMPLETED",
            created_candidate_case_ids=tuple(created_case_ids),
            used_tokens=total_tokens,
            estimated_cost_usd=round(total_cost, 4),
            error_message=None,
            created_by=actor.user_id,
            created_at=now,
            updated_at=datetime.now(UTC),
        )
        state = self._service._repo.load()
        new_state = state.model_copy(update={"candidate_jobs": (*state.candidate_jobs, job)})
        self._service._repo.commit_mutation(new_state, expected_revision=state.revision)
        return job.model_dump(mode="json")

    def _create_candidate_cases(
        self,
        *,
        source_refs: tuple[dict[str, Any], ...],
        target_types: tuple[str, ...],
        requested_count: int,
        owner_unit_id: str,
        actor: ActorContext,
        limits_resolved: dict[str, Any],
    ) -> list[str]:
        created_case_ids: list[str] = []
        tokens_per_case = 150
        cost_per_case = 0.002
        total_tokens = 0
        total_cost = 0.0
        for i in range(requested_count):
            if total_tokens + tokens_per_case > limits_resolved.get("max_tokens", 8000):
                break
            if total_cost + cost_per_case > limits_resolved.get("max_cost_usd", 0.50):
                break
            source_ref = source_refs[i % len(source_refs)]
            behavior = (
                target_types[i % len(target_types)] if target_types else "ANSWER_WITH_CITATION"
            )
            case_args = build_synthetic_candidate_case(
                index=i, source_ref=source_ref, behavior=behavior
            )
            case_res = self._service.create_case(
                title=case_args["title"],
                query=case_args["query"],
                owner_unit_id=owner_unit_id,
                behavior=case_args["behavior"],  # type: ignore[arg-type]
                criteria=case_args["criteria"],
                evidence=case_args["evidence"],
                tags=case_args["tags"],
                criticality=case_args["criticality"],
                provenance=case_args["provenance"],
                actor=actor,
            )
            created_case_ids.append(case_res["case"]["case_id"])
            total_tokens += tokens_per_case
            total_cost += cost_per_case
        return created_case_ids

    def get_job_status(self, job_id: str, *, actor: ActorContext) -> dict[str, Any]:
        self._service._authorize(actor, "ops.evals.read")
        job = self._service._repo.get_candidate_job(job_id)
        if not job:
            raise EvaluationNotFoundError(f"Candidate job {job_id} not found")
        self._service._authorize(actor, "ops.evals.read", job.owner_unit_id)
        return job.model_dump(mode="json")
