from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..contracts import OperationalEvent

logger = logging.getLogger(__name__)


def _firestore_document(event: OperationalEvent) -> dict[str, Any]:
    payload = event.model_dump()
    for key in ("occurred_at", "ingested_at", "retention_expires_at"):
        value = payload.get(key)
        if isinstance(value, str):
            payload[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return payload


class FirestoreOperationalStore:
    """Append-only operational event store backed by Firestore."""

    def __init__(self, client: Any, collection: str) -> None:
        self._collection = client.collection(collection)

    async def append(self, event: OperationalEvent) -> bool:
        document = self._collection.document(event.event_id)
        snapshot = await document.get()
        if snapshot.exists:
            return False
        await document.set(_firestore_document(event))
        return True

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]:
        query = self._collection.order_by("occurred_at")
        if since is not None:
            query = query.where("occurred_at", ">=", since)
        if until is not None:
            query = query.where("occurred_at", "<=", until)
        if cursor:
            cursor_doc = await self._collection.document(cursor).get()
            if cursor_doc.exists:
                query = query.start_after(cursor_doc)
        snapshots = [item async for item in query.limit(limit + 1).stream()]
        events = [OperationalEvent.model_validate(item.to_dict()) for item in snapshots[:limit]]
        next_cursor = snapshots[limit].id if len(snapshots) > limit else None
        return events, next_cursor


def build_firestore_client(project: str | None, database: str | None) -> Any:
    try:
        from google.cloud.firestore import AsyncClient
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "OPS_STORE_MODE=FIRESTORE requires google-cloud-firestore."
        ) from exc
    kwargs: dict[str, str] = {}
    if project:
        kwargs["project"] = project
    if database:
        kwargs["database"] = database
    return AsyncClient(**kwargs)
