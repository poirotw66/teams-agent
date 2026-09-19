"""Domain query mixin: KnowledgeQueryMixin."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from operations_core.access import ActorContext
from operations_core.contracts import OperationalEvent

from ..knowledge_bridge.delegation import DELEGATION_HEADER, issue_delegation_envelope
from .query_knowledge_docs_ops import (
    build_document_inventory_item,
    build_document_performance_payload,
    filter_documents_by_format,
    paginate_documents,
)
from .query_knowledge_portal_ops import (
    fetch_active_release_document_ids,
    fetch_document_governance,
    fetch_document_inventory,
)
from .query_knowledge_status import (
    _derive_index_status,
    _normalize_format_type,
    normalize_format_type,
)

__all__ = [
    "KnowledgeQueryMixin",
    "KnowledgeQueryService",
    "_derive_index_status",
    "_normalize_format_type",
]


class KnowledgeQueryMixin:
    async def _portal_identity_token(self, audience: str) -> str:
        now = asyncio.get_running_loop().time()
        cached = self._knowledge_identity_token
        if cached is not None and cached[0] > now:
            return cached[1]
        async with self._knowledge_identity_token_lock:
            cached = self._knowledge_identity_token
            if cached is not None and cached[0] > now:
                return cached[1]
            from ..knowledge_bridge.client import _fetch_google_id_token

            token = await asyncio.to_thread(_fetch_google_id_token, audience)
            self._knowledge_identity_token = (now + 3000, token)
            return token

    async def _portal_headers(self, portal_url: str) -> dict[str, str]:
        headers = {
            "X-Portal-User-Id": "ai-ops-backoffice",
            "X-Portal-User-Name": "AI%20Ops%20Backoffice",
            "X-Portal-Role": "PLATFORM",
            "X-Portal-Owner-Units": self._settings.default_owner_unit_id,
        }
        if self._settings.knowledge_delegation_secret:
            service_actor = ActorContext(
                user_id="ai-ops-backoffice",
                display_name="AI Ops Backoffice",
                role="SYSTEM_ADMIN",
                owner_unit_ids=(self._settings.default_owner_unit_id,),
                tenant_id=self._settings.deployment_tenant_id,
            )
            headers[DELEGATION_HEADER] = issue_delegation_envelope(
                service_actor,
                secret=self._settings.knowledge_delegation_secret,
                correlation_id=uuid.uuid4().hex,
            )
        if self._settings.knowledge_auth_mode == "GOOGLE_ID_TOKEN":
            token = await self._portal_identity_token(portal_url)
            headers["Authorization"] = f"Bearer {token}"
        elif self._settings.knowledge_service_token:
            headers["Authorization"] = (
                f"Bearer {self._settings.knowledge_service_token}"
            )
        return headers

    def _portal_base_url(self) -> str:
        return (
            self._settings.knowledge_internal_url or self._settings.knowledge_portal_url
        ).rstrip("/")

    async def document_performance(
        self,
        actor: ActorContext,
        document_id: str,
        *,
        preset: str | None = None,
        days: int = 30,
        start_date: str | None = None,
        end_date: str | None = None,
        issue_type_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        period = self._resolve_period(
            preset=preset,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        events = await self._scoped_events(actor, period, force_refresh=force_refresh)
        governance = await self._fetch_document_governance(
            document_id,
            indexed_document_ids=await self._fetch_active_release_document_ids(),
        )
        return build_document_performance_payload(
            document_id=document_id,
            period=period,
            events=events,
            taxonomy=self.taxonomy,
            issue_type_id=issue_type_id,
            limit=limit,
            cursor=cursor,
            governance=governance,
        )

    async def list_documents(
        self,
        actor: ActorContext,
        *,
        status: str | None = None,
        owner_unit_id: str | None = None,
        query: str | None = None,
        format_type: str | None = None,
        preset: str | None = None,
        days: int = 30,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        period = self._resolve_period(preset=preset, days=days)
        events = await self._scoped_events(actor, period)
        inventory = await self._fetch_document_inventory(
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )
        documents = [
            document
            for document in inventory["items"]
            if actor.allows_owner_unit(document.get("owner_unit_id"))
        ]
        indexed_document_ids = await self._fetch_active_release_document_ids()
        format_needle = normalize_format_type(format_type) if format_type else None
        documents, governance_by_id = await filter_documents_by_format(
            documents,
            format_needle=format_needle,
            fetch_governance=self._fetch_document_governance,
            indexed_document_ids=indexed_document_ids,
        )
        total = len(documents)
        _remaining, page, next_cursor = paginate_documents(
            documents,
            cursor=cursor,
            limit=limit,
        )
        if governance_by_id is None:
            governance = await asyncio.gather(
                *(
                    self._fetch_document_governance(
                        str(document["document_id"]),
                        indexed_document_ids=indexed_document_ids,
                    )
                    for document in page
                )
            )
        else:
            governance = [governance_by_id[str(document["document_id"])] for document in page]
        items = [
            self._document_inventory_item(document, governance_item, events)
            for document, governance_item in zip(page, governance, strict=True)
        ]
        return {
            "items": items,
            "total": total,
            "nextCursor": next_cursor,
            "periodDays": period.days,
            "periodPreset": period.preset,
            "portalStatus": inventory["status"],
            "warning": inventory.get("warning"),
            "filterFormatType": format_needle,
        }

    def _document_inventory_item(
        self,
        document: dict[str, Any],
        governance: dict[str, Any],
        events: list[OperationalEvent],
    ) -> dict[str, Any]:
        return build_document_inventory_item(document, governance, events)

    async def _fetch_document_inventory(
        self,
        *,
        status: str | None,
        owner_unit_id: str | None,
        query: str | None,
    ) -> dict[str, Any]:
        portal_url = self._portal_base_url()
        headers = await self._portal_headers(portal_url)
        return await fetch_document_inventory(
            portal_url=portal_url,
            headers=headers,
            status=status,
            owner_unit_id=owner_unit_id,
            query=query,
        )

    async def _fetch_active_release_document_ids(self) -> set[str] | None:
        portal_url = self._portal_base_url()
        headers = await self._portal_headers(portal_url)
        return await fetch_active_release_document_ids(
            portal_url=portal_url,
            headers=headers,
        )

    async def _fetch_document_governance(
        self,
        document_id: str,
        *,
        indexed_document_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        portal_url = self._portal_base_url()
        headers = await self._portal_headers(portal_url)
        return await fetch_document_governance(
            portal_url=portal_url,
            headers=headers,
            document_id=document_id,
            indexed_document_ids=indexed_document_ids,
        )


KnowledgeQueryService = KnowledgeQueryMixin

