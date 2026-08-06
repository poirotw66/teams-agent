"""Legacy single-query RAG agent (spec §8.2).

Task 9 (integration) rewires this module so it no longer keeps its own copy
of the retrieve/relevance-check/rewrite/generate/citation/image logic. That
logic now lives in exactly one place, ``knowledge.HybridKnowledgeService``
(spec §3.2's "Knowledge Service via interface" requirement) — this class
delegates to it for the "does this need a knowledge lookup, and if so what's
the grounded answer" work, and keeps only what is genuinely specific to this
legacy single-query flow: the direct-vs-retrieve greeting router.

``RagAgent`` is kept (thin) rather than deleted because:

- ``test_graph.py`` exercises it directly as a standalone single-query agent.
- It is a reasonable minimal "ask one question, get one grounded answer"
  entry point independent of the full §5 multi-issue LangGraph workflow
  (``workflow.AgentWorkflow``), which is what ``/agent/chat`` now runs.

No retrieval/answer-generation code is duplicated between this module and
``knowledge.py`` any more.
"""

from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import uuid4

from langchain.chat_models import init_chat_model
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .contracts import AgentImage, AgentRequest, AgentResponse, Citation, UserContext, UserIdentity
from .knowledge import HybridKnowledgeService, KnowledgeService
from .retrieval import HybridIndex
from .settings import RagSettings
from .usage import UsageReport, build_usage_report, estimate_text_tokens


class RouteDecision(BaseModel):
    route: Literal["retrieve", "direct"] = Field(
        description="retrieve for internal support knowledge, direct only for greetings"
    )


class RagState(TypedDict):
    request: AgentRequest
    trace_id: str
    query: str
    route: Literal["retrieve", "direct"]
    answer: str
    citations: list[Citation]
    images: list[AgentImage]
    embedding_tokens: int


@dataclass(frozen=True)
class RagRunResult:
    answer: str
    trace_id: str
    citations: list[Citation]
    images: list[AgentImage]
    usage: UsageReport


ROUTE_PROMPT = """\
You route requests for an internal IT support assistant.
Use retrieve for any question that may depend on company procedures, systems, VPN,
accounts, applications, troubleshooting, contact points, or internal knowledge.
Use direct only for greetings, thanks, or casual conversation that needs no company facts.
"""

# Mirrors HybridKnowledgeService's own "no answer" marking (spec §8.4: 找不到答案時
# 明確表示未命中), but this legacy single-query flow speaks directly to the user
# rather than through the deterministic Response Builder (spec §5.3), so it owns
# its own user-facing copy here.
NO_ANSWER_TEXT = (
    "目前知識庫中沒有足夠資訊可以可靠回答這個問題。"
    "請補充系統名稱、錯誤訊息或操作情境，或聯繫資訊服務窗口。"
)


def user_context_from_identity(user: UserIdentity) -> UserContext:
    """Map the wire-level ``UserIdentity`` to the internal ``UserContext``.

    Single shared conversion point (also used by ``workflow.py``) so the
    Teams/Entra identity fields reach ``KnowledgeService`` / ``TicketService``
    consistently (spec §11.4, §12).
    """
    return UserContext(
        teamsUserId=user.teamsUserId,
        entraObjectId=user.entraObjectId,
        displayName=user.displayName,
        email=user.email,
        groups=list(user.groups),
    )


class RagAgent:
    """Legacy single-query agent: greeting-vs-retrieve routing only.

    All retrieval/answer-generation is delegated to a ``KnowledgeService``
    (default: ``HybridKnowledgeService`` wrapping ``index``), per spec §8.2.
    """

    def __init__(
        self,
        settings: RagSettings,
        index: HybridIndex,
        model: BaseChatModel | None = None,
        knowledge: KnowledgeService | None = None,
    ) -> None:
        self.settings = settings
        self.index = index
        self.model = model or (
            init_chat_model(settings.model) if settings.model else None
        )
        self.knowledge: KnowledgeService = knowledge or HybridKnowledgeService(
            settings, index, self.model
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(RagState)
        builder.add_node("route", self._route)
        builder.add_node("direct", self._direct)
        builder.add_node("search", self._search)

        builder.add_edge(START, "route")
        builder.add_conditional_edges(
            "route",
            lambda state: state["route"],
            {"direct": "direct", "retrieve": "search"},
        )
        builder.add_edge("direct", END)
        builder.add_edge("search", END)
        return builder.compile()

    async def _route(self, state: RagState) -> dict:
        query = state["query"].strip()
        normalized = query.lower().strip("!！。,.，?？ ")
        if normalized in {"hi", "hello", "嗨", "你好", "謝謝", "thanks", "thank you"}:
            return {"route": "direct"}
        if not self.model:
            return {"route": "retrieve"}

        decision = await self.model.with_structured_output(RouteDecision).ainvoke(
            [
                SystemMessage(content=ROUTE_PROMPT),
                HumanMessage(content=query),
            ]
        )
        return {"route": decision.route}

    async def _direct(self, state: RagState) -> dict:
        if not self.model:
            return {
                "answer": "你好！我是公司內部資訊客服，請告訴我你遇到的資訊問題。",
                "citations": [],
                "images": [],
            }
        response = await self.model.ainvoke(
            [
                SystemMessage(
                    content=(
                        "你是公司內部資訊客服。只回覆簡短問候，不提供未查證的公司資訊。"
                    )
                ),
                HumanMessage(content=state["query"]),
            ]
        )
        return {"answer": message_text(response), "citations": [], "images": []}

    async def _search(self, state: RagState) -> dict:
        query = state["query"]
        embedding_tokens = state.get("embedding_tokens", 0)
        if self.index.embedding_client and any(
            chunk.vector for chunk in self.index.chunks
        ):
            embedding_tokens += estimate_text_tokens(query)

        user_context = user_context_from_identity(state["request"].user)
        result = await self.knowledge.search(
            query, user_context, correlation_id=state["trace_id"]
        )
        if not result.found:
            return {
                "answer": NO_ANSWER_TEXT,
                "citations": [],
                "images": [],
                "embedding_tokens": embedding_tokens,
            }
        return {
            "answer": result.answer,
            "citations": result.sources,
            "images": result.images,
            "embedding_tokens": embedding_tokens,
        }

    async def run(self, request: AgentRequest) -> RagRunResult:
        trace_id = str(uuid4())
        with get_usage_metadata_callback() as usage_callback:
            result = await self.graph.ainvoke(
                {
                    "request": request,
                    "trace_id": trace_id,
                    "query": request.message.text,
                    "route": "retrieve",
                    "answer": "",
                    "citations": [],
                    "images": [],
                    "embedding_tokens": 0,
                }
            )
        usage = build_usage_report(
            usage_callback.usage_metadata,
            embedding_tokens=int(result.get("embedding_tokens") or 0),
            embedding_model=self.settings.embedding_model,
        )
        return RagRunResult(
            answer=result["answer"],
            trace_id=trace_id,
            citations=result["citations"],
            images=result["images"],
            usage=usage,
        )

    async def respond(self, request: AgentRequest) -> AgentResponse:
        result = await self.run(request)
        return AgentResponse(
            answer=result.answer,
            traceId=result.trace_id,
            citations=result.citations,
            images=result.images,
        )


def message_text(message: BaseMessage) -> str:
    return str(message.text).strip()
