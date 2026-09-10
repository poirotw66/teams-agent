from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext

from ..evaluation_domain import (
    CandidateGenerationManager,
    EvaluationCriteria,
    EvaluationImportExportManager,
    EvaluationService,
    EvidenceItem,
    EvidenceRequirement,
    ProvenanceSpec,
)


class CaseCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1)
    owner_unit_id: str
    behavior: Literal[
        "ANSWER_WITH_CITATION",
        "CLARIFY",
        "REFUSE",
        "HANDOFF",
        "TOOL_TASK",
    ] = "ANSWER_WITH_CITATION"
    reference_answer: str | None = None
    required_facts: list[dict[str, Any]] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    criticality: Literal["CRITICAL", "NORMAL"] = "NORMAL"
    source_type: Literal[
        "MANUAL",
        "QUALITY_CASE",
        "FAQ",
        "DOCUMENT",
        "CONVERSATION",
        "SYNTHETIC",
    ] = "MANUAL"
    source_id: str | None = None
    source_version_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RevisionCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    base_revision_id: str | None = None
    behavior: Literal[
        "ANSWER_WITH_CITATION",
        "CLARIFY",
        "REFUSE",
        "HANDOFF",
        "TOOL_TASK",
    ] | None = None
    reference_answer: str | None = None
    required_facts: list[dict[str, Any]] | None = None
    forbidden_claims: list[str] | None = None
    tags: list[str] | None = None
    criticality: Literal["CRITICAL", "NORMAL"] | None = None


class SubmitRevisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_etag: int = Field(ge=1)


class ReviewRevisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    reason: str = Field(min_length=1)
    expected_etag: int = Field(ge=1)


class RetireCasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)


class SetCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    owner_unit_ids: list[str] = Field(min_length=1)
    purpose: Literal["DEVELOPMENT", "HOLDOUT"] = "DEVELOPMENT"
    description: str = ""


class SetVersionDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_revision_ids: list[str] = Field(min_length=1)


class PublishSetVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_etag: int = Field(ge=1)


class ImportValidatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    file_format: Literal["JSONL", "CSV"] = "JSONL"
    owner_unit_id: str


class ExportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    set_id: str | None = None
    file_format: Literal["JSONL", "CSV"] = "JSONL"


class CandidateJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_refs: list[dict[str, Any]] = Field(min_length=1)
    target_types: list[str] = Field(default_factory=lambda: ["ANSWER_WITH_CITATION"])
    requested_count: int = Field(default=5, ge=1, le=100)
    owner_unit_id: str
    limits: dict[str, Any] = Field(default_factory=dict)


