"""Shared numeric helpers for backoffice query services."""

from __future__ import annotations


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int((len(ordered) - 1) * ratio)
    return round(ordered[index], 1)
