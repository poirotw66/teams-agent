"""Model schedule-effect helpers for governance model routes."""

from __future__ import annotations

from .governance_domain import (
    GovernanceNotFoundError,
    GovernanceService,
    GovernanceTransitionError,
)

__all__ = ["run_model_schedule", "scheduled_model_id"]


def scheduled_model_id(items: list[dict[str, object]], *, config_id: str, version_id: str) -> str:
    for item in items:
        config = item.get("config") or {}
        if not isinstance(config, dict) or config.get("config_id") != config_id:
            continue
        versions = item.get("versions") or []
        if not isinstance(versions, list):
            continue
        for version in versions:
            if isinstance(version, dict) and version.get("version_id") == version_id:
                model_id = str(version.get("model_id") or "")
                if model_id:
                    return model_id
    raise GovernanceNotFoundError(version_id)


async def run_model_schedule(
    governance: GovernanceService,
    query_service: object,
    *,
    actor: object,
    config_id: str,
    version_id: str,
    reason: str,
    already_scheduled: bool = False,
) -> dict[str, object]:
    from .governance_domain.model_catalog import model_component
    from .services.model_effect import ModelEffectError, run_scheduled_effect
    from .services.runtime_models import load_agent_runtime_models

    settings = getattr(query_service, "_settings", None)
    agent_api_url = getattr(settings, "agent_api_url", None)
    runtime = await load_agent_runtime_models(agent_api_url)
    if not runtime.get("controlPlaneReady"):
        raise GovernanceTransitionError("model control plane is not connected")
    spec = model_component(config_id=config_id)
    if spec.effect == "next_request":
        raise GovernanceTransitionError("this component activates on the next request")
    listed = governance.list_models(actor=actor)
    model_id = scheduled_model_id(listed, config_id=config_id, version_id=version_id)
    portal_url = getattr(settings, "knowledge_internal_url", None) or getattr(
        settings, "knowledge_portal_url", None
    )
    token = getattr(settings, "service_token", "") or getattr(
        settings, "knowledge_service_token", ""
    )
    try:
        return await run_scheduled_effect(
            governance=governance,
            actor=actor,
            config_id=config_id,
            version_id=version_id,
            reason=reason,
            effect=spec.effect,
            model_id=model_id,
            agent_api_url=agent_api_url,
            portal_url=portal_url,
            service_token=token,
            already_scheduled=already_scheduled,
        )
    except ModelEffectError as exc:
        raise GovernanceTransitionError(exc.message) from exc
