"""Pricing rate list, history, and update routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from agent_service.usage import list_model_rates_usd

from .context import AnalyticsRouteContext


async def _update_pricing_rate(
    *,
    pricing_svc: Any,
    payload: dict[str, Any],
    actor: Any,
) -> dict[str, object]:
    rate_type = str(payload.get("type") or "MODEL_RATE").upper()
    reason = payload.get("reason")
    effective_at_raw = payload.get("effectiveAt")
    effective_at = datetime.fromisoformat(effective_at_raw) if effective_at_raw else None
    pricing_version = payload.get("pricingVersion")
    if rate_type == "MODEL_RATE":
        model = str(payload.get("model") or "")
        input_rate = float(
            payload.get("inputUsdPer1MTokens")
            if payload.get("inputUsdPer1MTokens") is not None
            else payload.get("inputPerMillion", 0.0)
        )
        output_rate = float(
            payload.get("outputUsdPer1MTokens")
            if payload.get("outputUsdPer1MTokens") is not None
            else payload.get("outputPerMillion", 0.0)
        )
        return await pricing_svc.update_model_rate(
            model=model,
            input_rate=input_rate,
            output_rate=output_rate,
            effective_at=effective_at,
            reason=reason,
            pricing_version=pricing_version,
            actor=actor,
        )
    if rate_type == "EXCHANGE_RATE":
        exchange_rate = float(payload.get("exchangeRate", 0.0))
        return await pricing_svc.update_exchange_rate(
            exchange_rate=exchange_rate,
            effective_at=effective_at,
            reason=reason,
            pricing_version=pricing_version,
            actor=actor,
        )
    raise HTTPException(status_code=400, detail=f"Unsupported rate type: {rate_type}")


def register_pricing_routes(app: FastAPI, ctx: AnalyticsRouteContext) -> None:
    current_actor = ctx.current_actor
    require_capability = ctx.require_capability
    query_service = ctx.query_service
    audit_read = ctx.audit_read

    @app.get("/api/costs/rates")
    async def costs_rates(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.cost.read")
        pricing_svc = getattr(query_service, "pricing_service", None)
        if pricing_svc is not None:
            rates = pricing_svc.list_rates()
            exchange_rate = pricing_svc.get_exchange_rate()
            pricing_version = pricing_svc.get_pricing_version()
        else:
            rates = list_model_rates_usd()
            # Use public metrics_definitions() instead of query_service._metrics.
            definitions = query_service.metrics_definitions()
            exchange_rate = float(definitions.get("usdTwdExchangeRate", 31.70))
            pricing_version = definitions.get("pricingVersion", "v1")
        return {
            "rates": rates,
            "exchangeRate": exchange_rate,
            "exchangeRateUsdToTwd": exchange_rate,
            "pricingVersion": pricing_version,
        }

    @app.get("/api/costs/rates/history")
    async def costs_rates_history(actor: Any = Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.cost.read")
        pricing_svc = getattr(query_service, "pricing_service", None)
        if pricing_svc is not None:
            result = pricing_svc.list_history()
        else:
            result = {
                "currentPricingVersion": "v1",
                "currentExchangeRate": 31.70,
                "history": [],
                "audits": [],
            }
        await audit_read(actor, "query.costs_rates_history", "pricing_rules")
        return result

    @app.post("/api/costs/rates")
    async def update_costs_rate(
        payload: dict[str, Any],
        actor: Any = Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.cost.write")
        pricing_svc = getattr(query_service, "pricing_service", None)
        if pricing_svc is None:
            raise HTTPException(status_code=500, detail="Pricing service not configured")
        return await _update_pricing_rate(
            pricing_svc=pricing_svc,
            payload=payload,
            actor=actor,
        )
