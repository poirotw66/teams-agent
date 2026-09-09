from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query

from ..faq_domain import FaqNotFoundError
from ..request_models import (
    BudgetPolicyCreateRequest,
    BudgetPolicyStateRequest,
    BudgetPolicyUpdateRequest,
    FaqReasonRequest,
)


def register_budget_routes(
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

    @app.get("/api/alerts")
    async def list_alerts(
        alert_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        scope_type: str | None = None,
        scope_id: str | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.alerts.read")
        items = budget_service.list_alerts(
            actor=actor,
            alert_type=alert_type,
            severity=severity,
            status=status,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return {"items": items, "total": len(items)}

    @app.get("/api/alerts/{alert_id}")
    async def get_alert(alert_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.alerts.read")
        return {"alert": budget_service.alert_detail(alert_id, actor=actor)}

    @app.post("/api/alerts/{alert_id}/acknowledge")
    async def acknowledge_alert(
        alert_id: str,
        payload: FaqReasonRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.alerts.manage")
        return budget_service.change_alert(
            alert_id,
            action="ACKNOWLEDGE",
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            actor=actor,
        )

    @app.post("/api/alerts/{alert_id}/deliveries/{delivery_id}/retry")
    async def retry_alert_delivery(
        alert_id: str,
        delivery_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.alerts.manage")
        alert = budget_service.alert_detail(alert_id, actor=actor)
        if delivery_id not in {item["delivery_id"] for item in alert["deliveries"]}:
            raise FaqNotFoundError(delivery_id)
        result = budget_service.retry_delivery(delivery_id, actor=actor)
        delivery_item = result.get("delivery")
        if delivery_item:
            await notification_dispatcher.dispatch_delivery(delivery_item, actor=actor)
        updated_alert = budget_service.alert_detail(alert_id, actor=actor)
        updated_delivery = next(
            item for item in updated_alert["deliveries"] if item["delivery_id"] == delivery_id
        )
        return {"delivery": updated_delivery}

    @app.post("/api/alerts/{alert_id}/resolve")
    async def resolve_alert(
        alert_id: str,
        payload: FaqReasonRequest,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.alerts.manage")
        return budget_service.change_alert(
            alert_id,
            action="RESOLVE",
            expected_etag=payload.expected_etag,
            reason=payload.reason,
            actor=actor,
        )

