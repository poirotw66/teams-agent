"""Retrieval search route."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request

from ..contracts import SearchHit, SearchRequest, SearchResponse
from ..deps import sync_knowledge_to_active_pointer
from ..retrieval import HybridIndex
from ..settings import RagSettings


def register_retrieval_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
    authorize: Callable[..., None],
) -> None:
    @app.post(
        "/retrieval/search",
        response_model=SearchResponse,
        dependencies=[Depends(authorize)],
    )
    async def search(payload: SearchRequest, request: Request) -> SearchResponse:
        sync_knowledge_to_active_pointer(request.app, resolved_settings)
        if (
            resolved_settings.allowed_tenants
            and payload.tenantId not in resolved_settings.allowed_tenants
        ):
            raise HTTPException(status_code=403, detail="Tenant is not allowed.")
        index: HybridIndex = request.app.state.index
        results = index.search(payload.query, payload.limit, set(payload.groups))
        return SearchResponse(
            hits=[
                SearchHit(
                    chunkId=result.chunk.chunk_id,
                    title=result.chunk.title,
                    sourcePath=result.chunk.source_path,
                    content=result.chunk.content,
                    score=result.score,
                )
                for result in results
            ]
        )
