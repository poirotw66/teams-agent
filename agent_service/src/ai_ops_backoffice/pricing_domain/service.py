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


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def effective_rule_from_state(
    state: PricingState,
    at: datetime | None = None,
) -> HistoricalPricingRule:
    """Resolve the pricing snapshot that is effective at ``at`` from history.

    Live ``state.rates`` / ``state.exchange_rate`` are not used as the timeline
    source of truth; scheduled snapshots must compose from prior history rows.
    """
    target = _normalize_utc(at or datetime.now(UTC))
    applicable = [rule for rule in state.history if rule.effective_at <= target]
    if applicable:
        applicable.sort(key=lambda rule: (rule.effective_at, rule.created_at))
        return applicable[-1]
    if state.history:
        sorted_history = sorted(
            state.history, key=lambda rule: (rule.effective_at, rule.created_at)
        )
        return sorted_history[0]
    return HistoricalPricingRule(
        version=state.pricing_version,
        effective_at=datetime(2026, 8, 31, 0, 0, tzinfo=UTC),
        exchange_rate=state.exchange_rate,
        rates=dict(state.rates),
        description="Baseline pricing rule",
        created_by="system",
        created_at=datetime.now(UTC),
    )


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

    def get_effective_rule(self, at: datetime | None = None) -> HistoricalPricingRule:
        return effective_rule_from_state(self._repository.load(), at)

    def list_rates(self, at: datetime | None = None) -> list[dict[str, Any]]:
        rule = self.get_effective_rule(at)
        return [
            {
                "model": model,
                "inputUsdPer1MTokens": rates[0],
                "outputUsdPer1MTokens": rates[1],
                "pricingVersion": rule.version,
            }
            for model, rates in sorted(rule.rates.items())
        ]

    def get_exchange_rate(self, at: datetime | None = None) -> float:
        return self.get_effective_rule(at).exchange_rate

    def get_pricing_version(self, at: datetime | None = None) -> str:
        return self.get_effective_rule(at).version

    def lookup_rate(self, model: str, at: datetime | None = None) -> tuple[float, float] | None:
        rule = self.get_effective_rule(at)
        key = normalize_model_name(model).lower()
        if key in rule.rates:
            return rule.rates[key]
        for known, rate in rule.rates.items():
            if known in key or key in known:
                return rate
        return None

    def list_history(self) -> dict[str, Any]:
        state = self._repository.load()
        current = effective_rule_from_state(state)
        return {
            "currentPricingVersion": current.version,
            "currentExchangeRate": current.exchange_rate,
            "history": [rule.model_dump(mode="json") for rule in state.history],
            "audits": [audit.model_dump(mode="json") for audit in reversed(state.audits)],
        }

    @staticmethod
    def _next_version(state: PricingState, pricing_version: str | None) -> str:
        if pricing_version and pricing_version.strip():
            return pricing_version.strip()
        return f"{state.pricing_version}.{state.revision + 1}"

    @staticmethod
    def _append_snapshot(
        state: PricingState,
        *,
        next_version: str,
        effective: datetime,
        now: datetime,
        actor_id: str,
        description: str,
        exchange_rate: float | None = None,
        rate_update: tuple[str, tuple[float, float]] | None = None,
    ) -> tuple[HistoricalPricingRule, dict[str, tuple[float, float]], float]:
        """Build a full snapshot from the timeline at ``effective``, then apply the change."""
        base = effective_rule_from_state(state, effective)
        rates = dict(base.rates)
        fx = base.exchange_rate
        if rate_update is not None:
            model_name, model_rates = rate_update
            rates[model_name] = model_rates
        if exchange_rate is not None:
            fx = exchange_rate
        rule = HistoricalPricingRule(
            version=next_version,
            effective_at=effective,
            exchange_rate=fx,
            rates=dict(rates),
            description=description,
            created_by=actor_id,
            created_at=now,
        )
        return rule, rates, fx

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
        effective = _normalize_utc(effective_at or now)

        def operation(state: PricingState) -> tuple[PricingState, dict[str, Any]]:
            base_before = effective_rule_from_state(state, effective)
            before_rate = base_before.rates.get(normalized_model)
            before_dict = (
                {
                    "inputUsdPer1MTokens": before_rate[0],
                    "outputUsdPer1MTokens": before_rate[1],
                    "pricingVersion": base_before.version,
                }
                if before_rate is not None
                else None
            )
            next_version = self._next_version(state, pricing_version)
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
            new_rule, snapshot_rates, snapshot_fx = self._append_snapshot(
                state,
                next_version=next_version,
                effective=effective,
                now=now,
                actor_id=actor.user_id,
                description=reason or f"Rate updated for {normalized_model}",
                rate_update=(normalized_model, (input_rate, output_rate)),
            )
            history_list = [*state.history, new_rule]
            is_future = effective > now
            if is_future:
                next_state = PricingState(
                    revision=state.revision + 1,
                    exchange_rate=state.exchange_rate,
                    pricing_version=state.pricing_version,
                    rates=state.rates,
                    history=tuple(history_list),
                    audits=(*state.audits, audit),
                )
            else:
                next_state = PricingState(
                    revision=state.revision + 1,
                    exchange_rate=snapshot_fx,
                    pricing_version=next_version,
                    rates=dict(snapshot_rates),
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
        effective = _normalize_utc(effective_at or now)

        def operation(state: PricingState) -> tuple[PricingState, dict[str, Any]]:
            base_before = effective_rule_from_state(state, effective)
            before_dict = {
                "exchangeRate": base_before.exchange_rate,
                "pricingVersion": base_before.version,
            }
            next_version = self._next_version(state, pricing_version)
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
            new_rule, snapshot_rates, snapshot_fx = self._append_snapshot(
                state,
                next_version=next_version,
                effective=effective,
                now=now,
                actor_id=actor.user_id,
                description=reason or f"Exchange rate updated to {exchange_rate}",
                exchange_rate=exchange_rate,
            )
            history_list = [*state.history, new_rule]
            is_future = effective > now
            if is_future:
                next_state = PricingState(
                    revision=state.revision + 1,
                    exchange_rate=state.exchange_rate,
                    pricing_version=state.pricing_version,
                    rates=state.rates,
                    history=tuple(history_list),
                    audits=(*state.audits, audit),
                )
            else:
                next_state = PricingState(
                    revision=state.revision + 1,
                    exchange_rate=snapshot_fx,
                    pricing_version=next_version,
                    rates=dict(snapshot_rates),
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
