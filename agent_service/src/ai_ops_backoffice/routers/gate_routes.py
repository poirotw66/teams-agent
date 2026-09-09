from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Query
from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext

from ..evaluation_domain.gate_service import QualityGateService


class CreateGatePolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str
    name: str
    description: str = ""
    mode: Literal["REPORT_ONLY", "ENFORCE"] = "REPORT_ONLY"
    minimum_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_pass_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    max_regression_count: int = Field(default=0, ge=0)
    required_set_version_ids: list[str] | None = None


class CreatePolicyVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    mode: Literal["REPORT_ONLY", "ENFORCE"] = "REPORT_ONLY"
    minimum_coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    minimum_pass_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    max_regression_count: int = Field(default=0, ge=0)
    required_set_version_ids: list[str] | None = None


class ActivatePolicyVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["REPORT_ONLY", "ENFORCE"] | None = None


class EvaluateDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str
    policy_version: int | None = None
    run_id: str
    target_manifest_hash: str


class RequestExceptionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    validity_hours: int = Field(default=24, ge=1, le=168)


class CreateSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_id: str
    name: str
    set_version_id: str
    frequency: Literal["HOURLY", "DAILY", "WEEKLY", "ON_CHANGE"] = "DAILY"
    budget_limit_usd: float = Field(default=5.0, gt=0.0)
    target_refs: dict[str, Any] = Field(default_factory=dict)


class UpdateSchedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool | None = None
    frequency: Literal["HOURLY", "DAILY", "WEEKLY", "ON_CHANGE"] | None = None
    budget_limit_usd: float | None = Field(default=None, gt=0.0)
    target_refs: dict[str, Any] | None = None


class VerifyReleasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_manifest_hash: str
    policy_id: str = "default-gate-policy"


class CreateQualityCasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_cause: str


