"""Admin endpoints that apply a scheduled model without flipping governance itself."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..model_control import (
    adopt_embedding_index,
    apply_file_search_model,
    restore_file_search_model,
)
from ..settings import RagSettings


class EmbeddingAdoptBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_model_id: str = Field(alias="expectedModelId", min_length=1)


class FileSearchModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    model_id: str = Field(alias="modelId", min_length=1)


def register_model_control_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
    authorize: Callable[..., None],
) -> None:
    @app.post(
        "/admin/model-control/embedding/adopt",
        dependencies=[Depends(authorize)],
    )
    async def adopt_embedding(payload: EmbeddingAdoptBody, request: Request) -> dict[str, object]:
        result = adopt_embedding_index(request.app, resolved_settings, payload.expected_model_id)
        if not result.adopted:
            raise HTTPException(
                status_code=409, detail=result.reason or "embedding index was not adopted"
            )
        return {"adopted": True, "embeddingModel": result.embedding_model}

    @app.post(
        "/admin/model-control/file-search/apply",
        dependencies=[Depends(authorize)],
    )
    async def apply_file_search(
        payload: FileSearchModelBody, request: Request
    ) -> dict[str, object]:
        result = apply_file_search_model(request.app, payload.model_id)
        if not result.applied:
            raise HTTPException(
                status_code=409, detail=result.reason or "file search model was not applied"
            )
        return {
            "applied": True,
            "model": result.model,
            "previousModel": result.previous_model,
        }

    @app.post(
        "/admin/model-control/file-search/restore",
        dependencies=[Depends(authorize)],
    )
    async def restore_file_search(
        payload: FileSearchModelBody, request: Request
    ) -> dict[str, object]:
        restore_file_search_model(request.app, payload.model_id)
        return {"restored": True, "model": payload.model_id}
