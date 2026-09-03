from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .governance_domain import (
    GovernanceAuthorizationError,
    GovernanceConflictError,
    GovernanceError,
    GovernanceNotFoundError,
    GovernanceService,
    GovernanceTransitionError,
    GovernanceValidationError,
)


class PromptCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version: str
    taxonomy_version: str
    knowledge_release_id: str | None = None


class PromptApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)
    policy_exception_reason: str | None = None
    policy_exception_expires_at: datetime | None = None
    approved: bool | None = None


class PromptCanaryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    percent: int = Field(ge=1, le=99)
    environment: str = "prod"
    reason: str = Field(min_length=3)


class PromptCanaryStopBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)
    rollback: bool = False


class PromptCanaryEvaluateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_rate: float = Field(ge=0, le=1)
    negative_feedback_rate: float = Field(ge=0, le=1)
    handoff_rate: float = Field(ge=0, le=1)
    safety_alerts: int = Field(default=0, ge=0)
    sample_size: int = Field(ge=0)


class PromptActivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)
    emergency: bool = False


class PromptRollbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)


class ModelCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_id: str = "issue-extractor-model"
    provider: str
    model_id: str
    component: str = "issue-extractor"
    temperature: float = Field(default=0.0, ge=0, le=1)
    max_output_tokens: int = Field(default=2048, ge=1, le=8192)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    retry: int = Field(default=1, ge=0, le=3)
    secret_ref: str
    region: str = "asia-east1"
    pricing_version: str = "v1"
    fallback_model_id: str | None = None
    fallback_on: tuple[str, ...] = ()
    change_reason: str = Field(min_length=3)


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3)


class FallbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: Literal["TIMEOUT", "RATE_LIMIT", "UNAVAILABLE"]


class FlagCandidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flag_id: str
    value: str
    environment: str = "lab"
    expires_at: datetime | None = None
    percent: int | None = Field(default=None, ge=1, le=100)
    reason: str = Field(min_length=3)


class RoleRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_principal: str
    target_role: str | None = None
    add_capabilities: tuple[str, ...] = ()
    remove_capabilities: tuple[str, ...] = ()
    reason: str = Field(min_length=3)


class RevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: str
    reason: str = Field(min_length=3)


class RetentionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = "operational-events"
    ttl_days: int = Field(ge=1, le=3650)
    migration_plan: str = Field(min_length=3)
    reason: str = Field(min_length=3)


class MaskingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=3)


