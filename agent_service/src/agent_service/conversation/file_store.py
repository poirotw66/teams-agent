"""File-backed conversation repository."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from ..contracts import ConversationContext, ConversationMessage, PendingIssueContext
from .helpers import (
    Clock,
    ConversationRepository,
    _conversation_key,
    _is_timed_out,
    _utc_now,
)

logger = logging.getLogger(__name__)

class FileConversationRepository:
    """FILE-mode repository: one JSON file per conversation under a directory.

    Layout under ``store_path``:
      - ``index.json``: ``{conversation_key: conversation_id}``
      - ``<conversation_id>.json``: the serialized ``ConversationContext``

    Writes are crash-safe: content is written to a temp file in the same
    directory and then moved into place with ``os.replace`` (atomic on the
    same filesystem). A corrupt/unreadable file is logged and treated as
    absent rather than raised to the caller, so one bad file never takes
    down a request.
    """

    _INDEX_FILE = "index.json"

    def __init__(self, store_path: Path, clock: Clock = _utc_now) -> None:
        self._store_path = store_path
        self._clock = clock
        self._lock = asyncio.Lock()

    # -- path / low-level IO helpers ---------------------------------

    def _conversation_path(self, conversation_id: str) -> Path:
        return self._store_path / f"{conversation_id}.json"

    def _index_path(self) -> Path:
        return self._store_path / self._INDEX_FILE

    def _read_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Conversation store file unreadable, treating as absent: %s (%s)", path, exc)
            return None

    def _write_json_atomic(self, path: Path, data: dict) -> None:
        self._store_path.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex}")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, path)

    def _read_index(self) -> dict[str, str]:
        data = self._read_json(self._index_path())
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def _write_index(self, index: dict[str, str]) -> None:
        self._write_json_atomic(self._index_path(), index)

    def _read_context(self, conversation_id: str) -> ConversationContext | None:
        data = self._read_json(self._conversation_path(conversation_id))
        if data is None:
            return None
        try:
            return ConversationContext.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - tolerate any bad-file shape, never crash
            logger.warning(
                "Conversation store file failed validation, treating as absent: "
                "conversation_id=%s (%s)",
                conversation_id,
                exc,
            )
            return None

    def _write_context(self, context: ConversationContext) -> None:
        self._write_json_atomic(
            self._conversation_path(context.conversationId),
            json.loads(context.model_dump_json()),
        )

    # -- Protocol implementation --------------------------------------

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
            conversation_id = self._read_index().get(key)
            if conversation_id is None:
                return None
            context = self._read_context(conversation_id)
        if context is None:
            return None
        if _is_timed_out(context, timeout_hours, self._clock()):
            return None
        return context

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
            self._write_context(context)
            index = self._read_index()
            index[key] = context.conversationId
            self._write_index(index)
        logger.info(
            "Created conversation: conversation_id=%s tenant_id=%s",
            context.conversationId,
            tenant_id or "-",
        )
        return context

    async def save_message(self, conversation_id: str, message: ConversationMessage) -> None:
        async with self._lock:
            context = self._read_context(conversation_id)
            if context is None:
                raise LookupError(f"Unknown conversation_id: {conversation_id!r}")
            updated = context.model_copy(
                update={
                    "messages": [*context.messages, message],
                    "lastActivityAt": message.createdAt,
                }
            )
            self._write_context(updated)
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
            context = self._read_context(conversation_id)
        if context is None or limit <= 0:
            return []
        return list(context.messages[-limit:])


