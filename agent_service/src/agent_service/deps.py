"""Shared FastAPI dependencies and knowledge-index sync helpers."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException

from .graph import RagAgent
from .knowledge_backends import KnowledgeBackendRouter
from .knowledge_release import read_active_release_id, release_index_path
from .retrieval import HybridIndex
from .settings import RagSettings
from .source_refs import hydrate_index_sources
from .workflow import build_knowledge_service

logger = logging.getLogger(__name__)


def make_authorize(resolved_settings: RagSettings) -> Callable[..., None]:
    """Build the Bearer service-token dependency closed over ``resolved_settings``."""

    def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = resolved_settings.service_token
        if not expected:
            return
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="Invalid service token.")

    return authorize


def sync_knowledge_to_active_pointer(
    target_app: FastAPI, resolved_settings: RagSettings
) -> bool:
    """Reload the in-memory index when the portal active-release pointer moves."""
    release_dir = (
        resolved_settings.knowledge_release_dir
        or (resolved_settings.data_dir / "releases")
    )
    active_release_id = read_active_release_id(release_dir)
    if not active_release_id:
        return False
    current_release_id = getattr(target_app.state, "knowledge_release_id", None)
    if current_release_id == active_release_id:
        return False

    target_index_path = release_index_path(release_dir, active_release_id)
    if not target_index_path.exists():
        logger.warning(
            "Active release index not found for auto-sync: release_id=%s path=%s",
            active_release_id,
            target_index_path,
        )
        return False

    try:
        new_index = HybridIndex.load(
            target_index_path,
            resolved_settings.embedding_model,
        )
        hydrate_index_sources(
            new_index.chunks,
            release_dir=release_dir,
            release_id=active_release_id,
        )
        new_agent = RagAgent(resolved_settings, new_index)
        new_hybrid_service = build_knowledge_service(
            target_app.state.hybrid_settings,
            new_index,
            target_app.state.rag_model,
            release_id=active_release_id,
        )
        router: KnowledgeBackendRouter = target_app.state.knowledge_router
        router.update_service("HYBRID", new_hybrid_service)

        target_app.state.index = new_index
        target_app.state.knowledge_index_path = target_index_path
        target_app.state.knowledge_release_id = active_release_id
        target_app.state.knowledge_index_source = "portal_release"
        target_app.state.agent = new_agent
        logger.info(
            "Auto-synced knowledge index to active pointer: release_id=%s chunks=%d",
            active_release_id,
            len(new_index.chunks),
        )
        return True
    except Exception as err:
        logger.error(
            "Failed to auto-sync knowledge index to active pointer %s: %s",
            active_release_id,
            err,
        )
        return False
