"""Prompt and eval-harness route registration for governance."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header, Query

from .governance_domain import GovernanceService, GovernanceValidationError
from .governance_route_models import (
    PromptActivateBody,
    PromptApproveBody,
    PromptCanaryBody,
    PromptCanaryEvaluateBody,
    PromptCanaryStopBody,
    PromptCandidateBody,
    PromptRollbackBody,
)

__all__ = ["register_prompt_routes"]


def _reject_client_approval(payload: PromptApproveBody) -> None:
    if payload.approved is not None:
        raise GovernanceValidationError("approved=true from the client is rejected")


def register_prompt_read_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    eval_harness_status=None,
) -> None:
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


def register_prompt_candidate_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    example_service,
) -> None:
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


def register_prompt_release_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
) -> None:
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


def register_prompt_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    example_service,
    eval_harness_status=None,
) -> None:
    register_prompt_read_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
        eval_harness_status=eval_harness_status,
    )
    register_prompt_candidate_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
        example_service=example_service,
    )
    register_prompt_release_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
    )
