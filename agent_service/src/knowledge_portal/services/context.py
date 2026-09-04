from __future__ import annotations

from pathlib import Path
from typing import Any

from ..capabilities import (
    compute_allowed_actions,
    compute_next_action,
    document_status_label,
)
from ..draft_assets import DraftAssetStore, slug_from_title
from ..migration import KnowledgeMigrationService
from ..models import (
    AuditEventRecord,
    DocumentDetailResponse,
    DraftAssetListResponse,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    ReviewRecord,
    utc_now,
)
from ..publisher import ReleasePublisher
from ..repository import PortalRepository, new_id
from ..settings import PortalSettings


class IdempotencyStore:
    """Bounded in-memory cache for deduplicating mutating API requests."""

    def __init__(self, max_records: int = 1000) -> None:
        self._cache: dict[str, Any] = {}
        self._keys: list[str] = []
        self._max_records = max_records

    def get(self, key: str) -> Any | None:
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        if key in self._cache:
            self._cache[key] = value
            return
        if len(self._keys) >= self._max_records:
            oldest = self._keys.pop(0)
            self._cache.pop(oldest, None)
        self._keys.append(key)
        self._cache[key] = value


class PortalServiceContext:
    def __init__(self, settings: PortalSettings, repository: PortalRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.publisher = ReleasePublisher(settings)
        self.migration = KnowledgeMigrationService(settings, repository, self.publisher)
        self.idempotency = IdempotencyStore()

    async def audit(
        self,
        *,
        actor: PortalActor,
        action: str,
        target_type: str,
        target_id: str,
        correlation_id: str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        result: str = "SUCCESS",
    ) -> None:
        await self.repository.append_audit(
            AuditEventRecord(
                event_id=new_id("audit"),
                actor_id=actor.user_id,
                actor_role=actor.role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                correlation_id=correlation_id,
                reason=reason,
                result=result,
                occurred_at=utc_now(),
                metadata=metadata or {},
            )
        )

    def document_detail_response(
        self,
        *,
        document: KnowledgeDocumentRecord,
        draft_version: KnowledgeVersionRecord | None,
        published_version: KnowledgeVersionRecord | None,
        open_review: ReviewRecord | None,
        draft_assets: DraftAssetListResponse | None,
        actor: PortalActor,
    ) -> DocumentDetailResponse:
        allowed_actions = compute_allowed_actions(
            actor=actor,
            document=document,
            draft_version=draft_version,
            open_review=open_review,
            settings=self.settings,
        )
        next_action = compute_next_action(
            allowed_actions,
            document_status=document.status,
        )
        return DocumentDetailResponse(
            document=document,
            draft_version=draft_version,
            published_version=published_version,
            open_review=open_review,
            draft_assets=draft_assets,
            allowed_actions=allowed_actions,
            next_action=next_action,
            status_label=document_status_label(document.status),
        )

    def validation_context(
        self,
        *,
        document_id: str,
        version_id: str,
        title: str,
        asset_slug: str,
    ) -> tuple[str, Path]:
        slug = asset_slug or slug_from_title(title)
        store = DraftAssetStore(self.settings)
        return slug, store.assets_root(document_id, version_id)
