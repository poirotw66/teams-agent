"""Budget policy and alert HTTP routes (orchestrator)."""

from __future__ import annotations

from fastapi import FastAPI

from .budget_alert_mutation_routes import register_budget_alert_mutation_routes
from .budget_alert_read_routes import register_budget_alert_read_routes
from .budget_evaluate_routes import register_budget_evaluate_routes
from .budget_policy_crud_routes import register_budget_policy_crud_routes


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
    kwargs = dict(
        budget_service=budget_service,
        query_service=query_service,
        notification_dispatcher=notification_dispatcher,
        evaluate_all_budgets=evaluate_all_budgets,
        check_api_health_alerts=check_api_health_alerts,
        configured_targets=configured_targets,
        current_actor=current_actor,
        require_capability=require_capability,
    )
    register_budget_policy_crud_routes(app, **kwargs)
    register_budget_evaluate_routes(app, **kwargs)
    register_budget_alert_read_routes(app, **kwargs)
    register_budget_alert_mutation_routes(app, **kwargs)
