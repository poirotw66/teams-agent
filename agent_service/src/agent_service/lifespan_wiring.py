"""Startup wiring helpers for the agent service lifespan."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from fastapi import FastAPI

from .conversation import ConversationService, build_repository
from .extractor import IssueExtractor
from .faq import FaqService
from .graph import RagAgent, build_chat_model
from .handoff_repository import build_handoff_repository
from .indexer import build_index
from .knowledge_backends import KnowledgeBackendRouter, build_backend_state_store
from .knowledge_release import resolve_knowledge_index
from .knowledge_release_control import build_firestore_release_control
from .operations.runtime import build_ops_runtime
from .retrieval import HybridIndex, hybrid_index_fusion_kwargs
from .settings import RagSettings
from .source_refs import hydrate_index_sources
from .ticket import build_ticket_service
from .ticket_dedupe import build_ticket_request_dedupe
from .workflow import AgentWorkflow, build_knowledge_service

logger = logging.getLogger(__name__)


def load_startup_index(settings: RagSettings) -> tuple[HybridIndex, Any]:
    """Resolve and load the knowledge index for process startup."""
    resolved_index = resolve_knowledge_index(settings)
    fusion_kwargs = hybrid_index_fusion_kwargs(settings)
    if resolved_index.source == "auto_build" and not resolved_index.index_path.exists():
        index = build_index(settings)
    elif not resolved_index.index_path.exists():
        raise FileNotFoundError(f"Knowledge index not found: {resolved_index.index_path}")
    else:
        index = HybridIndex.load(
            resolved_index.index_path,
            settings.embedding_model,
            **fusion_kwargs,
        )

    release_dir = resolved_index.release_dir or (
        settings.knowledge_release_dir or settings.data_dir / "releases"
    )
    hydrate_index_sources(
        index.chunks,
        release_dir=release_dir,
        release_id=resolved_index.release_id,
    )
    return index, resolved_index


def build_knowledge_router(
    settings: RagSettings,
    index: HybridIndex,
    rag_model: Any,
    *,
    release_id: str | None,
    active_file_search_store: str | None,
) -> tuple[KnowledgeBackendRouter, Any]:
    """Build hybrid/file-search knowledge services and the backend router."""
    hybrid_settings = replace(settings, knowledge_service_mode="HYBRID")
    knowledge_services = {
        "HYBRID": build_knowledge_service(
            hybrid_settings,
            index,
            rag_model,
            release_id=release_id,
        )
    }
    unavailable_backends: dict[str, str] = {}
    if active_file_search_store:
        gemini_settings = replace(
            settings,
            knowledge_service_mode="GEMINI_FILE_SEARCH",
            gemini_file_search_store=active_file_search_store,
        )
        knowledge_services["GEMINI_FILE_SEARCH"] = build_knowledge_service(
            gemini_settings,
            index,
            rag_model,
            release_id=release_id,
        )
    else:
        unavailable_backends["GEMINI_FILE_SEARCH"] = "尚未設定 GEMINI_FILE_SEARCH_STORE"
    router = KnowledgeBackendRouter(
        knowledge_services,
        settings.knowledge_service_mode,
        unavailable_backends,
        build_backend_state_store(settings),
        settings,
    )
    return router, hybrid_settings


def build_startup_workflow(
    settings: RagSettings,
    *,
    index: HybridIndex,
    resolved_index: Any,
    rag_model: Any,
    agent_model: Any,
) -> tuple[AgentWorkflow, KnowledgeBackendRouter, Any, Any, Any]:
    """Construct FAQ/conversation/ticket collaborators and the agent workflow."""
    from .prompt_runtime import ExtractorPromptRuntime, GovernanceRuntime

    faq_service = FaqService.from_settings(settings)
    conversation_service = ConversationService(build_repository(settings), settings)
    handoff_repository = build_handoff_repository(settings)
    ticket_service = build_ticket_service(settings)
    active_file_search_store = (
        resolved_index.file_search_store or settings.gemini_file_search_store
    )
    knowledge_router, hybrid_settings = build_knowledge_router(
        settings,
        index,
        rag_model,
        release_id=resolved_index.release_id,
        active_file_search_store=active_file_search_store,
    )
    governance_runtime = GovernanceRuntime.from_settings(settings)
    extractor = IssueExtractor(
        settings,
        agent_model,
        prompt_runtime=ExtractorPromptRuntime(governance_runtime),
    )
    if (
        settings.rag_require_file_search_acl
        and active_file_search_store
        and not settings.gemini_file_search_enforce_acl
    ):
        raise RuntimeError(
            "Refusing to start with GEMINI_FILE_SEARCH_ENFORCE_ACL=false while "
            "RAG_REQUIRE_FILE_SEARCH_ACL=true."
        )
    workflow = AgentWorkflow(
        settings,
        extractor=extractor,
        faq_service=faq_service,
        knowledge_service=knowledge_router,
        conversation_service=conversation_service,
        ticket_service=ticket_service,
        handoff_repository=handoff_repository,
        ticket_request_dedupe=build_ticket_request_dedupe(settings),
    )
    workflow.governance_runtime = governance_runtime
    return workflow, knowledge_router, hybrid_settings, governance_runtime, handoff_repository


def attach_app_state(
    app: FastAPI,
    settings: RagSettings,
    *,
    index: HybridIndex,
    resolved_index: Any,
    agent: RagAgent,
    knowledge_router: KnowledgeBackendRouter,
    workflow: AgentWorkflow,
    governance_runtime: Any,
    handoff_repository: Any,
    rag_model: Any,
    hybrid_settings: Any,
) -> None:
    """Populate FastAPI app.state with startup collaborators."""
    app.state.index = index
    app.state.knowledge_index_path = resolved_index.index_path
    app.state.knowledge_release_id = resolved_index.release_id
    app.state.knowledge_index_source = resolved_index.source
    app.state.knowledge_index_artifact = resolved_index.artifact
    app.state.knowledge_release_control = (
        build_firestore_release_control(settings)
        if settings.knowledge_release_store_mode == "GCS"
        else None
    )
    app.state.agent = agent
    app.state.knowledge_router = knowledge_router
    app.state.workflow = workflow
    app.state.governance_runtime = governance_runtime
    app.state.handoff_repository = handoff_repository
    app.state.rag_model = rag_model
    app.state.hybrid_settings = hybrid_settings


def configure_pricing_and_ops(app: FastAPI, settings: RagSettings) -> None:
    """Attach ops runtime and pricing service to app.state."""
    from .pricing_bootstrap import build_and_configure_pricing_service

    ops_runtime = build_ops_runtime()
    app.state.ops_runtime = ops_runtime
    if ops_runtime is not None:
        logger.info(
            "Operational events enabled: store=%s taxonomy=%s",
            ops_runtime.settings.store_mode,
            ops_runtime.taxonomy.version,
        )
        app.state.pricing_service = build_and_configure_pricing_service(
            ops_store_path=ops_runtime.settings.store_path,
            audit_store=ops_runtime.audit_store,
            environment=ops_runtime.settings.environment,
        )
    else:
        app.state.pricing_service = build_and_configure_pricing_service(
            environment=settings.deployment_environment,
        )


def log_startup_ready(settings: RagSettings, index: HybridIndex) -> None:
    logger.info(
        "Agentic RAG ready: chunks=%s agent_model=%s rag_model=%s embeddings=%s "
        "knowledge_mode=%s ticket_mode=%s",
        len(index.chunks),
        settings.agent_model or settings.model or "extractive-local",
        settings.model or "extractive-local",
        settings.embedding_model or "sparse-only",
        settings.knowledge_service_mode,
        settings.ticket_service_mode,
    )


async def startup_agent_runtime(app: FastAPI, settings: RagSettings) -> None:
    """Wire all startup collaborators onto ``app.state``."""
    import asyncio

    index, resolved_index = await asyncio.to_thread(load_startup_index, settings)
    agent = await asyncio.to_thread(RagAgent, settings, index)
    rag_model = build_chat_model(settings.model, temperature=0.0)
    agent_model = build_chat_model(
        settings.agent_model or settings.model,
        temperature=0.0,
    )
    (
        workflow,
        knowledge_router,
        hybrid_settings,
        governance_runtime,
        handoff_repository,
    ) = build_startup_workflow(
        settings,
        index=index,
        resolved_index=resolved_index,
        rag_model=rag_model,
        agent_model=agent_model,
    )
    attach_app_state(
        app,
        settings,
        index=index,
        resolved_index=resolved_index,
        agent=agent,
        knowledge_router=knowledge_router,
        workflow=workflow,
        governance_runtime=governance_runtime,
        handoff_repository=handoff_repository,
        rag_model=rag_model,
        hybrid_settings=hybrid_settings,
    )
    configure_pricing_and_ops(app, settings)
    from .observability import configure_tracing

    configure_tracing(
        service_name=settings.otel_service_name,
        enabled=settings.otel_enabled,
        exporter_endpoint=settings.otel_exporter_endpoint,
    )
    log_startup_ready(settings, index)
