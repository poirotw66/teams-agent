"""Conversation seeding helpers for retrieval / workflow evaluation harnesses.

Production multi-turn resolution goes through ``ConversationService`` and the
AgentWorkflow extractor path. Eval runners must seed prior turns the same way
instead of concatenating ``priorTurn`` into a synthetic retrieval string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import ConversationContext, ConversationMessage
from .conversation.memory import InMemoryConversationRepository
from .conversation.service import ConversationService
from .issue_trust import issue_retrieval_text
from .settings import RagSettings

EVAL_TENANT_ID = "rag-eval"
EVAL_USER_ID = "rag-eval-user"


@dataclass(frozen=True)
class EvalConversationHandles:
    """Isolated conversation identity for one eval case."""

    service: ConversationService
    repository: InMemoryConversationRepository
    tenant_id: str
    teams_conversation_id: str
    teams_user_id: str
    conversation: ConversationContext


async def create_eval_conversation(
    *,
    case_id: str,
    settings: RagSettings,
    tenant_id: str = EVAL_TENANT_ID,
    teams_user_id: str = EVAL_USER_ID,
) -> EvalConversationHandles:
    """Create an isolated in-memory conversation for one eval case."""
    repository = InMemoryConversationRepository()
    service = ConversationService(repository=repository, settings=settings)
    teams_conversation_id = f"rag-eval-{case_id}"
    conversation = await service.load_or_create(
        tenant_id=tenant_id,
        teams_conversation_id=teams_conversation_id,
        teams_user_id=teams_user_id,
    )
    return EvalConversationHandles(
        service=service,
        repository=repository,
        tenant_id=tenant_id,
        teams_conversation_id=teams_conversation_id,
        teams_user_id=teams_user_id,
        conversation=conversation,
    )


async def seed_prior_turn(
    handles: EvalConversationHandles,
    *,
    prior_turn: str,
    request_id: str,
    correlation_id: str | None = None,
) -> None:
    """Seed the prior user turn through ConversationService (production path)."""
    text = str(prior_turn or "").strip()
    if not text:
        return
    await handles.service.record_message(
        handles.conversation.conversationId,
        role="user",
        text=text,
        request_id=f"{request_id}-prior",
        correlation_id=correlation_id,
        follow_up_state="NONE",
    )
    # Stub assistant acknowledgment so the second turn has a completed prior round.
    await handles.service.record_message(
        handles.conversation.conversationId,
        role="assistant",
        text="已記錄您的問題，請補充細節。",
        request_id=f"{request_id}-prior-assistant",
        correlation_id=correlation_id,
        follow_up_state="NONE",
    )


async def resolve_follow_up_retrieval_query(
    *,
    handles: EvalConversationHandles,
    query: str,
    extractor: Any | None,
    execution_context: Any | None = None,
) -> str:
    """Resolve the current turn using ConversationService history + extractor.

    Eval harnesses must not concatenate ``priorTurn`` with ``query``. When an
    extractor is unavailable, callers should exclude the multi-turn case.
    """
    history = await handles.service.get_history(handles.conversation.conversationId)
    if extractor is None:
        raise RuntimeError(
            "multi-turn eval requires an IssueExtractor; do not concatenate priorTurn"
        )
    outcome = await extractor.extract(
        text=query,
        history=list(history),
        faq_keys=[],
        correlation_id=getattr(execution_context, "correlation_id", None),
        conversation_id=handles.conversation.conversationId,
        tenant_id=handles.tenant_id,
        execution_context=execution_context,
    )
    issues = list(getattr(outcome, "issues", []) or [])
    if not issues:
        return query
    return issue_retrieval_text(issues[0], user_utterance=query)


def history_texts(messages: list[ConversationMessage]) -> list[str]:
    return [message.text for message in messages]


__all__ = [
    "EVAL_TENANT_ID",
    "EVAL_USER_ID",
    "EvalConversationHandles",
    "create_eval_conversation",
    "history_texts",
    "resolve_follow_up_retrieval_query",
    "seed_prior_turn",
]
