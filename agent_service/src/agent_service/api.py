import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import replace

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.callbacks import get_usage_metadata_callback

from .contracts import (
    AgentRequest,
    AgentResponse,
    FeedbackRequest,
    KnowledgeBackendUpdate,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from .conversation import ConversationService, build_repository
from .extractor import IssueExtractor
from .faq import FaqService
from .graph import RagAgent, build_chat_model
from .handoff_repository import build_handoff_repository
from .indexer import build_index
from .knowledge_backends import KnowledgeBackendRouter, build_backend_state_store
from .knowledge_release import resolve_knowledge_index
from .operations.event_identity import LogicalRequestIdentity
from .operations.emitter import OperationalEventReplayConflict
from .operations.runtime import OpsRuntime, build_ops_runtime
from .retrieval import HybridIndex
from .settings import RagSettings
from .ticket import build_ticket_service
from .ticket_dedupe import build_ticket_request_dedupe
from .usage import build_usage_report, convert_usd_to_twd
from .usage_events import (
    RequestCostSummary,
    build_request_cost_summary,
    derive_request_outcome,
    log_request_cost,
)
from .workflow import INITIAL_STAGE_LABEL, AgentWorkflow, build_knowledge_service

logger = logging.getLogger(__name__)


def _sse(event: str, data: dict) -> str:
    """Frame one Server-Sent Event.

    `ensure_ascii=True` is deliberate: the payload is Chinese, and escaping it
    keeps every `data:` line free of raw multi-byte content while JSON itself
    guarantees no embedded newline can break SSE framing.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
        resolved_index = resolve_knowledge_index(resolved_settings)
        if resolved_index.source == "auto_build" and not resolved_index.index_path.exists():
            index = build_index(resolved_settings)
        elif not resolved_index.index_path.exists():
            raise FileNotFoundError(
                f"Knowledge index not found: {resolved_index.index_path}"
            )
        else:
            index = HybridIndex.load(
                resolved_index.index_path,
                resolved_settings.embedding_model,
            )

        # Legacy single-query agent (spec §8.2 delegate). Kept for the
        # standalone /retrieval-adjacent use case and its own tests; the
        # LangGraph workflow below (spec §5) is what /agent/chat runs.
        agent = RagAgent(resolved_settings, index)

        rag_model = build_chat_model(resolved_settings.model)
        agent_model = build_chat_model(
            resolved_settings.agent_model or resolved_settings.model
        )

        # Build every §5 collaborator ONCE here (not per request):
        # FAQ / Conversation / Ticket / Knowledge services + the Issue
        # Extractor, then wire them into a single AgentWorkflow instance.
        faq_service = FaqService.from_settings(resolved_settings)
        conversation_service = ConversationService(
            build_repository(resolved_settings), resolved_settings
        )
        handoff_repository = build_handoff_repository(resolved_settings)
        ticket_service = build_ticket_service(resolved_settings)
        hybrid_settings = replace(resolved_settings, knowledge_service_mode="HYBRID")
        knowledge_services = {
            "HYBRID": build_knowledge_service(hybrid_settings, index, rag_model)
        }
        unavailable_backends: dict[str, str] = {}
        if resolved_settings.gemini_file_search_store:
            gemini_settings = replace(
                resolved_settings, knowledge_service_mode="GEMINI_FILE_SEARCH"
            )
            knowledge_services["GEMINI_FILE_SEARCH"] = build_knowledge_service(
                gemini_settings, index, rag_model
            )
        else:
            unavailable_backends["GEMINI_FILE_SEARCH"] = (
                "尚未設定 GEMINI_FILE_SEARCH_STORE"
            )
        knowledge_router = KnowledgeBackendRouter(
            knowledge_services,
            resolved_settings.knowledge_service_mode,
            unavailable_backends,
            build_backend_state_store(resolved_settings),
            resolved_settings,
        )
        extractor = IssueExtractor(resolved_settings, agent_model)
        ticket_request_dedupe = build_ticket_request_dedupe(resolved_settings)
        if (
            resolved_settings.rag_require_file_search_acl
            and resolved_settings.gemini_file_search_store
            and not resolved_settings.gemini_file_search_enforce_acl
        ):
            raise RuntimeError(
                "Refusing to start with GEMINI_FILE_SEARCH_ENFORCE_ACL=false while "
                "RAG_REQUIRE_FILE_SEARCH_ACL=true."
            )
        workflow = AgentWorkflow(
            resolved_settings,
            extractor=extractor,
            faq_service=faq_service,
            knowledge_service=knowledge_router,
            conversation_service=conversation_service,
            ticket_service=ticket_service,
            handoff_repository=handoff_repository,
            ticket_request_dedupe=ticket_request_dedupe,
        )

        app.state.index = index
        app.state.knowledge_index_path = resolved_index.index_path
        app.state.knowledge_release_id = resolved_index.release_id
        app.state.knowledge_index_source = resolved_index.source
        app.state.agent = agent
        app.state.knowledge_router = knowledge_router
        app.state.workflow = workflow
        app.state.handoff_repository = handoff_repository
        ops_runtime = build_ops_runtime()
        app.state.ops_runtime = ops_runtime
        if ops_runtime is not None:
            logger.info(
                "Operational events enabled: store=%s taxonomy=%s",
                ops_runtime.settings.store_mode,
                ops_runtime.taxonomy.version,
            )
        logger.info(
            "Agentic RAG ready: chunks=%s agent_model=%s rag_model=%s embeddings=%s "
            "knowledge_mode=%s ticket_mode=%s",
            len(index.chunks),
            resolved_settings.agent_model
            or resolved_settings.model
            or "extractive-local",
            resolved_settings.model or "extractive-local",
            resolved_settings.embedding_model or "sparse-only",
            resolved_settings.knowledge_service_mode,
            resolved_settings.ticket_service_mode,
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

    @app.get(
        "/admin/knowledge-backend",
        dependencies=[Depends(authorize)],
    )
    async def get_knowledge_backend(request: Request) -> dict[str, object]:
        router: KnowledgeBackendRouter = request.app.state.knowledge_router
        return await router.status()

    @app.put(
        "/admin/knowledge-backend",
        dependencies=[Depends(authorize)],
    )
    async def set_knowledge_backend(
        payload: KnowledgeBackendUpdate, request: Request
    ) -> dict[str, object]:
        if not resolved_settings.knowledge_backend_admin_enabled:
            raise HTTPException(
                status_code=403,
                detail="Knowledge backend switching is disabled in this environment.",
            )
        router: KnowledgeBackendRouter = request.app.state.knowledge_router
        try:
            await router.select(payload.backend)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        logger.info("Knowledge backend changed: backend=%s", payload.backend)
        return await router.status()

    def _authorize_tenant(payload: AgentRequest) -> None:
        tenant_id = payload.conversation.tenantId
        if (
            resolved_settings.allowed_tenants
            and tenant_id not in resolved_settings.allowed_tenants
        ):
            raise HTTPException(status_code=403, detail="Tenant is not allowed.")

    def _start_chat(payload: AgentRequest) -> str:
        # Spec §15.1: derive the Correlation ID exactly ONCE, at this entry
        # point, and never regenerate it downstream (the workflow honors an
        # explicitly-passed value instead of deriving its own).
        correlation_id = payload.correlationId or LogicalRequestIdentity(
            payload.conversation.tenantId,
            payload.conversation.conversationId,
            payload.requestId,
        ).value
        logger.info(
            "Agent request started: request_id=%s channel=%s correlation_id=%s",
            payload.requestId,
            payload.channel,
            correlation_id,
        )
        return correlation_id

    def _log_chat_failure(
        payload: AgentRequest, correlation_id: str, error: BaseException, started_at: float
    ) -> None:
        # Spec §17/§15.2: never a stack trace to the caller, and log the
        # error TYPE only (never the exception's raw text, which could
        # embed request content).
        logger.error(
            "Agent request failed: request_id=%s correlation_id=%s "
            "error_type=%s elapsed_ms=%s",
            payload.requestId,
            correlation_id,
            type(error).__name__,
            round((time.perf_counter() - started_at) * 1000, 1),
        )

    async def _log_chat_success(
        payload: AgentRequest,
        correlation_id: str,
        state: dict,
        usage_metadata: dict,
        started_at: float,
        *,
        ops_runtime: OpsRuntime | None = None,
        knowledge_release_id: str | None = None,
    ) -> RequestCostSummary | None:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        _log_chat_request(payload, state, elapsed_ms=elapsed_ms, error_type=None)
        usage_fields = build_usage_report(usage_metadata).log_fields()
        logger.info(
            "Agent request usage: request_id=%s correlation_id=%s input_tokens=%s "
            "output_tokens=%s total_tokens=%s embedding_tokens=%s estimated_cost_usd=%s "
            "usage=%s",
            payload.requestId,
            correlation_id,
            usage_fields["input_tokens"],
            usage_fields["output_tokens"],
            usage_fields["total_tokens"],
            usage_fields["embedding_tokens"],
            usage_fields["estimated_cost_usd"],
            usage_fields,
        )
        execution_context = state.get("execution_context")
        counter = state.get("llm_call_counter")
        if execution_context is None:
            return None
        summary = build_request_cost_summary(
            execution_context.usage_collector,
            langchain_usage=usage_metadata,
            outcome=derive_request_outcome(state),
            elapsed_ms=elapsed_ms,
            llm_call_count=counter.count if counter else 0,
            embedding_model=resolved_settings.embedding_model,
        )
        log_request_cost(summary)
        if ops_runtime is not None:
            enriched = dict(state)
            if knowledge_release_id:
                enriched["knowledge_release_id"] = knowledge_release_id
            await ops_runtime.emitter.emit_turn(payload, enriched, cost_summary=summary)
        return summary

    def _build_response(
        state: dict,
        correlation_id: str,
        *,
        channel: str,
        cost_summary: RequestCostSummary | None = None,
    ) -> AgentResponse:
        estimated_cost_usd: float | None = None
        estimated_cost_twd: float | None = None
        cost_complete: bool | None = None
        if resolved_settings.should_show_turn_cost(channel):
            cost_complete = cost_summary.cost_complete if cost_summary else False
            if cost_summary and cost_summary.estimated_cost_usd is not None:
                estimated_cost_usd = round(cost_summary.estimated_cost_usd, 8)
                estimated_cost_twd = convert_usd_to_twd(
                    estimated_cost_usd,
                    resolved_settings.usd_twd_exchange_rate,
                )
        return AgentResponse(
            answer=state.get("final_response", ""),
            traceId=correlation_id,
            correlationId=correlation_id,
            citations=state.get("citations", []),
            images=state.get("images", []),
            issueResults=state.get("issue_results", []),
            feedbackEnabled=state.get("feedback_enabled", False),
            estimatedCostUsd=estimated_cost_usd,
            estimatedCostTwd=estimated_cost_twd,
            costComplete=cost_complete,
        )

    @app.post(
        "/agent/chat",
        response_model=AgentResponse,
        dependencies=[Depends(authorize)],
    )
    async def chat(payload: AgentRequest, request: Request) -> AgentResponse:
        _authorize_tenant(payload)
        correlation_id = _start_chat(payload)
        workflow: AgentWorkflow = request.app.state.workflow

        started_at = time.perf_counter()
        try:
            # Keep the token-usage/cost accounting commit 53124a3 added: any
            # LLM call made while running the workflow (Issue Extractor +
            # every Knowledge Service call) is captured here.
            with get_usage_metadata_callback() as usage_callback:
                state = await workflow.run(payload, correlation_id=correlation_id)
            usage_metadata = usage_callback.usage_metadata
        except Exception as error:
            _log_chat_failure(payload, correlation_id, error, started_at)
            raise HTTPException(
                status_code=503,
                detail=f"Agent service is temporarily unavailable. Correlation ID: {correlation_id}",
            ) from error

        try:
            cost_summary = await _log_chat_success(
                payload,
                correlation_id,
                state,
                usage_metadata,
                started_at,
                ops_runtime=getattr(request.app.state, "ops_runtime", None),
                knowledge_release_id=getattr(request.app.state, "knowledge_release_id", None),
            )
        except Exception as error:
            _log_chat_failure(payload, correlation_id, error, started_at)
            raise HTTPException(
                status_code=503,
                detail=f"Agent service is temporarily unavailable. Correlation ID: {correlation_id}",
            ) from error
        return _build_response(
            state, correlation_id, channel=payload.channel, cost_summary=cost_summary
        )

    @app.post(
        "/agent/chat/stream",
        dependencies=[Depends(authorize)],
    )
    async def chat_stream(payload: AgentRequest, request: Request) -> StreamingResponse:
        """Server-Sent Events variant of `/agent/chat` (progress + answer).

        Emits `stage` events while the graph runs, then exactly one terminal
        event: `response` carrying the same `AgentResponse` body `/agent/chat`
        returns, or `error` if the workflow raised.

        The error contract differs from `/agent/chat` by necessity: the HTTP
        status is committed the moment the first byte ships, so a mid-run
        failure cannot become a 503 and is delivered as an `error` event
        instead. Everything a caller can be rejected for *before* the run
        starts -- bad service token, disallowed tenant -- is still a real HTTP
        error, because those checks run before the response begins.
        """
        _authorize_tenant(payload)
        correlation_id = _start_chat(payload)
        workflow: AgentWorkflow = request.app.state.workflow

        async def events():
            # Sent before the graph starts so the Teams user sees progress
            # within one round-trip instead of waiting for the first node.
            yield _sse("stage", {"label": INITIAL_STAGE_LABEL})

            started_at = time.perf_counter()
            state: dict | None = None
            try:
                with get_usage_metadata_callback() as usage_callback:
                    async for kind, value in workflow.stream(
                        payload, correlation_id=correlation_id
                    ):
                        if kind == "stage":
                            yield _sse("stage", {"label": value})
                        elif kind == "state":
                            state = value
                usage_metadata = usage_callback.usage_metadata
            except Exception as error:  # noqa: BLE001 - cannot re-raise mid-stream, see docstring
                _log_chat_failure(payload, correlation_id, error, started_at)
                yield _sse(
                    "error",
                    {
                        "detail": "Agent service is temporarily unavailable.",
                        "correlationId": correlation_id,
                    },
                )
                return

            if state is None:
                # The graph completed without yielding a terminal state. Treat
                # it as a failure rather than shipping an empty answer.
                _log_chat_failure(
                    payload, correlation_id, RuntimeError("no state"), started_at
                )
                yield _sse(
                    "error",
                    {
                        "detail": "Agent service is temporarily unavailable.",
                        "correlationId": correlation_id,
                    },
                )
                return

            try:
                cost_summary = await _log_chat_success(
                    payload,
                    correlation_id,
                    state,
                    usage_metadata,
                    started_at,
                    ops_runtime=getattr(request.app.state, "ops_runtime", None),
                    knowledge_release_id=getattr(request.app.state, "knowledge_release_id", None),
                )
            except Exception as error:  # noqa: BLE001 - HTTP status is already committed
                _log_chat_failure(payload, correlation_id, error, started_at)
                yield _sse(
                    "error",
                    {
                        "detail": "Agent service is temporarily unavailable.",
                        "correlationId": correlation_id,
                    },
                )
                return
            yield _sse(
                "response",
                _build_response(
                    state,
                    correlation_id,
                    channel=payload.channel,
                    cost_summary=cost_summary,
                ).model_dump(mode="json"),
            )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                # Cloud Run / nginx-style proxies buffer responses by default,
                # which would defeat the point of streaming progress.
                "X-Accel-Buffering": "no",
            },
        )

    @app.post(
        "/feedback",
        dependencies=[Depends(authorize)],
    )
    async def feedback(payload: FeedbackRequest, request: Request) -> dict[str, str]:
        logger.info(
            "Feedback recorded: correlation_id=%s conversation_id=%s issue_id=%s "
            "rating=%s user_id=%s reason=%s resolved=%s",
            payload.correlationId,
            payload.conversationId,
            payload.issueId,
            payload.rating,
            payload.userId,
            payload.reason,
            payload.resolvedStatus,
        )
        ops_runtime = getattr(request.app.state, "ops_runtime", None)
        if ops_runtime is not None:
            try:
                await ops_runtime.emitter.emit_feedback(payload)
            except (OperationalEventReplayConflict, ValueError) as error:
                raise HTTPException(
                    status_code=409,
                    detail="Feedback provenance could not be verified.",
                ) from error
            except Exception as error:
                raise HTTPException(
                    status_code=503,
                    detail="Feedback persistence is temporarily unavailable.",
                ) from error
        return {"status": "recorded"}

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


def _log_chat_request(
    payload: AgentRequest,
    state: dict,
    *,
    elapsed_ms: float,
    error_type: str | None,
) -> None:
    """Emit the single structured log line required by spec §15.2.

    Fields logged (and ONLY these — never API keys/tokens/passwords/
    verification codes/full message text/a stack trace, per spec §15.2/§17):
    correlation_id, conversation_id, user_id, issue_count, issue_routes,
    faq_hit, knowledge_backend, knowledge_hit, follow_up_asked,
    ticket_created, elapsed_ms, error_type, llm_call_count.
    """
    issues = state.get("issues", [])
    issue_results = state.get("issue_results", [])
    conversation = state.get("conversation")
    counter = state.get("llm_call_counter")

    issue_routes = [f"{issue.id}:{issue.route}" for issue in issues]
    faq_hit = any(result.resultType == "FAQ_ANSWERED" for result in issue_results)
    knowledge_hit = any(result.resultType == "KNOWLEDGE_ANSWERED" for result in issue_results)
    knowledge_backends = sorted(
        {result.backend for result in issue_results if result.backend}
    )
    follow_up_asked = any(result.resultType == "NEED_MORE_INFO" for result in issue_results)
    ticket_created = any(result.resultType == "TICKET_CREATED" for result in issue_results)

    logger.info(
        "Agent request completed: request_id=%s correlation_id=%s conversation_id=%s "
        "user_id=%s issue_count=%s issue_routes=%s faq_hit=%s knowledge_backend=%s "
        "knowledge_hit=%s follow_up_asked=%s ticket_created=%s elapsed_ms=%s "
        "error_type=%s llm_call_count=%s",
        payload.requestId,
        state.get("correlation_id"),
        conversation.conversationId if conversation else None,
        payload.user.entraObjectId or payload.user.teamsUserId,
        len(issues),
        issue_routes,
        faq_hit,
        knowledge_backends,
        knowledge_hit,
        follow_up_asked,
        ticket_created,
        elapsed_ms,
        error_type,
        counter.count if counter else 0,
    )


app = create_app()
