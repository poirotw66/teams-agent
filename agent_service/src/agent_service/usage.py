"""Token usage aggregation and rough USD cost estimates for RAG requests.

Pricing is approximate Standard paid-tier rates (USD per 1M tokens) and may drift
from the provider's current list price. Unknown models still report tokens with
cost marked as unavailable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

# Input / output USD per 1M tokens. Embeddings use input only (output=0).
# Source: Google AI Gemini API pricing, fetched 2026-07.
_MODEL_RATES_USD: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-embedding-2": (0.20, 0.0),
    "gemini-embedding-001": (0.15, 0.0),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
}


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


def normalize_model_name(model: str | None) -> str:
    if not model:
        return "unknown"
    name = model.strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    name = name.removeprefix("models/")
    return name or "unknown"


def lookup_rate(model: str) -> tuple[float, float] | None:
    key = normalize_model_name(model).lower()
    if key in _MODEL_RATES_USD:
        return _MODEL_RATES_USD[key]
    for known, rate in _MODEL_RATES_USD.items():
        if known in key or key in known:
            return rate
    return None


def estimate_text_tokens(text: str) -> int:
    """Rough token estimate for embedding calls without provider usage metadata."""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int = 0,
) -> float | None:
    rate = lookup_rate(model)
    if rate is None:
        return None
    input_price, output_price = rate
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def build_usage_report(
    llm_usage_by_model: Mapping[str, Mapping[str, int]],
    *,
    embedding_tokens: int = 0,
    embedding_model: str | None = None,
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
        cost = estimate_cost_usd(model_name, model_input, model_output)
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
