from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

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
    IdempotencyRecord,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    ReviewRecord,
    utc_now,
)
from ..publisher import ReleasePublisher
from ..repository import PortalRepository, new_id
from ..settings import PortalSettings


class IdempotencyConflictError(Exception):
    def __init__(
        self,
        message: str = "Idempotency key was previously used with a different request payload.",
    ) -> None:
        super().__init__(message)


class IdempotencyStore:
    """Bounded in-memory cache for deduplicating mutating API requests with atomic concurrency coordination."""

    def __init__(self, max_records: int = 1000) -> None:
        self._cache: dict[str, tuple[str, str, Any]] = {}
        self._keys: list[str] = []
        self._pending: dict[str, asyncio.Event] = {}
        self._pending_hashes: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._max_records = max_records

    def check_and_get(self, key: str, payload_hash: str) -> Any | None:
        if key in self._cache:
            stored_hash, status, response = self._cache[key]
            if stored_hash and stored_hash != payload_hash:
                raise IdempotencyConflictError(
                    "Idempotency key was previously used with a different request payload."
                )
            if status == "COMPLETED":
                return response
        return None

    def get(self, key: str) -> Any | None:
        if key in self._cache:
            return self._cache[key][2]
        return None

    def set(self, key: str, value: Any, payload_hash: str = "", status: str = "COMPLETED") -> None:
        if key in self._cache:
            self._cache[key] = (payload_hash, status, value)
            return
        if len(self._keys) >= self._max_records:
            oldest = self._keys.pop(0)
            self._cache.pop(oldest, None)
        self._keys.append(key)
        self._cache[key] = (payload_hash, status, value)

    async def claim_or_wait(
        self,
        key: str,
        payload_hash: str,
        timeout: float = 15.0,
    ) -> tuple[Literal["NEW", "CACHED"], Any | None]:
        async with self._lock:
            if key in self._cache:
                stored_hash, status, response = self._cache[key]
                if stored_hash and stored_hash != payload_hash:
                    raise IdempotencyConflictError(
                        "Idempotency key was previously used with a different request payload."
                    )
                if status == "COMPLETED":
                    return "CACHED", response

            if key in self._pending:
                pending_hash = self._pending_hashes.get(key, "")
                if pending_hash and pending_hash != payload_hash:
                    raise IdempotencyConflictError(
                        "Idempotency key was previously used with a different request payload."
                    )
                event = self._pending[key]
                wait_needed = True
            else:
                event = asyncio.Event()
                self._pending[key] = event
                self._pending_hashes[key] = payload_hash
                wait_needed = False

        if wait_needed:
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            async with self._lock:
                if key in self._cache:
                    stored_hash, status, response = self._cache[key]
                    if stored_hash and stored_hash != payload_hash:
                        raise IdempotencyConflictError(
                            "Idempotency key was previously used with a different request payload."
                        )
                    if status == "COMPLETED":
                        return "CACHED", response

        return "NEW", None

    async def complete(self, key: str, payload_hash: str, response: Any) -> None:
        async with self._lock:
            self.set(key, response, payload_hash=payload_hash, status="COMPLETED")
            event = self._pending.pop(key, None)
            self._pending_hashes.pop(key, None)
            if event:
                event.set()

    async def fail(self, key: str) -> None:
        async with self._lock:
            self._cache.pop(key, None)
            event = self._pending.pop(key, None)
            self._pending_hashes.pop(key, None)
            if event:
                event.set()


class PortalServiceContext:
    def __init__(self, settings: PortalSettings, repository: PortalRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.publisher = ReleasePublisher(settings)
        self.migration = KnowledgeMigrationService(settings, repository, self.publisher)
        self.idempotency = IdempotencyStore()

    async def claim_idempotency(
        self, key: str, payload_hash: str
    ) -> tuple[Literal["NEW", "CACHED"], Any | None]:
        status, response = await self.idempotency.claim_or_wait(key, payload_hash)
        if status == "CACHED":
            return status, response

        repo_rec = await self.repository.get_idempotency(key)
        if repo_rec is not None:
            if repo_rec.payload_hash and repo_rec.payload_hash != payload_hash:
                await self.idempotency.fail(key)
                raise IdempotencyConflictError(
                    "Idempotency key was previously used with a different request payload."
                )
            if repo_rec.status == "COMPLETED":
                await self.idempotency.complete(key, payload_hash, repo_rec.response)
                return "CACHED", repo_rec.response
            if repo_rec.status == "PROCESSING":
                for _ in range(30):
                    await asyncio.sleep(0.5)
                    poll = await self.repository.get_idempotency(key)
                    if poll and poll.status == "COMPLETED":
                        await self.idempotency.complete(key, payload_hash, poll.response)
                        return "CACHED", poll.response

        now = utc_now()
        rec = IdempotencyRecord(
            key=key,
            payload_hash=payload_hash,
            status="PROCESSING",
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_idempotency(rec)
        return "NEW", None

    async def complete_idempotency(self, key: str, payload_hash: str, response: Any) -> None:
        await self.idempotency.complete(key, payload_hash, response)
        now = utc_now()
        serialized_response = (
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else response
        )
        rec = IdempotencyRecord(
            key=key,
            payload_hash=payload_hash,
            response=serialized_response,
            status="COMPLETED",
            created_at=now,
            updated_at=now,
        )
        await self.repository.save_idempotency(rec)

    async def fail_idempotency(self, key: str) -> None:
        await self.idempotency.fail(key)

    async def get_idempotency(self, key: str, payload_hash: str) -> Any | None:
        status, response = await self.claim_idempotency(key, payload_hash)
        if status == "CACHED":
            return response
        return None

    async def save_idempotency(self, key: str, payload_hash: str, response: Any) -> None:
        await self.complete_idempotency(key, payload_hash, response)

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
