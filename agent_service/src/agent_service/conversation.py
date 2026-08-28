"""Conversation Repository & Service (spec §3.2, §10, §18.4).

Scope (spec §10.1): Conversation exists ONLY to support

- 連續問答 (multi-turn follow-up)
- 使用者補充資訊 (user-supplied missing info)
- 工單確認 (ticket confirmation)
- 最近對話上下文 (recent context window)

It is explicitly NOT a case-management system (no full issue lifecycle, no
case history browsing, no audit trail beyond what's needed for the above).

Per spec §3.2 the LangGraph workflow must depend only on the
``ConversationRepository`` Protocol below, never on a specific database.
Per spec §10.3, MongoDB (or any other product) must not be hard-coded as
the only option: this module ships three implementations selected via
``settings.conversation_repository_mode``:

- ``MEMORY``: in-memory Fake, the default for local dev/tests
  ("本機或測試可使用 Fake Repository").
- ``FILE``: local JSON files, for single-process local runs that should
  survive a restart.
- ``FIRESTORE``: managed Google Cloud Firestore, the only mode that
  survives Cloud Run's scale-to-zero and multi-instance routing. See
  ``FirestoreConversationRepository`` for the document layout and the TTL
  policy operators must enable.

Adding a further backend (Mongo, PostgreSQL, Redis) means adding one class
here and one branch in ``build_repository`` -- the workflow never changes.

Isolation (spec §18.4): conversations are keyed by
``(tenant_id, teams_conversation_id, teams_user_id)`` so that neither a
different user nor a different Teams conversation can ever see another
party's context -- see ``_conversation_key``.

Logging (spec §15.2): this module must NEVER log full message text at INFO
(或任何 level 記錄完整敏感對話). Only ids, roles and counts are logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .contracts import ConversationContext, ConversationMessage, PendingIssueContext
from .settings import RagSettings

logger = logging.getLogger(__name__)

# A clock is injected everywhere so tests can control time without sleeping.
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation_key(
    *, tenant_id: str | None, teams_conversation_id: str, teams_user_id: str
) -> str:
    """Build the isolation key for a conversation (spec §18.4).

    Different users and different Teams conversations must never share
    context, so the key is the composite of all three identifiers. A
    missing tenant id (e.g. local/dev) is normalized to ``"-"`` so it still
    participates in the key deterministically.
    """
    tenant = tenant_id or "-"
    return f"{tenant}::{teams_conversation_id}::{teams_user_id}"


class ConversationRepository(Protocol):
    """Storage interface for conversation context (spec §10.3, §3.2).

    Implementations MUST NOT be assumed to be MongoDB or any other specific
    product (spec §10.3). All methods are async so a future networked
    implementation (e.g. a managed DB) is a drop-in replacement.
    """

    async def find_conversation(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
        timeout_hours: int,
    ) -> ConversationContext | None:
        """Return the ACTIVE conversation for this key, or None.

        "Active" means: a conversation exists for this
        (tenant_id, teams_conversation_id, teams_user_id) key AND its
        ``lastActivityAt`` is within ``timeout_hours`` of now (spec §10.2).
        A timed-out conversation is treated as if it does not exist -- the
        caller (``ConversationService.load_or_create``) is responsible for
        creating a fresh one.
        """
        ...

    async def create_conversation(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
    ) -> ConversationContext:
        """Create and persist a brand-new conversation for this key.

        The new conversation becomes the "active" one for the key -- a
        subsequent ``find_conversation`` call (before timeout) returns it.
        """
        ...

    async def save_message(self, conversation_id: str, message: ConversationMessage) -> None:
        """Append ``message`` to the conversation and bump ``lastActivityAt``."""
        ...

    async def get_recent_messages(
        self, conversation_id: str, limit: int
    ) -> list[ConversationMessage]:
        """Return up to ``limit`` most recent messages, oldest-first.

        i.e. if there are more than ``limit`` messages, the oldest ones are
        dropped and the result is the tail of the conversation in normal
        chronological (ascending ``createdAt``) order -- ready to feed
        directly into an LLM prompt without needing to reverse it.
        """
        ...


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


class FirestoreConversationRepository:
    """FIRESTORE-mode repository: managed store that survives scale-to-zero.

    Why this exists: MEMORY loses every conversation when a Cloud Run
    instance is recycled, and FILE is per-instance local disk -- which on
    Cloud Run is both ephemeral AND not shared between instances, so two
    turns of the same conversation can land on different instances and see
    different state. Firestore is the POC-appropriate managed option per
    spec §10.3: serverless (no VPC connector, no idle cost with
    scale-to-zero), reachable from Cloud Run over ADC, and it has a native
    TTL policy for data retention.

    Document layout (``collection`` = ``CONVERSATION_FIRESTORE_COLLECTION``):

    - ``{collection}/{conversationId}`` -- conversation metadata:
      ``conversationKey``, ``tenantId``, ``startedAt``, ``lastActivityAt``,
      ``expiresAt``.
    - ``{collection}/{conversationId}/messages/{messageId}`` -- one doc per
      message: ``role``, ``text``, ``createdAt``, ``correlationId``,
      ``followUpState``, ``pendingIssues``, ``sortKey``, ``expiresAt``.
    - ``{collection}_keys/{sha256(conversationKey)}`` -- the key index,
      mapping an isolation key (spec §18.4) to its newest conversation id.
      This mirrors ``FileConversationRepository``'s ``index.json`` and
      keeps ``find_conversation`` a point read, so no composite index has
      to be created or maintained.

    Concurrency: messages are separate documents, so appending is a single
    atomic create with no read-modify-write -- two Cloud Run instances
    handling the same conversation cannot clobber each other's message the
    way an array-append would.

    Ordering comes from the ``sortKey`` field
    (``{createdAt microseconds}-{per-instance counter}-{random}``), which
    sorts lexicographically in insertion order; the counter keeps ordering
    stable even when two messages share a timestamp. Two messages written
    by *different* instances within the same microsecond are genuinely
    concurrent and their relative order is unspecified.

    ``sortKey`` is a regular field, deliberately, even though the document
    id already holds the same value: Firestore auto-creates single-field
    indexes for regular fields in BOTH directions, but descending order on
    ``__name__`` requires a composite index that would have to be created
    and maintained out-of-band. Verified against live Firestore by
    ``scripts/firestore_verification.py`` -- ordering by ``__name__``
    descending fails there with FAILED_PRECONDITION.

    Retention (§10.2): every document carries ``expiresAt`` =
    ``lastActivityAt + retention_hours``. Firestore does not act on that
    field by itself -- operators must enable a TTL policy on ``expiresAt``
    for the ``{collection}``, ``{collection}_keys`` and ``messages``
    collection group (see ``deploy/README.md``). Conversation timeout
    itself never depends on TTL having run: ``find_conversation`` always
    re-checks ``lastActivityAt`` against ``timeout_hours``, so a
    not-yet-collected document is still correctly treated as absent.
    """

    def __init__(
        self,
        client: Any,
        *,
        collection: str = "conversations",
        retention_hours: int = 24,
        context_message_limit: int = 50,
        clock: Clock = _utc_now,
    ) -> None:
        self._client = client
        self._collection = collection
        self._keys_collection = f"{collection}_keys"
        self._retention_hours = retention_hours
        self._context_message_limit = context_message_limit
        self._clock = clock
        # Tie-breaker for message ids written by this instance (see class doc).
        self._sequence = itertools.count()

    # -- helpers -------------------------------------------------------

    def _expires_at(self, last_activity: datetime) -> datetime:
        return last_activity + timedelta(hours=self._retention_hours)

    @staticmethod
    def _key_document_id(key: str) -> str:
        """Hash the isolation key into a safe, fixed-length document id.

        The raw key contains ids joined by ``::`` and has no length bound,
        while Firestore document ids may not contain ``/`` and are capped
        at 1500 bytes. The raw key is still stored as a field for support
        lookups.
        """
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _next_sort_key(self, created_at: datetime) -> str:
        """Build the lexicographically-ordered key for a new message.

        Used as both the document id and the ``sortKey`` field -- see the
        class docstring for why the query orders on the field.
        """
        micros = int(created_at.timestamp() * 1_000_000)
        return f"{micros:020d}-{next(self._sequence):06d}-{uuid.uuid4().hex[:8]}"

    def _conversation_doc(self, conversation_id: str):
        return self._client.collection(self._collection).document(conversation_id)

    def _messages_collection(self, conversation_id: str):
        return self._conversation_doc(conversation_id).collection("messages")

    @staticmethod
    def _to_datetime(value: Any) -> datetime | None:
        """Normalize a Firestore timestamp to an aware UTC ``datetime``.

        Firestore returns ``DatetimeWithNanoseconds`` (a ``datetime``
        subclass); a Fake or a legacy document may hold an ISO string.
        """
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    def _message_from_doc(self, data: dict) -> ConversationMessage | None:
        created_at = self._to_datetime(data.get("createdAt"))
        if created_at is None:
            return None
        try:
            return ConversationMessage(
                role=data.get("role"),
                text=data.get("text") or "",
                createdAt=created_at,
                correlationId=data.get("correlationId"),
                followUpState=data.get("followUpState") or "NONE",
                pendingIssues=data.get("pendingIssues") or [],
            )
        except Exception as exc:  # noqa: BLE001 - one bad doc must not fail a request
            logger.warning("Skipping malformed conversation message document (%s)", exc)
            return None

    async def _read_messages(self, conversation_id: str, limit: int) -> list[ConversationMessage]:
        """Return the ``limit`` newest messages, re-sorted oldest-first."""
        if limit <= 0:
            return []
        # Order by the sortKey FIELD, not by __name__: both hold the same
        # value, but only the field gets an automatic descending index.
        query = (
            self._messages_collection(conversation_id)
            .order_by("sortKey", direction="DESCENDING")
            .limit(limit)
        )
        newest_first: list[ConversationMessage] = []
        async for snapshot in query.stream():
            message = self._message_from_doc(snapshot.to_dict() or {})
            if message is not None:
                newest_first.append(message)
        newest_first.reverse()
        return newest_first

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
        key_snapshot = await (
            self._client.collection(self._keys_collection)
            .document(self._key_document_id(key))
            .get()
        )
        if not key_snapshot.exists:
            return None
        conversation_id = (key_snapshot.to_dict() or {}).get("conversationId")
        if not conversation_id:
            return None

        snapshot = await self._conversation_doc(conversation_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        started_at = self._to_datetime(data.get("startedAt"))
        last_activity_at = self._to_datetime(data.get("lastActivityAt"))
        if started_at is None or last_activity_at is None:
            logger.warning(
                "Conversation document missing timestamps, treating as absent: "
                "conversation_id=%s",
                conversation_id,
            )
            return None

        context = ConversationContext(
            conversationId=conversation_id,
            startedAt=started_at,
            lastActivityAt=last_activity_at,
            messages=[],
        )
        if _is_timed_out(context, timeout_hours, self._clock()):
            return None

        # Only the message tail is attached: callers read at most
        # MAX_HISTORY_MESSAGES via get_recent_messages, and the workflow
        # only inspects the last message (pending-ticket-offer check).
        messages = await self._read_messages(conversation_id, self._context_message_limit)
        return context.model_copy(update={"messages": messages})

    async def create_conversation(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
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
        await self._conversation_doc(context.conversationId).set(
            {
                "conversationKey": key,
                "tenantId": tenant_id,
                "startedAt": now,
                "lastActivityAt": now,
                "expiresAt": self._expires_at(now),
            }
        )
        # Written second so the key never points at a conversation document
        # that does not exist yet.
        await self._client.collection(self._keys_collection).document(
            self._key_document_id(key)
        ).set(
            {
                "conversationKey": key,
                "conversationId": context.conversationId,
                "updatedAt": now,
                "expiresAt": self._expires_at(now),
            }
        )
        logger.info(
            "Created conversation: conversation_id=%s tenant_id=%s",
            context.conversationId,
            tenant_id or "-",
        )
        return context

    async def save_message(self, conversation_id: str, message: ConversationMessage) -> None:
        snapshot = await self._conversation_doc(conversation_id).get()
        if not snapshot.exists:
            raise LookupError(f"Unknown conversation_id: {conversation_id!r}")

        expires_at = self._expires_at(message.createdAt)
        sort_key = self._next_sort_key(message.createdAt)
        await self._messages_collection(conversation_id).document(sort_key).set(
            {
                "role": message.role,
                "text": message.text,
                "createdAt": message.createdAt,
                "correlationId": message.correlationId,
                "followUpState": message.followUpState,
                "pendingIssues": [
                    pending.model_dump(mode="json") for pending in message.pendingIssues
                ],
                "sortKey": sort_key,
                "expiresAt": expires_at,
            }
        )
        # merge=True: only the activity fields move, the rest of the
        # conversation document is left untouched.
        await self._conversation_doc(conversation_id).set(
            {"lastActivityAt": message.createdAt, "expiresAt": expires_at},
            merge=True,
        )
        # Never log message.text (spec §15.2) -- ids/roles only.
        logger.info(
            "Saved conversation message: conversation_id=%s role=%s",
            conversation_id,
            message.role,
        )

    async def get_recent_messages(
        self, conversation_id: str, limit: int
    ) -> list[ConversationMessage]:
        return await self._read_messages(conversation_id, limit)


def _is_timed_out(context: ConversationContext, timeout_hours: int, now: datetime) -> bool:
    return now - context.lastActivityAt > timedelta(hours=timeout_hours)


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


@dataclass
class _Round:
    """One user turn plus any assistant messages that immediately follow it."""

    messages: list[ConversationMessage]


def _group_into_rounds(messages: list[ConversationMessage]) -> list[_Round]:
    """Group chronologically-ordered messages into rounds (see module doc).

    A round starts at each "user" message and absorbs every following
    message up to (but not including) the next "user" message. Any
    messages preceding the first "user" message (not expected in normal
    operation) form their own leading round so no message is ever dropped
    by grouping.
    """
    rounds: list[_Round] = []
    for message in messages:
        if message.role == "user" or not rounds:
            rounds.append(_Round(messages=[message]))
        else:
            rounds[-1].messages.append(message)
    return rounds


def _trim_to_rounds(
    messages: list[ConversationMessage], max_rounds: int
) -> list[ConversationMessage]:
    """Keep only the most recent ``max_rounds`` rounds, flattened back out."""
    if max_rounds <= 0:
        return []
    rounds = _group_into_rounds(messages)
    kept = rounds[-max_rounds:]
    return [message for round_ in kept for message in round_.messages]


class ConversationService:
    """Owns Conversation POLICY (spec §10.2) so the workflow stays thin.

    - Creates a new conversation when none exists, or the previous one
      exceeded ``settings.conversation_timeout_hours`` (§10.2).
    - Trims history to at most ``settings.max_history_messages`` AND at
      most ``settings.conversation_history_rounds`` round-trips, applying
      both bounds and keeping the most recent messages (see
      ``_trim_to_rounds`` for exactly how a "round" is counted).
    """

    def __init__(
        self,
        repository: ConversationRepository,
        settings: RagSettings,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._clock = clock

    async def load_or_create(
        self,
        *,
        tenant_id: str | None,
        teams_conversation_id: str,
        teams_user_id: str,
    ) -> ConversationContext:
        existing = await self._repository.find_conversation(
            tenant_id=tenant_id,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
            timeout_hours=self._settings.conversation_timeout_hours,
        )
        if existing is not None:
            return existing
        return await self._repository.create_conversation(
            tenant_id=tenant_id,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
        )

    async def record_message(
        self,
        conversation_id: str,
        *,
        role: str,
        text: str,
        correlation_id: str | None = None,
        follow_up_state: str = "NONE",
        pending_issues: list[PendingIssueContext] | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            role=role,  # type: ignore[arg-type]
            text=text,
            createdAt=self._clock(),
            correlationId=correlation_id,
            followUpState=follow_up_state,
            pendingIssues=pending_issues or [],
        )
        await self._repository.save_message(conversation_id, message)
        return message

    async def get_history(self, conversation_id: str) -> list[ConversationMessage]:
        """Return recent history honoring both trimming bounds (spec §10.2)."""
        messages = await self._repository.get_recent_messages(
            conversation_id, self._settings.max_history_messages
        )
        return _trim_to_rounds(messages, self._settings.conversation_history_rounds)
