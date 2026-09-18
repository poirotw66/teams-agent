"""Knowledge Portal draft test write and search HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from knowledge_portal.auth import draft_search_response
from knowledge_portal.models import CreateTestCaseRequest, DraftSearchRequest, PortalActor
from knowledge_portal.service import PortalService
from knowledge_portal.settings import PortalSettings


def register_tests_write_routes(
    app: FastAPI,
    *,
    settings: PortalSettings,
    service: PortalService,
    pdf_job_store: Any,
    authorize: Callable[..., None],
    current_actor: Callable[..., PortalActor],
    correlation_id: Callable[..., str],
    idempotency_key: Callable[..., str | None],
    handle_errors: Callable[[Exception], HTTPException],
) -> None:
    del settings, pdf_job_store, idempotency_key

    @app.post("/api/documents/{document_id}/test-cases")
    async def create_test_case(
        document_id: str,
        request: CreateTestCaseRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.add_test_case(
                actor, document_id, request, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/draft-search")
    async def draft_search(
        document_id: str,
        request: DraftSearchRequest,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
    ):
        try:
            result = await service.search_draft(
                actor,
                document_id,
                request.query,
                request.groups,
                request.limit,
            )
            return draft_search_response(result)
        except Exception as exc:
            raise handle_errors(exc) from exc

    @app.post("/api/documents/{document_id}/test-cases/{test_case_id}/run")
    async def run_test_case(
        document_id: str,
        test_case_id: str,
        actor: PortalActor = Depends(current_actor),
        _: None = Depends(authorize),
        correlation_id_value: str = Depends(correlation_id),
    ):
        try:
            return await service.run_test_case(
                actor, document_id, test_case_id, correlation_id_value
            )
        except Exception as exc:
            raise handle_errors(exc) from exc
