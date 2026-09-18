"""Budget policy evaluate and health-check alert routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI


def register_budget_evaluate_routes(
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
    del configured_targets

    @app.post("/api/budget-policies/{policy_id}/evaluate")
    async def evaluate_budget_policy(
        policy_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.evaluate")
        policy = budget_service.policy_detail(policy_id, actor=actor)
        usage = await query_service.budget_usage(
            actor,
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            period_type=str(policy["period"]),
            measure=str(policy["measure"]),
        )
        result = budget_service.evaluate(
            policy_id,
            period_key=str(usage["periodKey"]),
            actual_value=float(usage["actualValue"]),
            coverage=float(usage["coverage"]),
            pricing_version=str(usage["pricingVersion"]),
            exchange_rate_version=str(usage["exchangeRateVersion"]),
            actor=actor,
        )
        if result.get("triggered") and result.get("alert"):
            await notification_dispatcher.dispatch_for_alert(
                result["alert"]["alert_id"],
                actor=actor,
            )
        return {**result, "usage": usage}

    @app.post("/api/budget-policies/evaluate-all")
    async def evaluate_all_policies(
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.budget.evaluate")
        return await evaluate_all_budgets(actor)

    @app.post("/api/health/check-alerts")
    async def trigger_health_check_alerts(
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.health.read")
        alerts = await check_api_health_alerts(actor)
        return {"checked": True, "triggeredAlerts": alerts}
