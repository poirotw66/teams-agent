"""Budget alert list / get routes."""

from __future__ import annotations

from fastapi import Depends, FastAPI


def register_budget_alert_read_routes(
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
    del (
        query_service,
        notification_dispatcher,
        evaluate_all_budgets,
        check_api_health_alerts,
        configured_targets,
    )

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
