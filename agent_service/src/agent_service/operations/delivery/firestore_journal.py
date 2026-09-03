from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from ..contracts import OperationalEvent
from .journal import Lease, claim_record, register, settle_record, summarize


async def mutate_document(client: Any, document: Any, operation: Callable) -> Any:
    from google.cloud.firestore_v1.async_transaction import async_transactional

    @async_transactional
    async def apply(transaction: Any) -> Any:
        snapshot = await document.get(transaction=transaction)
        record, result = operation(snapshot.to_dict() if snapshot.exists else None)
        if record is not None:
            # Refuse oversize records before either the event or its delivery
            # manifest can be accepted. Keep below Firestore's document limit.
            if len(json.dumps(record, default=str).encode()) > 900_000:
                raise ValueError("delivery_record_too_large")
            transaction.set(document, record)
        return result

    return await apply(client.transaction())


class FirestoreJournal:
    """One transactional document contains the immutable event AND all receipts."""

    durable = True

    def __init__(self, client: Any, collection: str) -> None:
        self._client = client
        self._collection = client.collection(collection)

    def _document(self, event_id: str) -> Any:
        return self._collection.document(hashlib.sha256(event_id.encode()).hexdigest())

    async def put(self, event: OperationalEvent, sinks: list[str], now: float) -> bool:
        return await mutate_document(self._client, self._document(event.event_id),
                                     lambda old: register(old, event, sinks, now))

    async def claim(
        self, targets: set[str], now: float, lease_seconds: float, limit: int,
        event_id: str | None = None,
    ) -> list[Lease]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        if event_id is not None:
            documents = [self._document(event_id)]
        else:
            query = self._collection.where(filter=FieldFilter("wake_at", "<=", now))
            documents = [snap.reference async for snap in query.order_by("wake_at").stream()]
        leases: list[Lease] = []
        for document in documents:
            def operation(old: dict[str, Any] | None) -> tuple[Any, list[Lease]]:
                if old is None:
                    return None, []
                claimed = claim_record(old, targets, now, lease_seconds, limit - len(leases))
                return old if claimed else None, claimed
            leases.extend(await mutate_document(self._client, document, operation))
            if len(leases) >= limit:
                break
        return leases

    async def settle(
        self, lease: Lease, now: float, error: str | None = None, delay: float = 0,
    ) -> bool:
        def operation(old: dict[str, Any] | None) -> tuple[Any, bool]:
            if old is None:
                return None, False
            changed = settle_record(old, lease, now, error, delay)
            return old if changed else None, changed
        return await mutate_document(self._client, self._document(lease.event.event_id), operation)

    async def stats(self, now: float) -> dict[str, Any]:
        return summarize([snap.to_dict() async for snap in self._collection.stream()], now)
