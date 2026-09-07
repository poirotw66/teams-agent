"""Firestore-backed conversation repository."""
from __future__ import annotations

import hashlib
import itertools
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..contracts import ConversationContext, ConversationMessage, PendingIssueContext
from .helpers import (
    Clock,
    ConversationRepository,
    _conversation_key,
    _is_timed_out,
    _utc_now,
)

logger = logging.getLogger(__name__)

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
                requestId=data.get("requestId"),
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
        timeout_hours: int = 24,
    ) -> ConversationContext:
        key = _conversation_key(
            tenant_id=tenant_id,
            teams_conversation_id=teams_conversation_id,
            teams_user_id=teams_user_id,
        )
        now = self._clock()
        key_ref = self._client.collection(self._keys_collection).document(
            self._key_document_id(key)
        )
        transaction = self._client.transaction()

        async def operation(transaction):
            key_snapshot = await key_ref.get(transaction=transaction)
            if key_snapshot.exists:
                existing_id = (key_snapshot.to_dict() or {}).get("conversationId")
                if existing_id:
                    conversation_snapshot = await self._conversation_doc(existing_id).get(
                        transaction=transaction
                    )
                    if conversation_snapshot.exists:
                        data = conversation_snapshot.to_dict() or {}
                        started_at = self._to_datetime(data.get("startedAt"))
                        last_activity_at = self._to_datetime(data.get("lastActivityAt"))
                        if started_at and last_activity_at:
                            existing = ConversationContext(
                                conversationId=existing_id,
                                startedAt=started_at,
                                lastActivityAt=last_activity_at,
                                messages=[],
                            )
                            if not _is_timed_out(existing, timeout_hours, self._clock()):
                                return existing

            context = ConversationContext(
                conversationId=str(uuid.uuid4()),
                startedAt=now,
                lastActivityAt=now,
                messages=[],
            )
            transaction.set(
                self._conversation_doc(context.conversationId),
                {
                    "conversationKey": key,
                    "tenantId": tenant_id,
                    "startedAt": now,
                    "lastActivityAt": now,
                    "expiresAt": self._expires_at(now),
                },
            )
            transaction.set(
                key_ref,
                {
                    "conversationKey": key,
                    "conversationId": context.conversationId,
                    "updatedAt": now,
                    "expiresAt": self._expires_at(now),
                },
            )
            return context

        context = await self._run_transaction(transaction, operation)
        logger.info(
            "Created conversation: conversation_id=%s tenant_id=%s",
            context.conversationId,
            tenant_id or "-",
        )
        return context

    @staticmethod
    async def _run_transaction(transaction: Any, operation: Any):
        if hasattr(transaction, "commit") and not hasattr(transaction, "_read_only"):
            result = await operation(transaction)
            transaction.commit()
            return result
        try:
            from google.cloud.firestore_v1.async_transaction import async_transactional
        except ImportError as error:  # pragma: no cover - guarded by optional extra
            raise RuntimeError(
                "CONVERSATION_REPOSITORY_MODE=FIRESTORE requires the firestore extra"
            ) from error
        return await async_transactional(operation)(transaction)

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
                "requestId": message.requestId,
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


