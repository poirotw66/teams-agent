"""Governance policy-runtime configurer port (Agent PolicyRuntime at composition)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = [
    "GovernancePolicyConfigurer",
    "apply_governance_policy_runtime",
    "configure_governance_policy_configurer",
]

GovernancePolicyConfigurer = Callable[[Any, Any], None]

_governance_policy_configurer: GovernancePolicyConfigurer | None = None


def configure_governance_policy_configurer(
    configurer: GovernancePolicyConfigurer | None,
) -> None:
    """Register the composition-owned governance policy runtime installer."""

    global _governance_policy_configurer
    _governance_policy_configurer = configurer


def apply_governance_policy_runtime(
    query_service: Any,
    governance_service: Any,
) -> None:
    if _governance_policy_configurer is None:
        raise RuntimeError(
            "Governance policy configurer is not configured. Call "
            "configure_governance_policy_configurer from composition."
        )
    _governance_policy_configurer(query_service, governance_service)
