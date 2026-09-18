"""Token usage aggregation and rough USD cost estimates for RAG requests.

Prefer ``operations_core.usage`` for pricing helpers. This module re-exports
those shared helpers and keeps Agent-local usage report aggregation so
existing Agent imports keep working during ownership migration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from operations_core.usage import (
    MODEL_RATES_USD,
    PRICING_VERSION,
    PricingProvider,
    active_pricing_version,
    configure_pricing_provider,
    convert_usd_to_twd,
    default_model_rates_usd,
    estimate_cost_usd,
    estimate_text_tokens,
    get_pricing_provider,
    list_model_rates_usd,
    lookup_rate,
    normalize_model_name,
)

# Compat alias for callers that imported the private rate table.
_MODEL_RATES_USD = MODEL_RATES_USD


@dataclass(frozen=True)
class ModelUsage:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None


@dataclass(frozen=True)
class UsageReport:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    embedding_tokens: int
    estimated_cost_usd: float | None
    by_model: tuple[ModelUsage, ...]

    def log_fields(self) -> dict[str, object]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "embedding_tokens": self.embedding_tokens,
            "estimated_cost_usd": (
                None
                if self.estimated_cost_usd is None
                else round(self.estimated_cost_usd, 8)
            ),
            "models": [
                {
                    "model": item.model,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "total_tokens": item.total_tokens,
                    "estimated_cost_usd": (
                        None
                        if item.estimated_cost_usd is None
                        else round(item.estimated_cost_usd, 8)
                    ),
                }
                for item in self.by_model
            ],
        }


def build_usage_report(
    llm_usage_by_model: Mapping[str, Mapping[str, int]],
    *,
    embedding_tokens: int = 0,
    embedding_model: str | None = None,
    at: datetime | None = None,
) -> UsageReport:
    by_model: list[ModelUsage] = []
    input_tokens = 0
    output_tokens = 0
    costs: list[float] = []
    cost_complete = True

    for model_name, usage in llm_usage_by_model.items():
        model_input = int(usage.get("input_tokens") or 0)
        model_output = int(usage.get("output_tokens") or 0)
        model_total = int(usage.get("total_tokens") or (model_input + model_output))
        cost = estimate_cost_usd(model_name, model_input, model_output, at=at)
        if cost is None:
            cost_complete = False
        else:
            costs.append(cost)
        by_model.append(
            ModelUsage(
                model=normalize_model_name(model_name),
                input_tokens=model_input,
                output_tokens=model_output,
                total_tokens=model_total,
                estimated_cost_usd=cost,
            )
        )
        input_tokens += model_input
        output_tokens += model_output

    if embedding_tokens > 0:
        emb_model = (
            normalize_model_name(embedding_model) if embedding_model else "embedding"
        )
        emb_cost = (
            estimate_cost_usd(emb_model, embedding_tokens)
            if embedding_model
            else None
        )
        if emb_cost is None:
            cost_complete = False
        else:
            costs.append(emb_cost)
        by_model.append(
            ModelUsage(
                model=emb_model,
                input_tokens=embedding_tokens,
                output_tokens=0,
                total_tokens=embedding_tokens,
                estimated_cost_usd=emb_cost,
            )
        )
        input_tokens += embedding_tokens

    if not by_model:
        estimated_cost: float | None = 0.0
    elif cost_complete:
        estimated_cost = sum(costs)
    else:
        estimated_cost = None
    return UsageReport(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        embedding_tokens=embedding_tokens,
        estimated_cost_usd=estimated_cost,
        by_model=tuple(by_model),
    )


__all__ = [
    "MODEL_RATES_USD",
    "PRICING_VERSION",
    "_MODEL_RATES_USD",
    "ModelUsage",
    "PricingProvider",
    "UsageReport",
    "active_pricing_version",
    "build_usage_report",
    "configure_pricing_provider",
    "convert_usd_to_twd",
    "default_model_rates_usd",
    "estimate_cost_usd",
    "estimate_text_tokens",
    "get_pricing_provider",
    "list_model_rates_usd",
    "lookup_rate",
    "normalize_model_name",
]
