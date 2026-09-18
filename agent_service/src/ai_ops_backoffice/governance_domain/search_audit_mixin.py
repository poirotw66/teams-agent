from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from operations_core.access import ActorContext

from .constants import (
    READ,
)
from .models import (
    GovernanceState,
    replace_model,
)
from .search_hits import collect_search_hits

Clock = Callable[[], datetime]


class GovernanceSearchAuditMixin:
    def search(
        self,
        *,
        query: str,
        actor: ActorContext,
        doc_type: str | None = None,
        owner_unit_id: str | None = None,
        status: str | None = None,
        extra_documents: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._require(actor, READ["search"])
        state = self._ensured()
        hits = collect_search_hits(
            state,
            actor=actor,
            query=query,
            doc_type=doc_type,
            owner_unit_id=owner_unit_id,
            status=status,
            extra_documents=extra_documents,
        )

        def operation(current: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            audit = self._audit(
                action="GOVERNANCE_SEARCH",
                actor=actor,
                target_type="SEARCH",
                target_id=doc_type or "ALL",
                after={"queryLength": len(query), "resultCount": len(hits)},
            )
            return replace_model(current, audits=(*current.audits, audit)), {
                "items": hits,
                "hits": hits,
                "count": len(hits),
            }

        return self._mutate(operation)

    def query_audit(
        self,
        *,
        actor: ActorContext,
        target_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        self._require(actor, READ["audit"])
        events = list(self._ensured().audits)
        if target_type:
            needle_target = target_type.strip().casefold()
            events = [item for item in events if needle_target in item.target_type.casefold()]
        if actor_id:
            needle_actor = actor_id.strip().casefold()
            events = [item for item in events if needle_actor in item.actor_id.casefold()]
        if action:
            needle_action = action.strip().casefold()
            events = [item for item in events if needle_action in item.action.casefold()]
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=UTC)
                events = [item for item in events if item.occurred_at >= start_dt]
            except Exception:
                pass
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=UTC)
                events = [item for item in events if item.occurred_at <= end_dt]
            except Exception:
                pass

        sorted_events = sorted(events, key=lambda e: e.occurred_at, reverse=True)
        start = int(cursor or "0")
        page = sorted_events[start : start + limit]
        next_index = start + len(page)
        next_cursor = str(next_index) if next_index < len(sorted_events) else None
        return {
            "items": [item.model_dump(mode="json") for item in page],
            "nextCursor": next_cursor,
            "hasMore": next_cursor is not None,
            "total": len(sorted_events),
        }

    def export_audit(
        self,
        *,
        actor: ActorContext,
        target_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        self._require(actor, READ["audit"])
        items = self.list_audit(
            actor=actor,
            target_type=target_type,
            actor_id=actor_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
        )
        package = {
            "exportedAt": self._clock().isoformat(),
            "count": len(items),
            "targetType": target_type,
            "format": "json",
            "items": items,
        }

        def operation(state: GovernanceState) -> tuple[GovernanceState, dict[str, Any]]:
            audit = self._audit(
                action="GOVERNANCE_AUDIT_EXPORTED",
                actor=actor,
                target_type="AUDIT",
                target_id=target_type or "ALL",
                after={"count": len(items)},
            )
            return replace_model(state, audits=(*state.audits, audit)), package

        return self._mutate(operation)

    def list_audit(
        self,
        *,
        actor: ActorContext,
        target_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require(actor, READ["audit"])
        res = self.query_audit(
            actor=actor,
            target_type=target_type,
            actor_id=actor_id,
            action=action,
            start_date=start_date,
            end_date=end_date,
            limit=limit or 10000,
            cursor=cursor,
        )
        return res["items"]
