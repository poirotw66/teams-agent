"""Composition-owned production AgentWorkflow factory for eval harnesses."""

from __future__ import annotations

from agent_service.conversation import ConversationService
from agent_service.conversation.memory import InMemoryConversationRepository
from agent_service.extractor import IssueExtractor
from agent_service.faq import FaqService
from agent_service.graph import build_chat_model
from agent_service.handoff_repository import build_handoff_repository
from agent_service.lifespan_wiring import build_knowledge_router, load_startup_index
from agent_service.prompt_runtime import ExtractorPromptRuntime, GovernanceRuntime
from agent_service.rag_models import (
    build_rag_model_bundle,
    governance_overrides_from_runtime,
)
from agent_service.settings import RagSettings
from agent_service.ticket import build_ticket_service
from agent_service.ticket_dedupe import InMemoryTicketRequestDedupeRepository
from agent_service.workflow import AgentWorkflow
from composition.agent_hooks import install_agent_hooks

__all__ = ["build_production_eval_workflow"]


def _require_live_eval_models(
    *,
    agent_model: object | None,
    answer_model: object | None,
) -> None:
    if agent_model is None:
        raise RuntimeError(
            "AgentWorkflow eval requires settings.agent_model or settings.model"
        )
    if answer_model is None:
        raise RuntimeError("AgentWorkflow eval requires a resolved RAG answer model")


def build_production_eval_workflow(
    *,
    settings: RagSettings,
    live_model: bool = False,
) -> AgentWorkflow:
    """Build a production-path ``AgentWorkflow`` for eval (Hybrid index + live models).

    Uses the same startup wiring as the agent service lifespan. Requires
    ``live_model=True`` so release reports are never scored with stubs.
    """
    if not live_model:
        raise ValueError(
            "build_production_eval_workflow requires live_model=True for release gates"
        )

    # GOVERNED prompt/FAQ runtime needs Backoffice builders registered.
    install_agent_hooks()
    index, resolved_index = load_startup_index(settings)
    governance_runtime = GovernanceRuntime.from_settings(settings)
    rag_models = build_rag_model_bundle(
        settings,
        build_chat_model=build_chat_model,
        governance_overrides=governance_overrides_from_runtime(governance_runtime),
    )
    agent_model = build_chat_model(settings.agent_model or settings.model)
    _require_live_eval_models(
        agent_model=agent_model, answer_model=rag_models.answer
    )
    knowledge_router, _hybrid_settings = build_knowledge_router(
        settings,
        index,
        rag_models.answer,
        release_id=resolved_index.release_id,
        active_file_search_store=(
            resolved_index.file_search_store or settings.gemini_file_search_store
        ),
        rag_models=rag_models,
    )
    workflow = AgentWorkflow(
        settings,
        extractor=IssueExtractor(
            settings,
            agent_model,
            prompt_runtime=ExtractorPromptRuntime(governance_runtime),
        ),
        faq_service=FaqService.from_settings(settings),
        knowledge_service=knowledge_router,
        conversation_service=ConversationService(
            InMemoryConversationRepository(), settings
        ),
        ticket_service=build_ticket_service(settings),
        handoff_repository=build_handoff_repository(settings),
        ticket_request_dedupe=InMemoryTicketRequestDedupeRepository(),
    )
    workflow.governance_runtime = governance_runtime
    return workflow
