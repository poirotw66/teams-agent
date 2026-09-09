from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from agent_service.operations.access import ActorContext
from agent_service.operations.audit import AuditStore, build_audit_event
from agent_service.usage import normalize_model_name

from ..faq_domain.errors import FaqAuthorizationError, FaqValidationError
from .models import HistoricalPricingRule, PricingState, RateChangeAudit
from .repository import PricingRepository


class PricingService:
    def __init__(
        self,
        repository: PricingRepository,
        *,
        audit_store: AuditStore | None = None,
        environment: str = "dev",
    ) -> None:
        self._repository = repository
        self._audit_store = audit_store
        self._environment = environment

    def _authorize(self, actor: ActorContext, capability: str) -> None:
        if not (
            actor.has_capability(capability)
            or actor.role in {"SYSTEM_ADMIN", "AI_ADMIN"}
        ):
            raise FaqAuthorizationError(f"Actor lacks required capability: {capability}")

    def list_rates(self) -> list[dict[str, Any]]:
        state = self._repository.load()
        return [
            {
                "model": model,
                "inputUsdPer1MTokens": rates[0],
                "outputUsdPer1MTokens": rates[1],
                "pricingVersion": state.pricing_version,
            }
            for model, rates in sorted(state.rates.items())
        ]

    def get_exchange_rate(self) -> float:
        return self._repository.load().exchange_rate

    def get_pricing_version(self) -> str:
        return self._repository.load().pricing_version

    def lookup_rate(self, model: str) -> tuple[float, float] | None:
        state = self._repository.load()
        key = normalize_model_name(model).lower()
        if key in state.rates:
            return state.rates[key]
        for known, rate in state.rates.items():
            if known in key or key in known:
                return rate
        return None

    def list_history(self) -> dict[str, Any]:
        state = self._repository.load()
        return {
            "currentPricingVersion": state.pricing_version,
            "currentExchangeRate": state.exchange_rate,
            "history": [rule.model_dump(mode="json") for rule in state.history],
            "audits": [audit.model_dump(mode="json") for audit in reversed(state.audits)],
        }

    async def update_model_rate(
        self,
        model: str,
        *,
        input_rate: float,
        output_rate: float,
        effective_at: datetime | None = None,
        reason: str | None = None,
        pricing_version: str | None = None,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._authorize(actor, "ops.cost.write")
        normalized_model = normalize_model_name(model).strip()
        if not normalized_model or normalized_model == "unknown":
            raise FaqValidationError("A valid model name is required")
        if input_rate < 0 or output_rate < 0:
            raise FaqValidationError("Token rates must be non-negative")

        now = datetime.now(UTC)
        effective = effective_at or now

        def operation(state: PricingState) -> tuple[PricingState, dict[str, Any]]:
            before_rate = state.rates.get(normalized_model)
            before_dict = (
                {
                    "inputUsdPer1MTokens": before_rate[0],
                    "outputUsdPer1MTokens": before_rate[1],
                    "pricingVersion": state.pricing_version,
                }
                if before_rate is not None
                else None
            )
            next_version = pricing_version.strip() if pricing_version else state.pricing_version
            after_dict = {
                "inputUsdPer1MTokens": input_rate,
                "outputUsdPer1MTokens": output_rate,
                "pricingVersion": next_version,
            }

            audit = RateChangeAudit(
                audit_id=str(uuid.uuid4()),
                change_type="MODEL_RATE",
                target_id=normalized_model,
                actor_id=actor.user_id,
                actor_role=actor.role,
                before=before_dict,
                after=after_dict,
                effective_at=effective,
                occurred_at=now,
                reason=reason,
            )

            updated_rates = dict(state.rates)
            updated_rates[normalized_model] = (input_rate, output_rate)

            history_list = list(state.history)
            if next_version != state.pricing_version or not history_list:
                history_list.append(
                    HistoricalPricingRule(
                        version=next_version,
                        effective_at=effective,
                        exchange_rate=state.exchange_rate,
                        rates=dict(updated_rates),
                        description=reason or f"Rate updated for {normalized_model}",
                        created_by=actor.user_id,
                        created_at=now,
                    )
                )

            next_state = PricingState(
                revision=state.revision + 1,
                exchange_rate=state.exchange_rate,
                pricing_version=next_version,
                rates=updated_rates,
                history=tuple(history_list),
                audits=(*state.audits, audit),
            )
            return next_state, {
                "model": normalized_model,
                "before": before_dict,
                "after": after_dict,
                "audit": audit.model_dump(mode="json"),
            }

        result = self._repository.mutate(operation)
        if self._audit_store is not None:
            await self._audit_store.append(
                build_audit_event(
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    action="pricing.rate_updated",
                    target_type="PRICING_RATE",
                    target_id=normalized_model,
                    before=result["before"],
                    after=result["after"],
                    reason=reason,
                    environment=self._environment,
                )
            )
        return result

    async def update_exchange_rate(
        self,
        exchange_rate: float,
        *,
        effective_at: datetime | None = None,
        reason: str | None = None,
        pricing_version: str | None = None,
        actor: ActorContext,
    ) -> dict[str, Any]:
        self._authorize(actor, "ops.cost.write")
        if exchange_rate <= 0:
            raise FaqValidationError("Exchange rate must be positive")

        now = datetime.now(UTC)
        effective = effective_at or now

        def operation(state: PricingState) -> tuple[PricingState, dict[str, Any]]:
            before_dict = {
                "exchangeRate": state.exchange_rate,
                "pricingVersion": state.pricing_version,
            }
            next_version = pricing_version.strip() if pricing_version else state.pricing_version
            after_dict = {
                "exchangeRate": exchange_rate,
                "pricingVersion": next_version,
            }

            audit = RateChangeAudit(
                audit_id=str(uuid.uuid4()),
                change_type="EXCHANGE_RATE",
                target_id="USD_TWD",
                actor_id=actor.user_id,
                actor_role=actor.role,
                before=before_dict,
                after=after_dict,
                effective_at=effective,
                occurred_at=now,
                reason=reason,
            )

            history_list = list(state.history)
            if next_version != state.pricing_version or not history_list:
                history_list.append(
                    HistoricalPricingRule(
                        version=next_version,
                        effective_at=effective,
                        exchange_rate=exchange_rate,
                        rates=dict(state.rates),
                        description=reason or f"Exchange rate updated to {exchange_rate}",
                        created_by=actor.user_id,
                        created_at=now,
                    )
                )

            next_state = PricingState(
                revision=state.revision + 1,
                exchange_rate=exchange_rate,
                pricing_version=next_version,
                rates=state.rates,
                history=tuple(history_list),
                audits=(*state.audits, audit),
            )
            return next_state, {
                "targetId": "USD_TWD",
                "before": before_dict,
                "after": after_dict,
                "audit": audit.model_dump(mode="json"),
            }

        result = self._repository.mutate(operation)
        if self._audit_store is not None:
            await self._audit_store.append(
                build_audit_event(
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    action="pricing.exchange_rate_updated",
                    target_type="EXCHANGE_RATE",
                    target_id="USD_TWD",
                    before=result["before"],
                    after=result["after"],
                    reason=reason,
                    environment=self._environment,
                )
            )
        return result
