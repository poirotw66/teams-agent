"""Workbench document routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ai_ops_backoffice.application.workbench.documents import (
    DocumentOperationError,
)
from ai_ops_backoffice.application.workbench.documents import (
    delete_workbench_document as delete_document,
)
from ai_ops_backoffice.application.workbench.documents import (
    list_workbench_documents as list_documents,
)
from ai_ops_backoffice.application.workbench.documents import (
    upload_workbench_document as upload_document,
)
from ai_ops_backoffice.knowledge_bridge.capabilities import has_knowledge_capability
from operations_core.access import ActorContext

from .context import WorkbenchRouteContext
from .response_models import ManualDocumentItem


def register_document_routes(app: FastAPI, ctx: WorkbenchRouteContext) -> None:
    current_actor = ctx.current_actor
    knowledge_client = ctx.knowledge_client

    @app.get(
        "/api/console/workbench/documents",
        response_model=list[ManualDocumentItem],
    )
    async def list_workbench_documents(
        actor: ActorContext = Depends(current_actor),
    ) -> list[dict[str, Any]]:
        """Return published document metadata (chunk bodies loaded on demand)."""
        ctx.require_capability(actor, "ops.knowledge.read")
        portal_data, all_chunks = await asyncio.gather(
            asyncio.to_thread(ctx.load_portal_state),
            asyncio.to_thread(ctx.get_cached_chunks),
        )
        if not portal_data or "documents" not in portal_data:
            return []
        return await asyncio.to_thread(
            list_documents,
            portal_data=portal_data,
            all_chunks=all_chunks,
        )

    @app.post("/api/console/workbench/documents/upload")
    async def upload_workbench_document(
        file: UploadFile = File(...),
        title: str = Form(...),
        category: str = Form("辦公系統"),
        version: str = Form("v1.0"),
        deprecateOlderVersion: bool = Form(False),
        actor: ActorContext = Depends(current_actor),
    ):
        """Compatibility shim that creates a governed Portal ingestion draft."""
        del deprecateOlderVersion
        if not has_knowledge_capability(actor, "knowledge.create"):
            raise HTTPException(status_code=403, detail="需要 knowledge.create 權限。")
        file_bytes = await file.read()
        try:
            status_code, body = await upload_document(
                knowledge_client=knowledge_client,
                actor=actor,
                file_bytes=file_bytes,
                filename=file.filename or "document.pdf",
                content_type=file.content_type or "application/octet-stream",
                title=title,
                category=category,
                version=version,
            )
        except DocumentOperationError as err:
            raise HTTPException(status_code=err.status_code, detail=err.detail) from err
        return JSONResponse(status_code=status_code, content=body)

    @app.delete("/api/console/workbench/documents/{document_id}")
    async def delete_workbench_document(
        document_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        """Compatibility shim for governed Portal removal."""
        if not has_knowledge_capability(actor, "knowledge.delete"):
            raise HTTPException(status_code=403, detail="需要 knowledge.delete 權限。")
        try:
            return await delete_document(
                knowledge_client=knowledge_client,
                actor=actor,
                document_id=document_id,
            )
        except DocumentOperationError as err:
            raise HTTPException(status_code=err.status_code, detail=err.detail) from err
