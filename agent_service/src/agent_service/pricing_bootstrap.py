"""Bootstrap governed PricingService for the agent runtime.

Shares the same store defaults as the AI Ops backoffice so emit-time costs and
budget evaluation read one PricingService truth.

Concrete Backoffice repositories are wired via composition.install_agent_hooks().
Path resolution lives in ``operations_core.pricing_paths``; this module re-exports
it and keeps the Agent runtime-hook based configure entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from operations_core.pricing_paths import resolve_pricing_store_path

__all__ = [
    "build_and_configure_pricing_service",
    "resolve_pricing_store_path",
]


def build_and_configure_pricing_service(
    *,
    ops_store_path: Path | None = None,
    audit_store: Any | None = None,
    environment: str = "dev",
) -> Any:
    """Construct PricingService from the registered composition builder."""

    from agent_service.runtime_hooks import build_pricing_service

    service = build_pricing_service(
        ops_store_path=ops_store_path,
        audit_store=audit_store,
        environment=environment,
    )
    if service is None:
        raise RuntimeError(
            "Pricing bootstrap requires composition.install_agent_hooks(); "
            "no pricing builder is registered."
        )
    return service
