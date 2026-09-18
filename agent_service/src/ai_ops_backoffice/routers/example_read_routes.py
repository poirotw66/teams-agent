"""Example list / get routes."""

from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI


def register_example_read_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    example_service,
    faq_service,
    current_actor,
    require_capability,
) -> None:
    del resolved_settings, query_service, faq_service

    @app.get("/api/examples")
    async def list_examples(
        source_type: Literal["FAQ", "DOCUMENT", "CONVERSATION", "MANUAL"] | None = None,
        source_id: str | None = None,
        status: Literal["DRAFT", "VERIFIED", "REJECTED", "RETIRED"] | None = None,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.examples.read")
        items = example_service.list_examples(
            actor=actor,
            source_type=source_type,
            source_id=source_id,
            status=status,
        )
        return {"items": items, "total": len(items)}

    @app.get("/api/examples/{example_id}")
    async def get_example(example_id: str, actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.examples.read")
        return example_service.detail(example_id, actor=actor)
