"""Bootstrap governed PricingService for the agent runtime.

Shares the same store defaults as the AI Ops backoffice so emit-time costs and
budget evaluation read one PricingService truth.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from agent_service.usage import configure_pricing_provider

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
    """Construct PricingService from env/store defaults and install as provider."""
    from ai_ops_backoffice.pricing_domain import (
        FilePricingRepository,
        FirestorePricingRepository,
        InMemoryPricingRepository,
        PricingService,
    )

    mode = (os.environ.get("AI_OPS_PRICING_STORE_MODE", "FILE") or "FILE").upper()
    store_path = resolve_pricing_store_path(ops_store_path)
    collection = (
        os.environ.get("AIOPS_PRICING_FIRESTORE_COLLECTION")
        or os.environ.get("AI_OPS_PRICING_FIRESTORE_COLLECTION")
        or "ai_ops_pricing_state"
    )
    if mode == "FILE":
        repository = FilePricingRepository(store_path)
    elif mode == "FIRESTORE":
        from google.cloud import firestore

        project = (
            os.environ.get("AI_OPS_GCP_PROJECT")
            or os.environ.get("GCP_PROJECT_ID")
            or os.environ.get("OPS_FIRESTORE_PROJECT")
        )
        repository = FirestorePricingRepository(
            firestore.Client(project=project),
            collection=collection,
        )
    else:
        repository = InMemoryPricingRepository()

    service = PricingService(
        repository,
        audit_store=audit_store,
        environment=environment,
    )
    configure_pricing_provider(service)
    logger.info(
        "Governed pricing provider configured: mode=%s version=%s path=%s",
        mode,
        service.get_pricing_version(),
        store_path if mode == "FILE" else collection if mode == "FIRESTORE" else "memory",
    )
    return service
