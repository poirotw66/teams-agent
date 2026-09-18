"""Governance HTTP route registration.

Request bodies, search extras, and model schedule helpers live in sibling
modules; this module owns exception handlers and route endpoints.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, Query

from .governance_audit_routes import register_audit_routes
from .governance_domain import GovernanceService, GovernanceValidationError
from .governance_model_schedule import run_model_schedule, scheduled_model_id
from .governance_route_errors import register_governance_exception_handlers
from .governance_route_models import (
    FallbackBody,
    FlagCandidateBody,
    MaskingBody,
    ModelCandidateBody,
    PromptActivateBody,
    PromptApproveBody,
    PromptCanaryBody,
    PromptCanaryEvaluateBody,
    PromptCanaryStopBody,
    PromptCandidateBody,
    PromptRollbackBody,
    ReasonBody,
    RetentionBody,
    RevokeBody,
    RoleRequestBody,
)
from .governance_search_ops import collect_search_extras

# Re-export body models for stable importers / OpenAPI discovery.
__all__ = [
    "FallbackBody",
    "FlagCandidateBody",
    "MaskingBody",
    "ModelCandidateBody",
    "PromptActivateBody",
    "PromptApproveBody",
    "PromptCanaryBody",
    "PromptCanaryEvaluateBody",
    "PromptCanaryStopBody",
    "PromptCandidateBody",
    "PromptRollbackBody",
    "ReasonBody",
    "RetentionBody",
    "RevokeBody",
    "RoleRequestBody",
    "register_governance_routes",
]

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
    eval_harness_status=None,
) -> None:
    register_governance_exception_handlers(app)

    def _reject_client_approval(payload: PromptApproveBody) -> None:
        if payload.approved is not None:
            raise GovernanceValidationError("approved=true from the client is rejected")

    @app.get("/api/governance/eval-harness")
    async def governance_eval_harness_status(actor=Depends(current_actor)) -> dict[str, object]:
        """Surface formal eval wiring state for operators (unset / unavailable / ready)."""
        require_capability(actor, "ops.prompts.read")
        if eval_harness_status is None:
            return {
                "name": "unset",
                "available": False,
                "releaseEligible": False,
                "mode": "unset",
                "detail": "eval_harness_not_configured",
                "configured": False,
            }
        as_dict = getattr(eval_harness_status, "as_dict", None)
        if callable(as_dict):
            return as_dict()
        return dict(eval_harness_status)

    @app.get("/api/governance/prompts")
    async def list_governance_prompts(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return {"items": governance.list_prompts(actor=actor)}

    @app.get("/api/governance/prompts/{prompt_id}")
    async def governance_prompt_detail(
        prompt_id: str, actor=Depends(current_actor)
    ) -> dict[str, object]:
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
        return await governance.run_prompt_eval(
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
        from .governance_domain.model_catalog import component_catalog_payload
        from .services.runtime_models import load_agent_runtime_models

        agent_api_url = getattr(getattr(query_service, "_settings", None), "agent_api_url", None)
        runtime = await load_agent_runtime_models(agent_api_url)
        return {
            "items": governance.list_models(actor=actor),
            "runtime": runtime,
            "components": component_catalog_payload(),
        }

    @app.post("/api/governance/models/candidates")
    async def create_governance_model(
        payload: ModelCandidateBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
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

    @app.post("/api/governance/models/{config_id}/versions/{version_id}/schedule")
    async def schedule_governance_model(
        config_id: str, version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.activate")
        return await run_model_schedule(
            governance,
            query_service,
            actor=actor,
            config_id=config_id,
            version_id=version_id,
            reason=payload.reason,
        )

    @app.post("/api/governance/models/{config_id}/rollback")
    async def rollback_governance_model(
        config_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.activate")
        rolled = governance.rollback_model(config_id=config_id, reason=payload.reason, actor=actor)
        if not rolled.get("scheduled"):
            return rolled
        version = rolled.get("version") or {}
        version_id = str(version.get("version_id") or "")
        if not version_id:
            return rolled
        return await run_model_schedule(
            governance,
            query_service,
            actor=actor,
            config_id=config_id,
            version_id=version_id,
            reason=payload.reason,
            already_scheduled=True,
        )

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
    async def create_governance_flag(
        payload: FlagCandidateBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
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
    async def request_role_change(
        payload: RoleRequestBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.roles.request")
        return governance.request_role_change(**payload.model_dump(), actor=actor)

    @app.post("/api/governance/roles/{change_id}/approve")
    async def approve_role_change(
        change_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.roles.approve")
        return governance.approve_role_change(
            change_id=change_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/roles/revoke")
    async def revoke_principal(
        payload: RevokeBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.roles.revoke")
        return governance.revoke_principal(
            principal=payload.principal, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/retention/candidates")
    async def create_retention(
        payload: RetentionBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
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
        return governance.approve_retention(
            version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.post("/api/governance/retention/{version_id}/activate")
    async def activate_retention(
        version_id: str, payload: ReasonBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.retention.write")
        return governance.activate_retention(
            version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.get("/api/governance/masking")
    async def list_masking(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.retention.read")
        return {"items": governance.list_masking_policies(actor=actor)}

    @app.post("/api/governance/masking/candidates")
    async def create_masking(
        payload: MaskingBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
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
        return governance.activate_masking(
            version_id=version_id, reason=payload.reason, actor=actor
        )

    @app.get("/api/governance/search")
    async def governance_search(
        q: str = Query(default=""),
        doc_type: str | None = Query(default=None),
        owner_unit_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.search.read")
        extras, warnings = await collect_search_extras(
            actor=actor,
            query=q,
            faq_service=faq_service,
            example_service=example_service,
            query_service=query_service,
            quality_service=quality_service,
        )
        res = governance.search(
            query=q,
            actor=actor,
            doc_type=doc_type,
            owner_unit_id=owner_unit_id,
            status=status,
            extra_documents=extras,
        )
        res["warnings"] = warnings
        return res


    register_audit_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )


# Stable private aliases (historical underscore names).
_run_model_schedule = run_model_schedule
_scheduled_model_id = scheduled_model_id
