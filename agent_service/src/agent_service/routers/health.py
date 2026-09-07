"""Health and readiness probes."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from ..deps import sync_knowledge_to_active_pointer
from ..retrieval import HybridIndex
from ..settings import RagSettings


def register_health_routes(
    app: FastAPI,
    *,
    resolved_settings: RagSettings,
) -> None:
    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready(request: Request) -> dict[str, object]:
        sync_knowledge_to_active_pointer(request.app, resolved_settings)
        index: HybridIndex | None = getattr(request.app.state, "index", None)
        is_ready = bool(index is not None)
        if not is_ready:
            raise HTTPException(status_code=503, detail="RAG index is not ready.")
        return {
            "status": "ready",
            "chunks": len(index.chunks),
            "model": resolved_settings.model or "extractive-local",
            "agentModel": (
                resolved_settings.agent_model
                or resolved_settings.model
                or "extractive-local"
            ),
            "retrieval": (
                "hybrid"
                if resolved_settings.embedding_model
                else "chinese-bm25"
            ),
            "knowledgeBackend": await request.app.state.knowledge_router.active_backend(),
            "knowledgeIndexSource": getattr(
                request.app.state, "knowledge_index_source", "bundled_index"
            ),
            "knowledgeReleaseId": getattr(request.app.state, "knowledge_release_id", None),
            "knowledgeIndexPath": str(
                getattr(request.app.state, "knowledge_index_path", resolved_settings.index_path)
            ),
        }
