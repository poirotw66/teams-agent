"""Optional composition hooks so Agent domain code never imports Backoffice."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from agent_service.settings import RagSettings
from platform_kernel.ports.governance import GovernanceProvider

T = TypeVar("T")

GovernanceBuilder = Callable[[RagSettings], GovernanceProvider | None]
FaqServiceBuilder = Callable[[RagSettings], Any]
PricingBuilder = Callable[..., Any]
OpsGovernanceBuilder = Callable[[Any], Any]

_governance_builder: GovernanceBuilder | None = None
_faq_service_builder: FaqServiceBuilder | None = None
_pricing_builder: PricingBuilder | None = None
_ops_governance_builder: OpsGovernanceBuilder | None = None


def register_governance_builder(builder: GovernanceBuilder) -> None:
    global _governance_builder
    _governance_builder = builder


def register_faq_service_builder(builder: FaqServiceBuilder) -> None:
    global _faq_service_builder
    _faq_service_builder = builder


def register_pricing_builder(builder: PricingBuilder) -> None:
    global _pricing_builder
    _pricing_builder = builder


def register_ops_governance_builder(builder: OpsGovernanceBuilder) -> None:
    global _ops_governance_builder
    _ops_governance_builder = builder


def build_governance_provider(settings: RagSettings) -> GovernanceProvider | None:
    if _governance_builder is None:
        return None
    return _governance_builder(settings)


def build_faq_service(settings: RagSettings) -> Any | None:
    if _faq_service_builder is None:
        return None
    return _faq_service_builder(settings)


def build_pricing_service(**kwargs: Any) -> Any | None:
    if _pricing_builder is None:
        return None
    return _pricing_builder(**kwargs)


def build_ops_governance(settings: Any) -> Any | None:
    if _ops_governance_builder is None:
        return None
    return _ops_governance_builder(settings)
