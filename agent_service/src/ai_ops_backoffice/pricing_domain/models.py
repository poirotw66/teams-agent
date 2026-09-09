from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelRateRecord(StrictModel):
    model: str
    input_usd_per_1m_tokens: float = Field(ge=0.0)
    output_usd_per_1m_tokens: float = Field(ge=0.0)
    pricing_version: str
    effective_at: datetime
    updated_by: str
    updated_at: datetime


class RateChangeAudit(StrictModel):
    audit_id: str
    change_type: Literal["MODEL_RATE", "EXCHANGE_RATE"]
    target_id: str
    actor_id: str
    actor_role: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    effective_at: datetime
    occurred_at: datetime
    reason: str | None = None


class HistoricalPricingRule(StrictModel):
    version: str
    effective_at: datetime
    exchange_rate: float
    rates: dict[str, tuple[float, float]]
    description: str | None = None
    created_by: str
    created_at: datetime


class PricingState(StrictModel):
    revision: int = 0
    exchange_rate: float = 31.70
    pricing_version: str = "v1"
    rates: dict[str, tuple[float, float]] = Field(default_factory=dict)
    history: tuple[HistoricalPricingRule, ...] = ()
    audits: tuple[RateChangeAudit, ...] = ()


Mutation = Callable[[PricingState], tuple[PricingState, dict[str, Any]]]
