"""Release command facade: locks, wiring, and thin delegation.

Publish / rollback / promote / sync / query bodies live under
``knowledge_portal.release``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from knowledge_portal.models import (
    DocumentDetailResponse,
    KnowledgeVersionRecord,
    PortalActor,
    PublishRequest,
    ReleaseCompareResponse,
    ReleaseRecord,
    RemoveDocumentRequest,
    RollbackRequest,
    utc_now,
)
from knowledge_portal.repository import new_id

from .. import release as release_workflow
from .context import PortalServiceContext
from .document_service import DocumentService


class ReleaseService:
    def __init__(self, ctx: PortalServiceContext, documents: DocumentService) -> None:
        self._ctx = ctx
        self._documents = documents
        self._publish_lock = asyncio.Lock()

    @asynccontextmanager
    async def _coordination_lock(self, action_name: str, timeout: float = 30.0):
        lease_owner = f"{action_name}::{new_id('worker')}"
        async with self._publish_lock:
            start = asyncio.get_event_loop().time()
            acquired = False
            while not acquired:
                acquired = await self._ctx.repository.acquire_publish_lease(
                    lease_owner, ttl_seconds=timeout
                )
                if acquired:
                    break
                if asyncio.get_event_loop().time() - start > timeout:
                    raise TimeoutError(
                        f"Could not acquire publish coordination lease for {action_name}"
                    )
                await asyncio.sleep(0.05)
            try:
                yield
            finally:
                await self._ctx.repository.release_publish_lease(lease_owner)

    async def publish_version(
        self,
        actor: PortalActor,
        document_id: str,
        request: PublishRequest,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> ReleaseRecord:
        return await release_workflow.publish_version(
            ctx=self._ctx,
            documents=self._documents,
            actor=actor,
            document_id=document_id,
            request=request,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            coordination_lock=self._coordination_lock,
            activate_release=self._activate_release,
        )

    async def unpublish_document(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        return await release_workflow.unpublish_document(
            ctx=self._ctx,
            documents=self._documents,
            actor=actor,
            document_id=document_id,
            request=request,
            correlation_id=correlation_id,
            coordination_lock=self._coordination_lock,
            activate_release=self._activate_release,
        )

    async def remove_document(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse | dict[str, str]:
        return await release_workflow.remove_document(
            documents=self._documents,
            unpublish=self.unpublish_document,
            actor=actor,
            document_id=document_id,
            request=request,
            correlation_id=correlation_id,
        )

    async def rollback_release(
        self,
        actor: PortalActor,
        request: RollbackRequest,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> ReleaseRecord:
        return await release_workflow.rollback_release(
            ctx=self._ctx,
            actor=actor,
            request=request,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            coordination_lock=self._coordination_lock,
            require_allowed=self._require_release_allowed,
            notify_reload=self._notify_agent_reload,
            write_local_pointer=self._write_local_active_pointer,
            deactivate_others=self._deactivate_other_releases,
        )

    async def sync_agent_release(
        self,
        actor: PortalActor,
        release_id: str,
        correlation_id: str,
    ) -> ReleaseRecord:
        return await release_workflow.sync_agent_release(
            ctx=self._ctx,
            actor=actor,
            release_id=release_id,
            correlation_id=correlation_id,
            coordination_lock=self._coordination_lock,
            require_allowed=self._require_release_allowed,
            notify_reload=self._notify_agent_reload,
            write_local_pointer=self._write_local_active_pointer,
            deactivate_others=self._deactivate_other_releases,
        )

    async def _notify_agent_reload(
        self,
        release_id: str,
        correlation_id: str,
    ) -> tuple[bool, str | None]:
        return await release_workflow.notify_agent_reload(
            agent_api_url=self._ctx.settings.agent_api_url,
            agent_api_auth_mode=self._ctx.settings.agent_api_auth_mode,
            agent_api_token=self._ctx.settings.agent_api_token,
            release_id=release_id,
            correlation_id=correlation_id,
        )

    async def list_releases(self, actor: PortalActor) -> list[ReleaseRecord]:
        return await release_workflow.list_releases(ctx=self._ctx, actor=actor)

    async def compare_releases(
        self,
        actor: PortalActor,
        *,
        target_release_id: str,
    ) -> ReleaseCompareResponse:
        return await release_workflow.compare_releases(
            ctx=self._ctx,
            actor=actor,
            target_release_id=target_release_id,
        )

    async def _collect_active_published_versions(
        self,
        actor: PortalActor,
        *,
        exclude_document_ids: set[str] | None = None,
    ) -> list[KnowledgeVersionRecord]:
        return await release_workflow.collect_active_published_versions(
            repository=self._ctx.repository,
            actor=actor,
            exclude_document_ids=exclude_document_ids,
        )

    async def _activate_release(
        self,
        *,
        actor: PortalActor,
        published_versions: list[KnowledgeVersionRecord],
        correlation_id: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
        embedding_model: str | None = None,
    ) -> ReleaseRecord:
        return await release_workflow.activate_release(
            store=self._ctx.repository,
            publisher=self._ctx.publisher,
            actor=actor,
            published_versions=published_versions,
            correlation_id=correlation_id,
            reason=reason,
            release_id=new_id("release"),
            metadata=metadata,
            embedding_model=embedding_model,
            release_gate_checker=getattr(self._ctx, "release_gate_checker", None),
            source_catalog_writer=getattr(self._ctx, "source_catalog_writer", None),
            portal_settings=self._ctx.settings,
            audit=self._ctx.audit,
            require_allowed=self._require_release_allowed,
            notify_reload=self._notify_agent_reload,
            write_local_pointer=self._write_local_active_pointer,
            utc_now=utc_now,
        )

    async def promote_candidate_release(
        self,
        actor: PortalActor,
        release_id: str,
        *,
        correlation_id: str | None = None,
        reason: str = "Promote evaluated candidate release after gate pass",
    ) -> ReleaseRecord:
        return await release_workflow.promote_candidate_release(
            ctx=self._ctx,
            actor=actor,
            release_id=release_id,
            correlation_id=correlation_id,
            reason=reason,
            coordination_lock=self._coordination_lock,
            require_allowed=self._require_release_allowed,
            notify_reload=self._notify_agent_reload,
            write_local_pointer=self._write_local_active_pointer,
            deactivate_others=self._deactivate_other_releases,
        )

    async def _deactivate_other_releases(self, active_release_id: str) -> None:
        await release_workflow.deactivate_other_releases(
            self._ctx.repository,
            active_release_id,
        )

    def _require_release_allowed(
        self,
        release: ReleaseRecord,
        *,
        require_verified: bool = False,
    ) -> None:
        release_workflow.require_release_allowed(
            release,
            deployment_environment=self._ctx.settings.deployment_environment,
            release_gcs_bucket=self._ctx.settings.release_gcs_bucket,
            require_verified=require_verified,
        )

    def _write_local_active_pointer(self, release_id: str) -> None:
        release_workflow.write_local_active_pointer(
            release_artifact_dir=self._ctx.settings.release_artifact_dir,
            release_gcs_bucket=self._ctx.settings.release_gcs_bucket,
            release_id=release_id,
        )

    async def reindex_all_published(
        self,
        actor: PortalActor,
        *,
        scope_type: str = "ALL",
        scope_ids: list[str] | None = None,
        correlation_id: str | None = None,
        reason: str = "Manual knowledge reindex and synchronization",
        embedding_model: str | None = None,
    ) -> ReleaseRecord:
        return await release_workflow.reindex_all_published(
            repository=self._ctx.repository,
            actor=actor,
            scope_type=scope_type,
            scope_ids=scope_ids,
            correlation_id=correlation_id,
            reason=reason,
            embedding_model=embedding_model,
            coordination_lock=self._coordination_lock,
            activate_release=self._activate_release,
        )
