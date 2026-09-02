from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

from ..contracts import OperationalEvent

logger = logging.getLogger(__name__)


class OperationalStore(Protocol):
    async def append(self, event: OperationalEvent) -> bool: ...

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]: ...


class CompositeOperationalStore:
    def __init__(
        self,
        primary: OperationalStore,
        sinks: list[object] | None = None,
    ) -> None:
        self._primary = primary
        self._sinks = sinks or []

    async def append(self, event: OperationalEvent) -> bool:
        inserted = await self._primary.append(event)
        if inserted:
            for sink in self._sinks:
                append = getattr(sink, "append", None)
                if append is None:
                    continue
                try:
                    result = append(event)
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:  # noqa: BLE001 - sinks are best-effort
                    logger.warning("Operational event sink failed: %s", exc)
                    continue
        return inserted

    async def list_events(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[OperationalEvent], str | None]:
        return await self._primary.list_events(
            limit=limit,
            cursor=cursor,
            since=since,
            until=until,
        )
