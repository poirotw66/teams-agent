import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from langchain_core.callbacks import get_usage_metadata_callback

from .contracts import (
    AgentRequest,
    AgentResponse,
    FeedbackRequest,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from .conversation import ConversationService, build_repository
from .extractor import IssueExtractor
from .faq import FaqService
from .graph import RagAgent
from .indexer import build_index
from .retrieval import HybridIndex
from .settings import RagSettings
from .ticket import build_ticket_service
from .usage import build_usage_report
from .workflow import AgentWorkflow, build_knowledge_service

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

        # Legacy single-query agent (spec §8.2 delegate). Kept for the
        # standalone /retrieval-adjacent use case and its own tests; the
        # LangGraph workflow below (spec §5) is what /agent/chat runs.
        agent = RagAgent(resolved_settings, index)

        # Build every §5 collaborator ONCE here (not per request):
        # FAQ / Conversation / Ticket / Knowledge services + the Issue
        # Extractor, then wire them into a single AgentWorkflow instance.
        faq_service = FaqService.from_settings(resolved_settings)
        conversation_service = ConversationService(
            build_repository(resolved_settings), resolved_settings
        )
        ticket_service = build_ticket_service(resolved_settings)
        knowledge_service = build_knowledge_service(
            resolved_settings, index, agent.model
        )
        extractor = IssueExtractor(resolved_settings, agent.model)
        workflow = AgentWorkflow(
            resolved_settings,
            extractor=extractor,
            faq_service=faq_service,
            knowledge_service=knowledge_service,
            conversation_service=conversation_service,
            ticket_service=ticket_service,
        )

        app.state.index = index
        app.state.agent = agent
        app.state.workflow = workflow
        logger.info(
            "Agentic RAG ready: chunks=%s model=%s embeddings=%s "
            "knowledge_mode=%s ticket_mode=%s",
            len(index.chunks),
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

        # Spec §15.1: derive the Correlation ID exactly ONCE, at this entry
        # point, and never regenerate it downstream (workflow.run honors an
        # explicitly-passed value instead of deriving its own).
        correlation_id = payload.correlationId or str(uuid.uuid4())

        workflow: AgentWorkflow = request.app.state.workflow
        logger.info(
            "Agent request started: request_id=%s channel=%s correlation_id=%s",
            payload.requestId,
            payload.channel,
            correlation_id,
        )

        started_at = time.perf_counter()
        error_type: str | None = None
        try:
            # Keep the token-usage/cost accounting commit 53124a3 added: any
            # LLM call made while running the workflow (Issue Extractor +
            # every Knowledge Service call) is captured here.
            with get_usage_metadata_callback() as usage_callback:
                state = await workflow.run(payload, correlation_id=correlation_id)
            usage = build_usage_report(usage_callback.usage_metadata)
        except Exception as error:
            error_type = type(error).__name__
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
            # Spec §17/§15.2: never a stack trace to the caller, and log the
            # error TYPE only (never the exception's raw text, which could
            # embed request content).
            logger.error(
                "Agent request failed: request_id=%s correlation_id=%s "
                "error_type=%s elapsed_ms=%s",
                payload.requestId,
                correlation_id,
                error_type,
                elapsed_ms,
            )
            raise HTTPException(
                status_code=503,
                detail=f"Agent service is temporarily unavailable. Correlation ID: {correlation_id}",
            ) from error

        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        _log_chat_request(payload, state, elapsed_ms=elapsed_ms, error_type=error_type)
        usage_fields = usage.log_fields()
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

        issue_results = state.get("issue_results", [])
        return AgentResponse(
            answer=state.get("final_response", ""),
            traceId=correlation_id,
            correlationId=correlation_id,
            citations=state.get("citations", []),
            images=state.get("images", []),
            issueResults=issue_results,
            feedbackEnabled=state.get("feedback_enabled", False),
        )

    @app.post(
        "/feedback",
        dependencies=[Depends(authorize)],
    )
    async def feedback(payload: FeedbackRequest) -> dict[str, str]:
        # Spec §14/§3.3: POC scope does not require a persistent feedback
        # store. We log it in structured form so it can be tailed/exported
        # for the FAQ/RAG solve-rate analysis §14 describes; a real store
        # (e.g. a BigQuery sink or a feedback table) would read this same
        # structured log, or this handler could write to it directly,
        # without any other part of the system changing.
        logger.info(
            "Feedback recorded: correlation_id=%s conversation_id=%s issue_id=%s "
            "rating=%s user_id=%s",
            payload.correlationId,
            payload.conversationId,
            payload.issueId,
            payload.rating,
            payload.userId,
        )
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
