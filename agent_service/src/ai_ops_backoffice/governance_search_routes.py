"""Cross-domain search route registration for governance."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Query

from .governance_domain import GovernanceService
from .governance_search_ops import collect_search_extras

__all__ = ["register_search_routes"]


def register_search_routes(
    app: FastAPI,
    *,
    governance: GovernanceService,
    current_actor,
    require_capability,
    example_service,
    faq_service=None,
    query_service=None,
    quality_service=None,
) -> None:
    @app.get("/api/governance/search")
    async def governance_search(
        q: str = Query(default=""),
        doc_type: str | None = Query(default=None),
        owner_unit_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.search.read")
        extras, warnings = await collect_search_extras(
            actor=actor,
            query=q,
            faq_service=faq_service,
            example_service=example_service,
            query_service=query_service,
            quality_service=quality_service,
        )
        res = governance.search(
            query=q,
            actor=actor,
            doc_type=doc_type,
            owner_unit_id=owner_unit_id,
            status=status,
            extra_documents=extras,
        )
        res["warnings"] = warnings
        return res
