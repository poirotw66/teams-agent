from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from agent_service.operations.access import ActorContext

from .errors import EvaluationNotFoundError, EvaluationValidationError
from .models import (
    CandidateGenerationJob,
    CriterionItem,
    EvaluationCriteria,
    EvidenceItem,
    EvidenceRequirement,
    ProvenanceSpec,
)
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
            s_type = source_ref.get("source_type", "FAQ")
            s_id = source_ref.get("source_id", "faq_unknown")
            s_version = source_ref.get("version_id", "v1")
            s_title = source_ref.get("title", f"Source {s_id}")

            behavior = target_types[i % len(target_types)] if target_types else "ANSWER_WITH_CITATION"
            query_prefix = {
                "ANSWER_WITH_CITATION": "請問關於",
                "CLARIFY": "如何申請",
                "REFUSE": "請提供外部非公開機密",
                "HANDOFF": "我需要人工專員處理",
                "TOOL_TASK": "查詢我的目前狀態",
            }.get(behavior, "請問")

            query = f"{query_prefix}{s_title}的相關規範是什麼？（候選 #{i + 1}）"
            title = f"候選：{s_title} ({behavior})"

            evidence_item = EvidenceItem(
                evidence_id=f"ev_{i + 1}",
                source_type="FAQ" if s_type == "FAQ" else "DOCUMENT",
                source_id=s_id,
                version_id=s_version,
                text=f"來自 {s_title} 的內容依據",
            )
            evidence = (
                (EvidenceRequirement(group_id="primary", items=(evidence_item,)),)
                if behavior != "REFUSE"
                else ()
            )

            criteria = EvaluationCriteria(
                required_facts=(
                    CriterionItem(
                        criterion_id="crit_1",
                        description=f"回答應說明 {s_title} 的核心規定",
                        is_mandatory=True,
                    ),
                )
                if behavior != "REFUSE"
                else (),
                reference_answer=f"這是針對 {s_title} 的候選參考回答。" if behavior != "REFUSE" else None,
            )

            provenance = ProvenanceSpec(
                source_type="SYNTHETIC",
                source_id=s_id,
                source_version_id=s_version,
                generator_model="gemini-2.5-flash",
                generator_prompt_version="synth-eval-v1",
            )

            case_res = self._service.create_case(
                title=title,
                query=query,
                owner_unit_id=owner_unit_id,
                behavior=behavior,  # type: ignore[arg-type]
                criteria=criteria,
                evidence=evidence,
                tags=("synthetic", "candidate", behavior.lower()),
                criticality="NORMAL",
                provenance=provenance,
                actor=actor,
            )
            created_case_ids.append(case_res["case"]["case_id"])
            total_tokens += tokens_per_case
            total_cost += cost_per_case

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
        self._service._repo.commit_mutation(new_state)
        return job.model_dump(mode="json")

    def get_job_status(self, job_id: str, *, actor: ActorContext) -> dict[str, Any]:
        self._service._authorize(actor, "ops.evals.read")
        job = self._service._repo.get_candidate_job(job_id)
        if not job:
            raise EvaluationNotFoundError(f"Candidate job {job_id} not found")
        self._service._authorize(actor, "ops.evals.read", job.owner_unit_id)
        return job.model_dump(mode="json")

    def cancel_job(self, job_id: str, *, actor: ActorContext) -> dict[str, Any]:
        job = self._service._repo.get_candidate_job(job_id)
        if not job:
            raise EvaluationNotFoundError(f"Candidate job {job_id} not found")
        self._service._authorize(actor, "ops.evals.write", job.owner_unit_id)

        if job.status not in ("QUEUED", "RUNNING"):
            return job.model_dump(mode="json")

        cancelled_job = job.model_copy(
            update={"status": "CANCELLED", "updated_at": datetime.now(UTC)}
        )
        state = self._service._repo.load()
        updated_jobs = tuple(j if j.job_id != job_id else cancelled_job for j in state.candidate_jobs)
        new_state = state.model_copy(update={"candidate_jobs": updated_jobs})
        self._service._repo.commit_mutation(new_state)
        return cancelled_job.model_dump(mode="json")
