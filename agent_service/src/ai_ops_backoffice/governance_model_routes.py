"""Model catalog and schedule route registration for governance."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from .governance_domain import GovernanceService
from .governance_model_schedule import run_model_schedule
from .governance_route_models import FallbackBody, ModelCandidateBody, ReasonBody

__all__ = ["register_model_routes"]


def register_model_catalog_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    query_service=None,
) -> None:
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

    @app.post("/api/governance/models/{config_id}/simulate-fallback")
    async def simulate_model_fallback(
        config_id: str, payload: FallbackBody, actor=Depends(current_actor)
    ) -> dict[str, object]:
        require_capability(actor, "ops.models.read")
        return governance.simulate_fallback(config_id=config_id, error=payload.error, actor=actor)


def register_model_schedule_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    query_service=None,
) -> None:
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


def register_model_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    query_service=None,
) -> None:
    register_model_catalog_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
        query_service=query_service,
    )
    register_model_schedule_routes(
        app,
        governance=governance,
        current_actor=current_actor,
        require_capability=require_capability,
        query_service=query_service,
    )