def register_evaluation_routes(
    app: FastAPI,
    *,
    evaluation_service: EvaluationService,
    import_export_manager: EvaluationImportExportManager,
    candidate_manager: CandidateGenerationManager,
    current_actor: Any,
    require_capability: Any,
) -> None:
    router = APIRouter(prefix="/api/evaluations", tags=["Golden Eval Set"])

    @router.get("/cases")
    async def list_cases(
        q: str | None = None,
        owner_unit_id: str | None = None,
        status: str | None = None,
        behavior: str | None = None,
        criticality: str | None = None,
        source_health: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        items = evaluation_service.list_cases(
            actor=actor,
            q=q,
            owner_unit_id=owner_unit_id,
            status=status,
            behavior=behavior,
            criticality=criticality,
            source_health=source_health,
            source_type=source_type,
            source_id=source_id,
            limit=limit,
        )
        return {"items": items, "total": len(items)}

    @router.post("/cases", status_code=201)
    async def create_case(
        payload: CaseCreatePayload,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")

        from ..evaluation_domain.models import CriterionItem

        crit_items = tuple(CriterionItem(**c) for c in payload.required_facts)
        criteria = EvaluationCriteria(
            required_facts=crit_items,
            forbidden_claims=tuple(payload.forbidden_claims),
            reference_answer=payload.reference_answer,
        )

        evidence_reqs: list[EvidenceRequirement] = []
        for ev in payload.evidence:
            items = tuple(EvidenceItem(**item) for item in ev.get("items", []))
            evidence_reqs.append(EvidenceRequirement(group_id=ev.get("group_id", "default"), items=items))

        provenance = ProvenanceSpec(
            source_type=payload.source_type,
            source_id=payload.source_id or f"manual:{actor.user_id}",
            source_version_id=payload.source_version_id,
        )

        return evaluation_service.create_case(
            title=payload.title,
            query=payload.query,
            owner_unit_id=payload.owner_unit_id,
            behavior=payload.behavior,
            criteria=criteria,
            evidence=tuple(evidence_reqs),
            tags=tuple(payload.tags),
            criticality=payload.criticality,
            provenance=provenance,
            actor=actor,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @router.get("/cases/{case_id}")
    async def get_case(
        case_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return evaluation_service.get_case_detail(case_id, actor=actor)

    @router.post("/cases/{case_id}/revisions", status_code=201)
    async def create_revision(
        case_id: str,
        payload: RevisionCreatePayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.create_revision(
            case_id,
            query=payload.query,
            base_revision_id=payload.base_revision_id,
            behavior=payload.behavior,
            tags=tuple(payload.tags) if payload.tags is not None else None,
            criticality=payload.criticality,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/cases/{case_id}/revisions/{revision_id}/submit")
    async def submit_revision(
        case_id: str,
        revision_id: str,
        payload: SubmitRevisionPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.submit_revision(
            revision_id,
            expected_etag=payload.expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/cases/{case_id}/revisions/{revision_id}/review")
    async def review_revision(
        case_id: str,
        revision_id: str,
        payload: ReviewRevisionPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.review")
        return evaluation_service.review_revision(
            revision_id,
            approve=payload.approve,
            reason=payload.reason,
            expected_etag=payload.expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/cases/{case_id}/retire")
    async def retire_case(
        case_id: str,
        payload: RetireCasePayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.retire_case(
            case_id,
            reason=payload.reason,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.get("/sets")
    async def list_sets(
        purpose: Literal["DEVELOPMENT", "HOLDOUT"] | None = None,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        items = evaluation_service.list_sets(actor=actor, purpose=purpose)
        return {"items": items, "total": len(items)}

    @router.post("/sets", status_code=201)
    async def create_set(
        payload: SetCreatePayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.create_set(
            name=payload.name,
            owner_unit_ids=tuple(payload.owner_unit_ids),
            purpose=payload.purpose,
            description=payload.description,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.get("/sets/{set_id}")
    async def get_set(
        set_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return evaluation_service.get_set_detail(set_id, actor=actor)

    @router.post("/sets/{set_id}/versions", status_code=201)
    async def create_set_version_draft(
        set_id: str,
        payload: SetVersionDraftPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return evaluation_service.create_set_version_draft(
            set_id,
            case_revision_ids=tuple(payload.case_revision_ids),
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/sets/{set_id}/versions/{version_id}/publish")
    async def publish_set_version(
        set_id: str,
        version_id: str,
        payload: PublishSetVersionPayload,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.sets.publish")
        return evaluation_service.publish_set_version(
            version_id,
            expected_etag=payload.expected_etag,
            actor=actor,
            correlation_id=correlation_id,
        )

    @router.post("/imports/validate")
    async def validate_import(
        payload: ImportValidatePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        res = import_export_manager.validate_import(
            payload.content,
            file_format=payload.file_format,
            owner_unit_id=payload.owner_unit_id,
            actor=actor,
        )
        return res.model_dump(mode="json")

    @router.post("/imports/{staged_id}/commit")
    async def commit_import(
        staged_id: str,
        owner_unit_id: str = Query(...),
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        created_ids = import_export_manager.commit_staged_import(
            staged_id,
            owner_unit_id=owner_unit_id,
            actor=actor,
            correlation_id=correlation_id,
        )
        return {"created_case_ids": created_ids, "total": len(created_ids)}

    @router.post("/exports")
    async def export_cases(
        payload: ExportPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.export")
        data = import_export_manager.export_cases(
            actor=actor,
            set_id=payload.set_id,
            file_format=payload.file_format,
        )
        return {"content": data, "file_format": payload.file_format}

    @router.post("/candidate-jobs", status_code=202)
    async def start_candidate_job(
        payload: CandidateJobPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        job = candidate_manager.start_generation_job(
            source_refs=tuple(payload.source_refs),
            target_types=tuple(payload.target_types),
            requested_count=payload.requested_count,
            owner_unit_id=payload.owner_unit_id,
            actor=actor,
            limits=payload.limits,
        )
        return job

    @router.get("/candidate-jobs/{job_id}")
    async def get_candidate_job(
        job_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        return candidate_manager.get_job_status(job_id, actor=actor)

    @router.post("/candidate-jobs/{job_id}/cancel")
    async def cancel_candidate_job(
        job_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        return candidate_manager.cancel_job(job_id, actor=actor)

    app.include_router(router)
