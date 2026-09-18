"""Bootstrap governed PricingService for the agent runtime.

Shares the same store defaults as the AI Ops backoffice so emit-time costs and
budget evaluation read one PricingService truth.

Concrete Backoffice repositories are wired via composition.install_agent_hooks().
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def resolve_pricing_store_path(ops_store_path: Path | None = None) -> Path:
    explicit = os.environ.get("AI_OPS_PRICING_STORE_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if ops_store_path is not None:
        return (ops_store_path.parent / "phase2" / "pricing_rules.json").resolve()
    root = Path(__file__).resolve().parents[3]
    return (root / "data" / "ops" / "phase2" / "pricing_rules.json").resolve()


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
