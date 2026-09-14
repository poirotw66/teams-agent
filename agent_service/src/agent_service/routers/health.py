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
        catalog = _model_catalog(request, resolved_settings, index)
        by_role = {item["role"]: item for item in catalog["items"]}
        return {
            "status": "ready",
            "chunks": len(index.chunks),
            "model": by_role["answer"]["model"] or "extractive-local",
            "agentModel": by_role["agent"]["model"] or "extractive-local",
            "embeddingModel": by_role["embedding"]["model"],
            "fileSearchModel": by_role["file_search"]["model"],
            "modelCatalog": catalog,
            "knowledgeMode": resolved_settings.knowledge_service_mode,
            "retrieval": (
                "hybrid"
                if by_role["embedding"]["model"]
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


def _model_catalog(request: Request, settings: RagSettings, index: HybridIndex) -> dict[str, object]:
    runtime = getattr(request.app.state, "governance_runtime", None)
    file_search_model = _file_search_model(request)
    if runtime is None or not hasattr(runtime, "effective_model_catalog"):
        from ..prompt_runtime import GovernanceRuntime

        runtime = GovernanceRuntime.from_settings(settings)
    return runtime.effective_model_catalog(
        embedding_model=index.embedding_model_name,
        file_search_model=file_search_model,
    )


def _file_search_model(request: Request) -> str | None:
    router = getattr(request.app.state, "knowledge_router", None)
    getter = getattr(router, "get_service", None)
    if getter is None:
        return None
    service = getter("GEMINI_FILE_SEARCH")
    model = getattr(service, "model", None)
    return str(model) if model else None
