"""Budget evaluation and API anomaly alert workers."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from operations_core.access import ActorContext
from operations_core.contracts import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)

__all__ = [
    "build_check_api_health_alerts",
    "build_evaluate_all_budgets",
]

ApiHealthChecker = Callable[[ActorContext], Awaitable[list[dict[str, Any]]]]
BudgetEvaluator = Callable[[ActorContext], Awaitable[dict[str, Any]]]


def build_check_api_health_alerts(
    *,
    query_service,
    budget_service,
    notification_dispatcher,
) -> ApiHealthChecker:
    """Return the API anomaly checker bound to runtime collaborators."""

    async def check_api_health_alerts(actor: ActorContext) -> list[dict[str, Any]]:
        health = await query_service.health_summary()
        triggered_alerts: list[dict[str, Any]] = []
        today_key = (
            datetime.now(timezone.utc).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d")
        )
        for comp in health.get("components", []):
            alert = await _maybe_trigger_component_alert(
                budget_service=budget_service,
                notification_dispatcher=notification_dispatcher,
                actor=actor,
                today_key=today_key,
                comp=comp,
            )
            if alert is not None:
                triggered_alerts.append(alert)
        return triggered_alerts

    return check_api_health_alerts


def build_evaluate_all_budgets(
    *,
    resolved_settings,
    query_service,
    budget_service,
    notification_dispatcher,
    check_api_health_alerts: ApiHealthChecker,
) -> BudgetEvaluator:
    """Return the budget evaluator bound to runtime collaborators."""

    async def evaluate_all_budgets(actor: ActorContext) -> dict[str, Any]:
        evaluated_policies = 0
        evaluated_users = 0
        triggered_alerts: list[dict[str, Any]] = []

        policies = budget_service.list_policies(actor=actor)
        for policy in policies:
            if not policy.get("enabled", True):
                continue
            alert = await _evaluate_policy(
                query_service=query_service,
                budget_service=budget_service,
                notification_dispatcher=notification_dispatcher,
                actor=actor,
                policy=policy,
            )
            evaluated_policies += 1 if alert is not False else 0
            if isinstance(alert, dict):
                triggered_alerts.append(alert)

        if resolved_settings.default_personal_daily_budget_enabled:
            personal_count, personal_alerts = await _evaluate_personal_daily_budgets(
                resolved_settings=resolved_settings,
                query_service=query_service,
                budget_service=budget_service,
                notification_dispatcher=notification_dispatcher,
                actor=actor,
                policies=policies,
            )
            evaluated_users += personal_count
            triggered_alerts.extend(personal_alerts)

        if resolved_settings.api_anomaly_check_enabled:
            anomaly_alerts = await check_api_health_alerts(actor)
            triggered_alerts.extend(anomaly_alerts)

        dispatched = await notification_dispatcher.dispatch_pending(actor=actor)
        return {
            "evaluatedPolicies": evaluated_policies,
            "evaluatedUsers": evaluated_users,
            "triggeredAlerts": len(triggered_alerts),
            "alerts": triggered_alerts,
            "dispatchedDeliveries": len(dispatched),
        }

    return evaluate_all_budgets


async def _maybe_trigger_component_alert(
    *,
    budget_service,
    notification_dispatcher,
    actor: ActorContext,
    today_key: str,
    comp: dict[str, Any],
) -> dict[str, Any] | None:
    comp_id = str(comp.get("id") or "")
    if not comp_id:
        return None
    status = str(comp.get("status", "READY")).upper()
    note = str(comp.get("note", ""))
    error_rate = float(comp.get("errorRate") or 0.0)
    is_down = status in {"DOWN", "FAILED", "UNAVAILABLE"}
    is_degraded = status in {"DEGRADED"} or error_rate >= 0.05
    if not (is_down or is_degraded):
        return None
    severity = "CRITICAL" if is_down else "WARNING"
    summary = (
        f"API anomaly in {comp_id}: status={status}, errorRate={error_rate:.2%}; {note}"
    ).strip()
    try:
        alert_res = budget_service.trigger_operational_alert(
            alert_type="API_ANOMALY",
            severity=severity,
            scope_type="SERVICE",
            scope_id=comp_id,
            period_key=today_key,
            owner_unit_id="IT",
            summary=summary,
            actual_value=error_rate,
            actor=actor,
        )
        if alert_res.get("triggered") and alert_res.get("alert"):
            await notification_dispatcher.dispatch_for_alert(
                alert_res["alert"]["alert_id"],
                actor=actor,
            )
            return alert_res["alert"]
    except Exception:
        logger.exception("Failed to record API anomaly alert for %s", comp_id)
    return None


async def _evaluate_policy(
    *,
    query_service,
    budget_service,
    notification_dispatcher,
    actor: ActorContext,
    policy: dict[str, Any],
) -> dict[str, Any] | bool:
    """Evaluate one policy. Returns alert dict, True on success, or False on failure."""
    try:
        usage = await query_service.budget_usage(
            actor,
            scope_type=str(policy["scope_type"]),
            scope_id=str(policy["scope_id"]),
            period_type=str(policy["period"]),
            measure=str(policy["measure"]),
        )
        res = budget_service.evaluate(
            str(policy["policy_id"]),
            period_key=str(usage["periodKey"]),
            actual_value=float(usage["actualValue"]),
            coverage=float(usage["coverage"]),
            pricing_version=str(usage["pricingVersion"]),
            exchange_rate_version=str(usage["exchangeRateVersion"]),
            actor=actor,
        )
        if res.get("triggered") and res.get("alert"):
            await notification_dispatcher.dispatch_for_alert(
                res["alert"]["alert_id"],
                actor=actor,
            )
            return res["alert"]
        return True
    except Exception:
        logger.exception("Failed to evaluate policy %s", policy.get("policy_id"))
        return False


async def _evaluate_personal_daily_budgets(
    *,
    resolved_settings,
    query_service,
    budget_service,
    notification_dispatcher,
    actor: ActorContext,
    policies: list[dict[str, Any]],
) -> tuple[int, list[dict[str, Any]]]:
    evaluated_users = 0
    triggered_alerts: list[dict[str, Any]] = []
    today_period = query_service._resolve_period(preset="today")
    active_actors = await query_service.list_active_actors_for_budget(actor, today_period)
    definitions = query_service.metrics_definitions()
    pricing_ver = str(definitions.get("pricingVersion", "v1"))
    rate_ver = str(
        definitions.get("exchangeRateVersion") or definitions.get("pricingVersion", "v1")
    )
    covered_users = {
        p["scope_id"]
        for p in policies
        if p.get("scope_type") == "PERSONAL"
        and p.get("period") == "DAILY"
        and p.get("measure") == "TWD"
        and p.get("enabled", True)
    }
    for user_id in active_actors:
        if user_id in covered_users:
            continue
        alert = await _evaluate_personal_user(
            resolved_settings=resolved_settings,
            query_service=query_service,
            budget_service=budget_service,
            notification_dispatcher=notification_dispatcher,
            actor=actor,
            user_id=user_id,
            pricing_ver=pricing_ver,
            rate_ver=rate_ver,
        )
        if alert is False:
            continue
        evaluated_users += 1
        if isinstance(alert, dict):
            triggered_alerts.append(alert)
    return evaluated_users, triggered_alerts


async def _evaluate_personal_user(
    *,
    resolved_settings,
    query_service,
    budget_service,
    notification_dispatcher,
    actor: ActorContext,
    user_id: str,
    pricing_ver: str,
    rate_ver: str,
) -> dict[str, Any] | bool:
    try:
        personal_policy = budget_service.ensure_personal_policy(
            user_id=user_id,
            warning_threshold=resolved_settings.default_personal_daily_warning_threshold,
            critical_threshold=resolved_settings.default_personal_daily_budget_threshold,
            pricing_version=pricing_ver,
            exchange_rate_version=rate_ver,
            actor=actor,
        )
        usage = await query_service.budget_usage(
            actor,
            scope_type="PERSONAL",
            scope_id=user_id,
            period_type="DAILY",
            measure="TWD",
        )
        res = budget_service.evaluate(
            str(personal_policy["policy_id"]),
            period_key=str(usage["periodKey"]),
            actual_value=float(usage["actualValue"]),
            coverage=float(usage["coverage"]),
            pricing_version=str(usage["pricingVersion"]),
            exchange_rate_version=str(usage["exchangeRateVersion"]),
            actor=actor,
        )
        if res.get("triggered") and res.get("alert"):
            await notification_dispatcher.dispatch_for_alert(
                res["alert"]["alert_id"],
                actor=actor,
            )
            return res["alert"]
        return True
    except Exception:
        logger.exception("Failed to evaluate personal daily budget for user %s", user_id)
        return False
