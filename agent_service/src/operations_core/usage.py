"""Shared pricing and token-cost helpers for Agent and Backoffice.

Pricing is approximate Standard paid-tier rates (USD per 1M tokens) and may drift
from the provider's current list price. Unknown models still report tokens with
cost marked as unavailable.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol

# Default USD→TWD rate used when no PricingProvider is configured.
_DEFAULT_USD_TO_TWD = 31.70


class PricingProvider(Protocol):
    def lookup_rate(self, model: str, at: datetime | None = None) -> tuple[float, float] | None: ...
    def get_exchange_rate(self, at: datetime | None = None) -> float: ...
    def get_pricing_version(self, at: datetime | None = None) -> str: ...
    def list_rates(self, at: datetime | None = None) -> list[dict[str, Any]]: ...


_PRICING_PROVIDER: PricingProvider | None = None


def configure_pricing_provider(provider: PricingProvider | None) -> None:
    global _PRICING_PROVIDER
    _PRICING_PROVIDER = provider


def get_pricing_provider() -> PricingProvider | None:
    return _PRICING_PROVIDER


# Bump when MODEL_RATES_USD changes so historical usage events stay priced consistently.
PRICING_VERSION = "2026-08-31"


def active_pricing_version(at: datetime | None = None) -> str:
    """Return the governed pricing version when a provider is configured."""
    if _PRICING_PROVIDER is not None:
        return _PRICING_PROVIDER.get_pricing_version(at=at)
    return PRICING_VERSION


# Input / output USD per 1M tokens (Standard paid tier). Embeddings use input only (output=0).
#
# Primary source (queried 2026-08-31):
#   https://ai.google.dev/gemini-api/docs/pricing
#
# gemini-3.7-flash is not yet listed on that page; intro Standard rates
# ($0.75 in / $3.75 out through 2026-12-31) from:
#   https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-3-7-flash/
#
# OpenAI chat/embedding rates below are approximate PoC references, not re-verified on 2026-08-31.
MODEL_RATES_USD: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
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


def default_model_rates_usd() -> dict[str, tuple[float, float]]:
    """Return a shallow copy of the built-in per-model USD rate table."""
    return dict(MODEL_RATES_USD)


def normalize_model_name(model: str | None) -> str:
    if not model:
        return "unknown"
    name = model.strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    name = name.removeprefix("models/")
    return name or "unknown"


def lookup_rate(model: str, at: datetime | None = None) -> tuple[float, float] | None:
    if _PRICING_PROVIDER is not None:
        rate = _PRICING_PROVIDER.lookup_rate(model, at=at)
        if rate is not None:
            return rate
    key = normalize_model_name(model).lower()
    if key in MODEL_RATES_USD:
        return MODEL_RATES_USD[key]
    for known, rate in MODEL_RATES_USD.items():
        if known in key or key in known:
            return rate
    return None


def list_model_rates_usd(at: datetime | None = None) -> list[dict[str, Any]]:
    """Return the configured per-model USD rates used for cost estimates."""
    if _PRICING_PROVIDER is not None:
        return _PRICING_PROVIDER.list_rates(at=at)
    return [
        {
            "model": name,
            "inputUsdPer1MTokens": input_rate,
            "outputUsdPer1MTokens": output_rate,
            "pricingVersion": PRICING_VERSION,
        }
        for name, (input_rate, output_rate) in sorted(MODEL_RATES_USD.items())
    ]


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
    at: datetime | None = None,
) -> float | None:
    rate = lookup_rate(model, at=at)
    if rate is None:
        return None
    input_price, output_price = rate
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def convert_usd_to_twd(
    amount_usd: float,
    exchange_rate: float | None = None,
    at: datetime | None = None,
) -> float:
    """Convert a USD amount to TWD for user-facing cost display."""
    if exchange_rate is not None:
        rate = exchange_rate
    elif _PRICING_PROVIDER is not None:
        rate = _PRICING_PROVIDER.get_exchange_rate(at=at)
    else:
        rate = _DEFAULT_USD_TO_TWD
    return round(amount_usd * rate, 3)


__all__ = [
    "MODEL_RATES_USD",
    "PRICING_VERSION",
    "PricingProvider",
    "active_pricing_version",
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
