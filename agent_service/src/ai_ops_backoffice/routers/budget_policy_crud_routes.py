"""Budget policy list / create / update / state routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from ..request_models import (
    BudgetPolicyCreateRequest,
    BudgetPolicyStateRequest,
    BudgetPolicyUpdateRequest,
)


def register_budget_policy_crud_routes(
    app: FastAPI,
    *,
    budget_service,
    query_service,
    notification_dispatcher,
    evaluate_all_budgets,
    check_api_health_alerts,
    configured_targets: dict[str, str],
    current_actor,
    require_capability,
) -> None:
    del notification_dispatcher, evaluate_all_budgets, check_api_health_alerts

    @app.get("/api/budget-policies")
    async def list_budget_policies(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.budget.read")
        items = budget_service.list_policies(actor=actor)
        return {
            "items": items,
            "total": len(items),
            "notificationTargets": sorted(configured_targets),
        }

    @app.get("/api/budget-policies/{policy_id}")
    async def get_budget_policy(
        policy_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.read")
        return {"policy": budget_service.policy_detail(policy_id, actor=actor)}

    @app.post("/api/budget-policies")
    async def create_budget_policy(
        payload: BudgetPolicyCreateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.write")
        definitions = query_service.metrics_definitions()
        return budget_service.create_policy(
            **payload.model_dump(),
            pricing_version=str(definitions["pricingVersion"]),
            exchange_rate_version=str(
                definitions.get("exchangeRateVersion") or definitions["pricingVersion"]
            ),
            actor=actor,
        )

    @app.put("/api/budget-policies/{policy_id}")
    async def update_budget_policy(
        policy_id: str,
        payload: BudgetPolicyUpdateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.write")
        return budget_service.update_policy(policy_id, **payload.model_dump(), actor=actor)

    @app.post("/api/budget-policies/{policy_id}/state")
    async def set_budget_policy_state(
        policy_id: str,
        payload: BudgetPolicyStateRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.write")
        return budget_service.set_policy_enabled(
            policy_id,
            enabled=payload.enabled,
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            actor=actor,
        )