def register_gate_routes(
    app: FastAPI,
    gate_service: QualityGateService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
    router = APIRouter(prefix="/api/evaluations", tags=["Quality Gates"])

    # 1. Gate Policies
    @router.get("/gate-policies")
    async def list_gate_policies(actor: ActorContext = Depends(current_actor)) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        policies = gate_service.repository.list_policies()
        return [p.model_dump(mode="json") for p in policies]

    @router.post("/gate-policies")
    async def create_gate_policy(
        payload: CreateGatePolicyPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        tenant_id = actor.tenant_id or "default"
        pol, ver = gate_service.create_policy(
            policy_id=payload.policy_id,
            tenant_id=tenant_id,
            name=payload.name,
            created_by=actor.user_id,
            description=payload.description,
            mode=payload.mode,
            minimum_coverage=payload.minimum_coverage,
            minimum_pass_rate=payload.minimum_pass_rate,
            max_regression_count=payload.max_regression_count,
            required_set_version_ids=payload.required_set_version_ids,
        )
        return {
            "policy": pol.model_dump(mode="json"),
            "version": ver.model_dump(mode="json"),
        }

    @router.get("/gate-policies/{policy_id}")
    async def get_gate_policy(
        policy_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        policy = gate_service.repository.get_policy(policy_id)
        if not policy:
            return {"error": f"Gate policy '{policy_id}' not found"}
        versions = gate_service.repository.list_versions(policy_id)
        return {
            "policy": policy.model_dump(mode="json"),
            "versions": [v.model_dump(mode="json") for v in versions],
        }

    @router.post("/gate-policies/{policy_id}/versions")
    async def create_policy_version(
        policy_id: str,
        payload: CreatePolicyVersionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        version = gate_service.create_policy_version(
            policy_id=policy_id,
            name=payload.name,
            created_by=actor.user_id,
            description=payload.description,
            mode=payload.mode,
            minimum_coverage=payload.minimum_coverage,
            minimum_pass_rate=payload.minimum_pass_rate,
            max_regression_count=payload.max_regression_count,
            required_set_version_ids=payload.required_set_version_ids,
        )
        return {"version": version.model_dump(mode="json")}

    @router.post("/gate-policies/{policy_id}/versions/{version}/approve")
    async def approve_policy_version(
        policy_id: str,
        version: int,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.review")
        approved = gate_service.approve_policy_version(
            policy_id=policy_id,
            version=version,
            approved_by=actor.user_id,
        )
        return {"version": approved.model_dump(mode="json")}

    @router.post("/gate-policies/{policy_id}/versions/{version}/activate")
    async def activate_policy_version(
        policy_id: str,
        version: int,
        payload: ActivatePolicyVersionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.gates.manage")
        activated = gate_service.activate_policy_version(
            policy_id=policy_id,
            version=version,
            mode=payload.mode,
            actor=actor,
        )
        return {"version": activated.model_dump(mode="json")}

    # 2. Decisions & Exceptions
    @router.post("/gate-decisions")
    async def evaluate_decision(
        payload: EvaluateDecisionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        decision = gate_service.evaluate_decision(
            policy_id=payload.policy_id,
            policy_version=payload.policy_version,
            run_id=payload.run_id,
            target_manifest_hash=payload.target_manifest_hash,
            actor=actor,
        )
        return {"decision": decision.model_dump(mode="json")}

    @router.get("/gate-decisions")
    async def list_decisions(
        target_manifest_hash: str | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        decisions = gate_service.repository.list_decisions(target_manifest_hash=target_manifest_hash)
        return [d.model_dump(mode="json") for d in decisions]

    @router.get("/gate-decisions/{decision_id}")
    async def get_decision(
        decision_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        decision = gate_service.repository.get_decision(decision_id)
        if not decision:
            return {"error": f"Gate decision '{decision_id}' not found"}
        return {"decision": decision.model_dump(mode="json")}

    @router.post("/gate-decisions/{decision_id}/exceptions")
    async def request_exception(
        decision_id: str,
        payload: RequestExceptionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        exc = gate_service.request_exception(
            decision_id=decision_id,
            reason=payload.reason,
            requested_by=actor.user_id,
            validity_hours=payload.validity_hours,
        )
        return {"exception": exc.model_dump(mode="json")}

    @router.post("/exceptions/{exception_id}/approve")
    async def approve_exception(
        exception_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.gates.manage")
        approved = gate_service.approve_exception(
            exception_id=exception_id,
            approver_id=actor.user_id,
        )
        return {"exception": approved.model_dump(mode="json")}

    # 3. Source Impacts
    @router.get("/source-impacts")
    async def get_source_impacts(
        source_type: str = Query(...),
        source_id: str = Query(...),
        source_version: str | None = Query(default=None),
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        impact = gate_service.analyze_source_impact(
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
        )
        return {"impact": impact.model_dump(mode="json")}

    # 4. Schedules
    @router.get("/schedules")
    async def list_schedules(actor: ActorContext = Depends(current_actor)) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        schedules = gate_service.repository.list_schedules()
        return [s.model_dump(mode="json") for s in schedules]

    @router.post("/schedules")
    async def create_schedule(
        payload: CreateSchedulePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        tenant_id = actor.tenant_id or "default"
        schedule = gate_service.create_schedule(
            schedule_id=payload.schedule_id,
            tenant_id=tenant_id,
            name=payload.name,
            set_version_id=payload.set_version_id,
            frequency=payload.frequency,
            budget_limit_usd=payload.budget_limit_usd,
            target_refs=payload.target_refs,
            created_by=actor.user_id,
        )
        return {"schedule": schedule.model_dump(mode="json")}

    @router.patch("/schedules/{schedule_id}")
    async def update_schedule(
        schedule_id: str,
        payload: UpdateSchedulePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        schedule = gate_service.update_schedule(
            schedule_id=schedule_id,
            is_enabled=payload.is_enabled,
            frequency=payload.frequency,
            budget_limit_usd=payload.budget_limit_usd,
            target_refs=payload.target_refs,
            updated_by=actor.user_id,
        )
        return {"schedule": schedule.model_dump(mode="json")}

    # 5. Release Verification
    @router.post("/verify-release")
    async def verify_release(
        payload: VerifyReleasePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        res = gate_service.verify_release_gate(
            target_manifest_hash=payload.target_manifest_hash,
            policy_id=payload.policy_id,
        )
        return res

    # 6. Quality Case Loop
    @router.post("/runs/{run_id}/cases/{execution_id}/quality-case")
    async def link_quality_case(
        run_id: str,
        execution_id: str,
        payload: CreateQualityCasePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        case_link = gate_service.link_quality_case(
            run_id=run_id,
            execution_id=execution_id,
            root_cause=payload.root_cause,
            actor=actor,
        )
        return {"quality_case": case_link.model_dump(mode="json")}

    app.include_router(router)
