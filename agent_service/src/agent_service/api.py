import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from .contracts import (
    AgentRequest,
    AgentResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from .graph import RagAgent
from .indexer import build_index
from .retrieval import HybridIndex
from .settings import RagSettings

logger = logging.getLogger(__name__)


def create_app(settings: RagSettings | None = None) -> FastAPI:
    resolved_settings = settings or RagSettings.from_env()

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = resolved_settings.service_token
        if not expected:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service token.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not resolved_settings.index_path.exists():
            if not resolved_settings.auto_build_index:
                raise FileNotFoundError(
                    f"RAG index not found: {resolved_settings.index_path}"
                )
            index = build_index(resolved_settings)
        else:
            index = HybridIndex.load(
                resolved_settings.index_path,
                resolved_settings.embedding_model,
            )

        app.state.index = index
        app.state.agent = RagAgent(resolved_settings, index)
        logger.info(
            "Agentic RAG ready: chunks=%s model=%s embeddings=%s",
            len(index.chunks),
            resolved_settings.model or "extractive-local",
            resolved_settings.embedding_model or "sparse-only",
        )
        yield

    app = FastAPI(
        title="Teams Agentic RAG Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready(request: Request) -> dict[str, object]:
        index: HybridIndex | None = getattr(request.app.state, "index", None)
        is_ready = bool(index and index.chunks)
        if not is_ready:
            raise HTTPException(status_code=503, detail="RAG index is not ready.")
        return {
            "status": "ready",
            "chunks": len(index.chunks),
            "model": resolved_settings.model or "extractive-local",
            "retrieval": (
                "hybrid"
                if resolved_settings.embedding_model
                else "chinese-bm25"
            ),
        }

    @app.post(
        "/agent/chat",
        response_model=AgentResponse,
        dependencies=[Depends(authorize)],
    )
    async def chat(payload: AgentRequest, request: Request) -> AgentResponse:
        tenant_id = payload.conversation.tenantId
        if (
            resolved_settings.allowed_tenants
            and tenant_id not in resolved_settings.allowed_tenants
        ):
            raise HTTPException(status_code=403, detail="Tenant is not allowed.")

        agent: RagAgent = request.app.state.agent
        logger.info(
            "Agent request started: request_id=%s channel=%s conversation=%s",
            payload.requestId,
            payload.channel,
            payload.conversation.conversationId or "unknown",
        )
        try:
            result = await agent.run(payload)
        except Exception as error:
            logger.exception(
                "Agent request failed: request_id=%s",
                payload.requestId,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Agent execution failed. Request ID: {payload.requestId}",
            ) from error
        usage = result.usage.log_fields()
        logger.info(
            "Agent request completed: request_id=%s trace_id=%s citations=%s "
            "input_tokens=%s output_tokens=%s total_tokens=%s embedding_tokens=%s "
            "estimated_cost_usd=%s usage=%s",
            payload.requestId,
            result.trace_id,
            len(result.citations),
            usage["input_tokens"],
            usage["output_tokens"],
            usage["total_tokens"],
            usage["embedding_tokens"],
            usage["estimated_cost_usd"],
            usage,
        )
        return AgentResponse(
            answer=result.answer,
            traceId=result.trace_id,
            citations=result.citations,
            images=result.images,
        )

    @app.post(
        "/retrieval/search",
        response_model=SearchResponse,
        dependencies=[Depends(authorize)],
    )
    async def search(payload: SearchRequest, request: Request) -> SearchResponse:
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

    return app


app = create_app()
