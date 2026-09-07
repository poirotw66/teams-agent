"""In-memory conversation repository."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from ..contracts import ConversationContext, ConversationMessage, PendingIssueContext
from .helpers import (
    Clock,
    ConversationRepository,
    _conversation_key,
    _is_timed_out,
    _utc_now,
)

logger = logging.getLogger(__name__)

class InMemoryConversationRepository:
    """Default / Fake repository (spec §10.3: "本機或測試可使用 Fake Repository").

    Backed by plain dicts, guarded by an ``asyncio.Lock`` so concurrent
    Cloud Run requests handled by the same event loop (or concurrent tasks
    in tests) never interleave a read-modify-write.
    """

    def __init__(self, clock: Clock = _utc_now) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        # key -> conversationId of the most-recently-created conversation.
        self._latest_by_key: dict[str, str] = {}
        # conversationId -> context (source of truth for messages).
        self._by_id: dict[str, ConversationContext] = {}

    async def find_conversation(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
        timeout_hours: int,
    ) -> ConversationContext | None:
        key = _conversation_key(
            tenant_id=tenant_id,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
        )
        async with self._lock:
            conversation_id = self._latest_by_key.get(key)
            if conversation_id is None:
                return None
            context = self._by_id.get(conversation_id)
            if context is None:
                return None
            if _is_timed_out(context, timeout_hours, self._clock()):
                return None
            return context.model_copy(deep=True)

    async def create_conversation(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
        timeout_hours: int = 24,
    ) -> ConversationContext:
        key = _conversation_key(
            tenant_id=tenant_id,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
        )
        now = self._clock()
        context = ConversationContext(
            conversationId=str(uuid.uuid4()),
            startedAt=now,
            lastActivityAt=now,
            messages=[],
        )
        async with self._lock:
            self._by_id[context.conversationId] = context
            self._latest_by_key[key] = context.conversationId
        logger.info(
            "Created conversation: conversation_id=%s tenant_id=%s",
            context.conversationId,
            tenant_id or "-",
        )
        return context.model_copy(deep=True)

    async def save_message(self, conversation_id: str, message: ConversationMessage) -> None:
        async with self._lock:
            context = self._by_id.get(conversation_id)
            if context is None:
                raise LookupError(f"Unknown conversation_id: {conversation_id!r}")
            updated = context.model_copy(
                update={
                    "messages": [*context.messages, message],
                    "lastActivityAt": message.createdAt,
                }
            )
            self._by_id[conversation_id] = updated
        # Never log message.text (spec §15.2) -- ids/counts only.
        logger.info(
            "Saved conversation message: conversation_id=%s role=%s message_count=%s",
            conversation_id,
            message.role,
            len(updated.messages),
        )

    async def get_recent_messages(
        self, conversation_id: str, limit: int
    ) -> list[ConversationMessage]:
        async with self._lock:
            context = self._by_id.get(conversation_id)
            if context is None:
                return []
            messages = list(context.messages)
        if limit <= 0:
            return []
        return messages[-limit:]


