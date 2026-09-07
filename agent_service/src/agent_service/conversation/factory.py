"""Conversation repository factory."""
from __future__ import annotations

import logging
import os
from typing import Any

from ..settings import RagSettings
from .file_store import FileConversationRepository
from .firestore_store import FirestoreConversationRepository
from .helpers import Clock, ConversationRepository, _utc_now
from .memory import InMemoryConversationRepository

logger = logging.getLogger(__name__)


def _build_firestore_client(settings: RagSettings):
    """Construct the Firestore AsyncClient, importing the SDK lazily.

    ``google-cloud-firestore`` is an optional dependency (extras:
    ``firestore``) so MEMORY/FILE deployments and the test suite never need
    it installed. Project and database default to whatever Application
    Default Credentials resolve to, which on Cloud Run is the service's own
    project and the ``(default)`` database.
    """
    try:
        from google.cloud.firestore import AsyncClient
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RuntimeError(
            "CONVERSATION_REPOSITORY_MODE=FIRESTORE requires the 'firestore' extra: "
            "uv pip install '.[firestore]' (or add google-cloud-firestore)."
        ) from exc

    kwargs: dict[str, Any] = {}
    if settings.conversation_firestore_project:
        kwargs["project"] = settings.conversation_firestore_project
    if settings.conversation_firestore_database:
        kwargs["database"] = settings.conversation_firestore_database
    return AsyncClient(**kwargs)


def build_repository(
    settings: RagSettings,
    clock: Clock = _utc_now,
    firestore_client: Any | None = None,
) -> ConversationRepository:
    """Factory honoring ``settings.conversation_repository_mode`` (spec §10.3).

    ``firestore_client`` is an injection point for tests; production passes
    nothing and the real client is built from settings.
    """
    mode = settings.conversation_repository_mode
    if mode == "MEMORY":
        return InMemoryConversationRepository(clock=clock)
    if mode == "FILE":
        store_path = settings.conversation_store_path or (settings.data_dir / "conversations")
        return FileConversationRepository(store_path, clock=clock)
    if mode == "FIRESTORE":
        client = (
            firestore_client
            if firestore_client is not None
            else _build_firestore_client(settings)
        )
        return FirestoreConversationRepository(
            client,
            collection=settings.conversation_firestore_collection,
            retention_hours=settings.conversation_retention_days * 24,
            # Keep a tail comfortably larger than the history window so the
            # trimming in ConversationService, not the repository, decides
            # what the extractor sees.
            context_message_limit=max(settings.max_history_messages * 2, 20),
            clock=clock,
        )
    raise ValueError(f"Unsupported CONVERSATION_REPOSITORY_MODE: {mode!r}")