def register_governance_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    example_service,
    faq_service=None,
    query_service=None,
    quality_service=None,
) -> None:
    @app.exception_handler(GovernanceAuthorizationError)
    async def governance_authorization_handler(_request, exc: GovernanceAuthorizationError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(GovernanceNotFoundError)
    async def governance_not_found_handler(_request, exc: GovernanceNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(GovernanceConflictError)
    @app.exception_handler(GovernanceTransitionError)
    async def governance_conflict_handler(_request, exc: GovernanceError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(GovernanceValidationError)
    async def governance_validation_handler(_request, exc: GovernanceValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def _reject_client_approval(payload: PromptApproveBody) -> None:
        if payload.approved is not None:
            raise GovernanceValidationError("approved=true from the client is rejected")

    @app.get("/api/governance/prompts")
    async def list_governance_prompts(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return {"items": governance.list_prompts(actor=actor)}

    @app.get("/api/governance/prompts/{prompt_id}")
    async def governance_prompt_detail(prompt_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return governance.prompt_detail(prompt_id, actor=actor)

    @app.get("/api/governance/prompts/{prompt_id}/versions/{version_id}/diff")
    async def governance_prompt_diff(
        prompt_id: str, version_id: str, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return governance.prompt_diff(prompt_id, version_id, actor=actor)

    @app.post("/api/governance/prompts/{prompt_id}/candidates")
    async def create_governance_prompt_candidate(
        prompt_id: str,
        payload: PromptCandidateBody,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.candidates.create")
        verified = example_service.list_examples(actor=actor, status="VERIFIED")
        return governance.create_prompt_candidate(
            prompt_id=prompt_id,
            dataset_version=payload.dataset_version,
            taxonomy_version=payload.taxonomy_version,
            knowledge_release_id=payload.knowledge_release_id,
            verified_examples=verified,
            actor=actor,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )

    @app.post("/api/governance/prompts/{prompt_id}/versions/{version_id}/eval")
    async def eval_governance_prompt(
        prompt_id: str, version_id: str, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.eval.run")
        verified = example_service.list_examples(actor=actor, status="VERIFIED")
        return governance.run_prompt_eval(
            prompt_id=prompt_id,
            version_id=version_id,
            verified_examples=verified,
            actor=actor,
        )

    @app.post("/api/governance/prompts/{prompt_id}/versions/{version_id}/approve")
    async def approve_governance_prompt(
        prompt_id: str,
        version_id: str,
        payload: PromptApproveBody,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.approve")
        _reject_client_approval(payload)
        return governance.approve_prompt(
            prompt_id=prompt_id,
            version_id=version_id,
            reason=payload.reason,
            actor=actor,
            policy_exception_reason=payload.policy_exception_reason,
            policy_exception_expires_at=payload.policy_exception_expires_at,
        )

    @app.post("/api/governance/prompts/{prompt_id}/versions/{version_id}/canary")
    async def canary_governance_prompt(
        prompt_id: str,
        version_id: str,
        payload: PromptCanaryBody,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.canary")
        return governance.start_prompt_canary(
            prompt_id=prompt_id,
            version_id=version_id,
            percent=payload.percent,
            environment=payload.environment,
            reason=payload.reason,
            actor=actor,
        )

    @app.post("/api/governance/prompts/{prompt_id}/canary/stop")
    async def stop_governance_prompt_canary(
        prompt_id: str,
        payload: PromptCanaryStopBody,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.canary")
        return governance.stop_prompt_canary(
            prompt_id=prompt_id,
            reason=payload.reason,
            actor=actor,
            rollback=payload.rollback,
        )

    @app.post("/api/governance/prompts/{prompt_id}/canary/evaluate")
    async def evaluate_governance_prompt_canary(
        prompt_id: str,
        payload: PromptCanaryEvaluateBody,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.canary")
        return governance.evaluate_prompt_canary(
            prompt_id=prompt_id,
            error_rate=payload.error_rate,
            negative_feedback_rate=payload.negative_feedback_rate,
            handoff_rate=payload.handoff_rate,
            safety_alerts=payload.safety_alerts,
            sample_size=payload.sample_size,
            actor=actor,
        )

    @app.post("/api/governance/prompts/{prompt_id}/versions/{version_id}/activate")
    async def activate_governance_prompt(
        prompt_id: str,
        version_id: str,
        payload: PromptActivateBody,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.activate")
        return governance.activate_prompt(
            prompt_id=prompt_id,
            version_id=version_id,
            reason=payload.reason,
            actor=actor,
            emergency=payload.emergency,
        )

    @app.post("/api/governance/prompts/{prompt_id}/rollback")
    async def rollback_governance_prompt(
        prompt_id: str, payload: PromptRollbackBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.rollback")
        return governance.rollback_prompt(prompt_id=prompt_id, reason=payload.reason, actor=actor)

    @app.get("/api/governance/prompts/{prompt_id}/runtime")
    async def resolve_governance_prompt(
        prompt_id: str,
        conversation_id: str = Query(min_length=1),
        tenant: str = Query(default="default"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return governance.resolve_prompt(
            prompt_id, tenant=tenant, conversation_id=conversation_id, actor=actor
        )

    @app.get("/api/governance/models")
    async def list_governance_models(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.models.read")
        return {"items": governance.list_models(actor=actor)}

    @app.post("/api/governance/models/candidates")
    async def create_governance_model(payload: ModelCandidateBody, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.models.write")
        return governance.create_model_candidate(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/models/{config_id}/versions/{version_id}/eval")
    async def eval_governance_model(
        config_id: str, version_id: str, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.write")
        return governance.run_model_eval(config_id=config_id, version_id=version_id, actor=actor)

    @app.post("/api/governance/models/{config_id}/versions/{version_id}/approve")
    async def approve_governance_model(
        config_id: str, version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.approve")
        return governance.approve_model(
            config_id=config_id, version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/models/{config_id}/versions/{version_id}/activate")
    async def activate_governance_model(
        config_id: str, version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.activate")
        return governance.activate_model(
            config_id=config_id, version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/models/{config_id}/rollback")
    async def rollback_governance_model(
        config_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.activate")
        return governance.rollback_model(config_id=config_id, reason=payload.reason, actor=actor)

    @app.post("/api/governance/models/{config_id}/simulate-fallback")
    async def simulate_model_fallback(
        config_id: str, payload: FallbackBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.read")
        return governance.simulate_fallback(config_id=config_id, error=payload.error, actor=actor)

    @app.get("/api/governance/flags")
    async def list_governance_flags(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.flags.read")
        return {"items": governance.list_flags(actor=actor)}

    @app.post("/api/governance/flags/candidates")
    async def create_governance_flag(payload: FlagCandidateBody, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.flags.write")
        return governance.create_flag_candidate(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/flags/{flag_id}/versions/{version_id}/approve")
    async def approve_governance_flag(
        flag_id: str, version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.flags.approve")
        return governance.approve_flag(
            flag_id=flag_id, version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/flags/{flag_id}/versions/{version_id}/activate")
    async def activate_governance_flag(
        flag_id: str, version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.flags.activate")
        return governance.activate_flag(
            flag_id=flag_id, version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.get("/api/governance/flags/{flag_id}/effective")
    async def effective_governance_flag(
        flag_id: str,
        environment: str = Query(default="lab"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.flags.read")
        return governance.effective_flag(flag_id, actor=actor, environment=environment)

    @app.get("/api/governance/roles")
    async def list_role_changes(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.roles.read")
        return {"items": governance.list_role_changes(actor=actor)}

    @app.post("/api/governance/roles/requests")
    async def request_role_change(payload: RoleRequestBody, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.roles.request")
        return governance.request_role_change(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/roles/{change_id}/approve")
    async def approve_role_change(
        change_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.roles.approve")
        return governance.approve_role_change(change_id=change_id, reason=payload.reason, actor=actor)

    @app.post("/api/governance/roles/revoke")
    async def revoke_principal(payload: RevokeBody, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.roles.revoke")
        return governance.revoke_principal(principal=payload.principal, reason=payload.reason, actor=actor)

    @app.post("/api/governance/retention/candidates")
    async def create_retention(payload: RetentionBody, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.create_retention_candidate(**payload.model_dump(), actor=actor)

    @app.get("/api/governance/retention")
    async def list_retention(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.retention.read")
        return {"items": governance.list_retention_policies(actor=actor)}

    @app.post("/api/governance/retention/{version_id}/approve")
    async def approve_retention(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.approve_retention(version_id=version_id, reason=payload.reason, actor=actor)

    @app.post("/api/governance/retention/{version_id}/activate")
    async def activate_retention(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.activate_retention(version_id=version_id, reason=payload.reason, actor=actor)

    @app.get("/api/governance/masking")
    async def list_masking(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.retention.read")
        return {"items": governance.list_masking_policies(actor=actor)}

    @app.post("/api/governance/masking/candidates")
    async def create_masking(payload: MaskingBody, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.create_masking_candidate(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/masking/{version_id}/approve")
    async def approve_masking(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.approve_masking(version_id=version_id, reason=payload.reason, actor=actor)

    @app.post("/api/governance/masking/{version_id}/activate")
    async def activate_masking(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.activate_masking(version_id=version_id, reason=payload.reason, actor=actor)

    @app.get("/api/governance/search")
    async def governance_search(
        q: str = Query(default=""),
        doc_type: str | None = Query(default=None),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.search.read")
        extras: list[dict[str, object]] = []
        if faq_service is not None and actor.has_capability("ops.faq.read"):
            for item in faq_service.list_faqs(actor=actor):
                faq = item.get("faq") or {}
                version = item.get("version") or {}
                content = version.get("content") or {}
                extras.append(
                    {
                        "type": "FAQ",
                        "id": str(faq.get("faq_id") or ""),
                        "title": str(content.get("faq_key") or faq.get("faq_id") or ""),
                        "snippet": str(content.get("question") or version.get("status") or "")[:160],
                        "requiredCapability": "ops.faq.read",
                    }
                )
        if example_service is not None and actor.has_capability("ops.examples.read"):
            for item in example_service.list_examples(actor=actor)[:200]:
                extras.append(
                    {
                        "type": "EXAMPLE",
                        "id": str(item.get("example_id") or ""),
                        "title": str(item.get("expected_issue_type_id") or item.get("label") or ""),
                        "snippet": str(item.get("text") or "")[:160],
                        "requiredCapability": "ops.examples.read",
                    }
                )
        if query_service is not None and actor.has_capability("ops.issues.read"):
            taxonomy = getattr(query_service, "taxonomy", None)
            if taxonomy is not None:
                for issue in taxonomy.list_active():
                    issue_id = getattr(issue, "issue_type_id", None) or getattr(issue, "id", "")
                    display = getattr(issue, "display_name", None) or getattr(issue, "name", issue_id)
                    extras.append(
                        {
                            "type": "ISSUE_TYPE",
                            "id": str(issue_id),
                            "title": str(display),
                            "snippet": str(getattr(issue, "category", "") or ""),
                            "requiredCapability": "ops.issues.read",
                        }
                    )
        if quality_service is not None and actor.has_capability("ops.quality.read"):
            for case in quality_service.list_cases(actor=actor)[:200]:
                extras.append(
                    {
                        "type": "QUALITY_CASE",
                        "id": str(case.get("case_id") or ""),
                        "title": str(case.get("title") or case.get("status") or ""),
                        "snippet": str(case.get("description") or case.get("issue_type_id") or "")[
                            :160
                        ],
                        "requiredCapability": "ops.quality.read",
                    }
                )
        return governance.search(
            query=q, actor=actor, doc_type=doc_type, extra_documents=extras
        )

    @app.get("/api/governance/audit")
    async def governance_audit(
        target_type: str | None = Query(default=None),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.audit.read")
        return {"items": governance.list_audit(actor=actor, target_type=target_type)}

    @app.get("/api/governance/audit/export")
    async def governance_audit_export(
        target_type: str | None = Query(default=None),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.audit.read")
        return governance.export_audit(actor=actor, target_type=target_type)
