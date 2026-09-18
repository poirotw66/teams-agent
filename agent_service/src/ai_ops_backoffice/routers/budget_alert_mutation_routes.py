"""Budget alert acknowledge / retry / resolve routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from ..request_models import FaqReasonRequest
from .budget_alert_retry import retry_alert_delivery_action


def register_budget_alert_mutation_routes(
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
    del query_service, evaluate_all_budgets, check_api_health_alerts, configured_targets

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
        return await retry_alert_delivery_action(
            budget_service=budget_service,
            notification_dispatcher=notification_dispatcher,
            alert_id=alert_id,
            delivery_id=delivery_id,
            actor=actor,
        )

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
