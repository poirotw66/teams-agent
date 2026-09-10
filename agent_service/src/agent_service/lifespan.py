"""Application lifespan: build and wire runtime collaborators once at startup."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import AsyncIterator

from fastapi import FastAPI

from .conversation import ConversationService, build_repository
from .extractor import IssueExtractor
from .faq import FaqService
from .graph import RagAgent, build_chat_model
from .handoff_repository import build_handoff_repository
from .indexer import build_index
from .knowledge_backends import KnowledgeBackendRouter, build_backend_state_store
from .knowledge_release import resolve_knowledge_index
from .operations.runtime import build_ops_runtime
from .retrieval import HybridIndex
from .settings import RagSettings
from .source_refs import hydrate_index_sources
from .ticket import build_ticket_service
from .ticket_dedupe import build_ticket_request_dedupe
from .workflow import AgentWorkflow, build_knowledge_service

logger = logging.getLogger(__name__)


def build_lifespan(resolved_settings: RagSettings):
    """Return a FastAPI lifespan context manager bound to ``resolved_settings``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

        release_dir = (
            resolved_settings.knowledge_release_dir
            or (resolved_settings.data_dir / "releases")
        )
        hydrate_index_sources(
            index.chunks,
            release_dir=release_dir,
            release_id=resolved_index.release_id,
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
            "HYBRID": build_knowledge_service(
                hybrid_settings,
                index,
                rag_model,
                release_id=resolved_index.release_id,
            )
        }
        unavailable_backends: dict[str, str] = {}
        if resolved_settings.gemini_file_search_store:
            gemini_settings = replace(
                resolved_settings, knowledge_service_mode="GEMINI_FILE_SEARCH"
            )
            knowledge_services["GEMINI_FILE_SEARCH"] = build_knowledge_service(
                gemini_settings,
                index,
                rag_model,
                release_id=resolved_index.release_id,
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
        from .prompt_runtime import ExtractorPromptRuntime, GovernanceRuntime

        governance_runtime = GovernanceRuntime.from_settings(resolved_settings)
        extractor = IssueExtractor(
            resolved_settings,
            agent_model,
            prompt_runtime=ExtractorPromptRuntime(governance_runtime),
        )
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
        workflow.governance_runtime = governance_runtime

        app.state.index = index
        app.state.knowledge_index_path = resolved_index.index_path
        app.state.knowledge_release_id = resolved_index.release_id
        app.state.knowledge_index_source = resolved_index.source
        app.state.agent = agent
        app.state.knowledge_router = knowledge_router
        app.state.workflow = workflow
        app.state.governance_runtime = governance_runtime
        app.state.handoff_repository = handoff_repository
        app.state.rag_model = rag_model
        app.state.hybrid_settings = hybrid_settings
        ops_runtime = build_ops_runtime()
        app.state.ops_runtime = ops_runtime
        if ops_runtime is not None:
            logger.info(
                "Operational events enabled: store=%s taxonomy=%s",
                ops_runtime.settings.store_mode,
                ops_runtime.taxonomy.version,
            )
            from .pricing_bootstrap import build_and_configure_pricing_service

            app.state.pricing_service = build_and_configure_pricing_service(
                ops_store_path=ops_runtime.settings.store_path,
                audit_store=ops_runtime.audit_store,
                environment=ops_runtime.settings.environment,
            )
        else:
            # Ops disabled: still prefer governed rates when a pricing store exists.
            from .pricing_bootstrap import build_and_configure_pricing_service

            app.state.pricing_service = build_and_configure_pricing_service(
                environment=resolved_settings.deployment_environment,
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

    return lifespan
