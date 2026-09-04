from __future__ import annotations

import logging
from typing import Any

import httpx

from agent_service.knowledge_release import write_active_release_pointer

logger = logging.getLogger(__name__)


from ..models import (
    DocumentDetailResponse,
    KnowledgeVersionRecord,
    PortalActor,
    PublishRequest,
    ReleaseCompareResponse,
    ReleaseDocumentChange,
    ReleaseRecord,
    RemoveDocumentRequest,
    RollbackRequest,
    utc_now,
)
from ..publisher import ReleaseBuildError
from ..rbac import ensure_can_publish, ensure_not_found
from ..repository import new_id
from ..role_capabilities import ensure_can_list_releases
from .context import PortalServiceContext
from .document_service import DocumentService


class ReleaseService:
    def __init__(self, ctx: PortalServiceContext, documents: DocumentService) -> None:
        self._ctx = ctx
        self._documents = documents

    async def publish_version(
        self,
        actor: PortalActor,
        document_id: str,
        request: PublishRequest,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> ReleaseRecord:
        if idempotency_key:
            scope_key = f"publish::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
            cached = self._ctx.idempotency.get(scope_key)
            if cached is not None:
                return cached

        ensure_can_publish(actor)
        detail = await self._documents.get_document(actor, document_id)
        document = detail.document
        version = await self._ctx.repository.get_version(request.version_id)
        ensure_not_found("version", request.version_id, version)
        if version.document_id != document_id:
            raise ValueError("Version does not belong to this document.")
        if version.status != "APPROVED":
            raise ValueError("Only approved versions can be published.")
        if (
            self._ctx.settings.require_dual_approval
            and actor.user_id == version.created_by
            and actor.role != "PLATFORM"
        ):
            raise ValueError("Contributors cannot publish their own approved content.")

        published_versions = await self._collect_active_published_versions(
            actor,
            exclude_document_ids={document_id},
        )
        published_versions.append(version.model_copy(update={"status": "PUBLISHED"}))

        release = await self._activate_release(
            actor=actor,
            published_versions=published_versions,
            correlation_id=correlation_id,
            reason=request.reason,
            metadata={"documentId": document_id, "versionId": version.version_id},
        )
        if release is None:
            raise ValueError("Publishing failed to produce an active release.")

        updated_version = version.model_copy(update={"status": "PUBLISHED"})
        updated_document = document.model_copy(
            update={
                "status": "PUBLISHED",
                "current_published_version_id": version.version_id,
                "draft_version_id": None,
                "updated_at": utc_now(),
                "updated_by": actor.user_id,
            }
        )
        await self._ctx.repository.save_version(updated_version)
        await self._ctx.repository.save_document(updated_document)
        await self._ctx.audit(
            actor=actor,
            action="document.publish",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            reason=request.reason,
            metadata={"versionId": version.version_id, "releaseId": release.release_id},
        )
        if idempotency_key:
            self._ctx.idempotency.set(scope_key, release)
        return release

    async def unpublish_document(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        detail = await self._documents.get_document(actor, document_id)
        document = detail.document
        if document.status != "PUBLISHED":
            raise ValueError("Only published documents can be unpublished.")
        ensure_can_publish(actor)

        now = utc_now()
        updated_document = document.model_copy(
            update={
                "status": "UNPUBLISHED",
                "current_published_version_id": None,
                "updated_at": now,
                "updated_by": actor.user_id,
            }
        )
        await self._ctx.repository.save_document(updated_document)
        published_versions = await self._collect_active_published_versions(
            actor,
            exclude_document_ids={document_id},
        )
        await self._activate_release(
            actor=actor,
            published_versions=published_versions,
            correlation_id=correlation_id,
            reason=request.reason,
            metadata={"documentId": document_id, "action": "unpublish"},
        )
        await self._ctx.audit(
            actor=actor,
            action="document.unpublish",
            target_type="document",
            target_id=document_id,
            correlation_id=correlation_id,
            reason=request.reason,
        )
        return await self._documents.get_document(actor, document_id)

    async def remove_document(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse | dict[str, str]:
        detail = await self._documents.get_document(actor, document_id)
        document = detail.document
        if document.current_published_version_id and document.status == "PUBLISHED":
            return await self.unpublish_document(
                actor, document_id, request, correlation_id
            )
        return await self._documents.discard_draft(
            actor, document_id, request, correlation_id
        )

    async def rollback_release(
        self,
        actor: PortalActor,
        request: RollbackRequest,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> ReleaseRecord:
        if idempotency_key:
            scope_key = f"rollback::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
            cached = self._ctx.idempotency.get(scope_key)
            if cached is not None:
                return cached

        ensure_can_publish(actor)
        target = await self._ctx.repository.get_release(request.release_id)
        ensure_not_found("release", request.release_id, target)
        previous_active_id = await self._ctx.repository.get_active_release_id()
        previous_release = (
            await self._ctx.repository.get_release(previous_active_id)
            if previous_active_id
            else None
        )
        await self._deactivate_other_releases(target.release_id)
        await self._ctx.repository.set_active_release_id(target.release_id)
        write_active_release_pointer(
            self._ctx.settings.release_artifact_dir,
            target.release_id,
        )
        rolled_back = target.model_copy(
            update={"status": "DEPLOYING", "activated_at": utc_now()}
        )
        await self._ctx.repository.save_release(rolled_back)

        # Synchronize repository document records to match target release manifest
        target_manifest = {entry.document_id: entry.version_id for entry in target.manifest}
        prev_manifest = (
            {entry.document_id: entry.version_id for entry in previous_release.manifest}
            if previous_release
            else {}
        )
        now = utc_now()
        for doc_id in prev_manifest:
            if doc_id not in target_manifest:
                doc = await self._ctx.repository.get_document(doc_id)
                if doc is not None:
                    update_fields: dict[str, Any] = {
                        "current_published_version_id": None,
                        "updated_at": now,
                        "updated_by": actor.user_id,
                    }
                    if doc.status == "PUBLISHED":
                        update_fields["status"] = "UNPUBLISHED"
                    await self._ctx.repository.save_document(
                        doc.model_copy(update=update_fields)
                    )

        for doc_id, version_id in target_manifest.items():
            doc = await self._ctx.repository.get_document(doc_id)
            if doc is not None:
                update_fields = {
                    "current_published_version_id": version_id,
                    "updated_at": now,
                    "updated_by": actor.user_id,
                }
                if doc.status == "UNPUBLISHED":
                    update_fields["status"] = "PUBLISHED"
                await self._ctx.repository.save_document(
                    doc.model_copy(update=update_fields)
                )

        reload_success, reload_error = await self._notify_agent_reload(
            target.release_id, correlation_id
        )
        if reload_success:
            rolled_back = rolled_back.model_copy(
                update={
                    "status": "ACTIVE",
                    "verified_at": utc_now(),
                    "failure_summary": "",
                }
            )
        else:
            rolled_back = rolled_back.model_copy(
                update={
                    "status": "RELOAD_FAILED",
                    "failure_summary": reload_error or "Agent reload failed",
                }
            )
        await self._ctx.repository.save_release(rolled_back)

        await self._ctx.audit(
            actor=actor,
            action="release.rollback",
            target_type="release",
            target_id=target.release_id,
            correlation_id=correlation_id,
            reason=request.reason,
            metadata={
                "previousReleaseId": previous_active_id,
                "reloadStatus": "SUCCESS" if reload_success else "FAILURE",
            },
        )
        if idempotency_key:
            self._ctx.idempotency.set(scope_key, rolled_back)
        return rolled_back

    async def sync_agent_release(
        self,
        actor: PortalActor,
        release_id: str,
        correlation_id: str,
    ) -> ReleaseRecord:
        ensure_can_publish(actor)
        release = await self._ctx.repository.get_release(release_id)
        ensure_not_found("release", release_id, release)

        reload_success, reload_error = await self._notify_agent_reload(
            release_id, correlation_id
        )
        if reload_success:
            updated = release.model_copy(
                update={
                    "status": "ACTIVE",
                    "verified_at": utc_now(),
                    "failure_summary": "",
                }
            )
        else:
            updated = release.model_copy(
                update={
                    "status": "RELOAD_FAILED",
                    "failure_summary": reload_error or "Agent reload failed",
                }
            )
        await self._ctx.repository.save_release(updated)
        await self._ctx.audit(
            actor=actor,
            action="release.sync_agent",
            target_type="release",
            target_id=release_id,
            correlation_id=correlation_id,
            reason=f"Manual agent sync: {'SUCCESS' if reload_success else 'FAILURE'}",
            result="SUCCESS" if reload_success else "FAILURE",
            metadata={"reloadError": reload_error} if reload_error else {},
        )
        return updated

    async def _notify_agent_reload(
        self,
        release_id: str,
        correlation_id: str,
    ) -> tuple[bool, str | None]:
        agent_url = self._ctx.settings.agent_api_url
        if not agent_url:
            return True, None

        target_url = f"{agent_url.rstrip('/')}/admin/reload-knowledge"
        headers = {
            "Content-Type": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        if self._ctx.settings.agent_api_token:
            headers["Authorization"] = f"Bearer {self._ctx.settings.agent_api_token}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    target_url,
                    json={"releaseId": release_id},
                    headers=headers,
                )
                if resp.status_code == 200:
                    logger.info(
                        "Agent reload acknowledged for release %s (correlation_id=%s)",
                        release_id,
                        correlation_id,
                    )
                    return True, None
                err_msg = (
                    f"Agent reload returned HTTP {resp.status_code}: {resp.text[:200]}"
                )
                logger.warning(
                    "Agent reload failed for release %s: %s",
                    release_id,
                    err_msg,
                )
                return False, err_msg
        except Exception as exc:  # noqa: BLE001
            err_msg = f"Agent reload error: {exc}"
            logger.warning(
                "Agent reload request failed for release %s: %s",
                release_id,
                err_msg,
            )
            return False, err_msg


    async def list_releases(self, actor: PortalActor) -> list[ReleaseRecord]:
        ensure_can_list_releases(actor)
        return await self._ctx.repository.list_releases()

    async def compare_releases(
        self,
        actor: PortalActor,
        *,
        target_release_id: str,
    ) -> ReleaseCompareResponse:
        ensure_can_list_releases(actor)
        target = await self._ctx.repository.get_release(target_release_id)
        ensure_not_found("release", target_release_id, target)
        current_id = await self._ctx.repository.get_active_release_id()
        current = await self._ctx.repository.get_release(current_id) if current_id else None

        current_manifest = {
            entry.document_id: entry for entry in (current.manifest if current else [])
        }
        target_manifest = {entry.document_id: entry for entry in target.manifest}

        changes: list[ReleaseDocumentChange] = []
        for doc_id, entry in target_manifest.items():
            current_entry = current_manifest.get(doc_id)
            if current_entry is None:
                changes.append(
                    ReleaseDocumentChange(
                        document_id=doc_id,
                        title=entry.title,
                        change_type="ADDED",
                        target_version_id=entry.version_id,
                    )
                )
            elif current_entry.version_id != entry.version_id:
                changes.append(
                    ReleaseDocumentChange(
                        document_id=doc_id,
                        title=entry.title,
                        change_type="UPDATED",
                        current_version_id=current_entry.version_id,
                        target_version_id=entry.version_id,
                    )
                )
        for doc_id, entry in current_manifest.items():
            if doc_id not in target_manifest:
                changes.append(
                    ReleaseDocumentChange(
                        document_id=doc_id,
                        title=entry.title,
                        change_type="REMOVED",
                        current_version_id=entry.version_id,
                    )
                )

        target_is_older = False
        if current is not None and current.created_at and target.created_at:
            target_is_older = target.created_at < current.created_at

        return ReleaseCompareResponse(
            current_release_id=current_id,
            target_release_id=target_release_id,
            target_is_older=target_is_older,
            document_count_delta=len(target.manifest) - len(current_manifest),
            changes=changes,
        )

    async def _collect_active_published_versions(
        self,
        actor: PortalActor,
        *,
        exclude_document_ids: set[str] | None = None,
    ) -> list[KnowledgeVersionRecord]:
        excluded = exclude_document_ids or set()
        published_versions: list[KnowledgeVersionRecord] = []

        active_release_id = await self._ctx.repository.get_active_release_id()
        active_release = (
            await self._ctx.repository.get_release(active_release_id)
            if active_release_id
            else None
        )

        if active_release and active_release.manifest:
            for entry in active_release.manifest:
                if entry.document_id in excluded:
                    continue
                version = await self._ctx.repository.get_version(entry.version_id)
                if version is not None and version.status == "PUBLISHED":
                    published_versions.append(version)
        else:
            # Fallback when no active release exists (e.g. first release):
            # Query with PLATFORM role so cross-unit documents are included.
            admin_actor = (
                actor
                if actor.role == "PLATFORM"
                else PortalActor(
                    user_id=actor.user_id,
                    display_name=actor.display_name,
                    role="PLATFORM",
                    owner_unit_ids=(),
                    tenant_id=actor.tenant_id,
                )
            )
            for other in await self._ctx.repository.list_documents(actor=admin_actor):
                if other.document_id in excluded:
                    continue
                if not other.current_published_version_id:
                    continue
                other_version = await self._ctx.repository.get_version(
                    other.current_published_version_id
                )
                if other_version is not None and other_version.status == "PUBLISHED":
                    published_versions.append(other_version)

        return published_versions

    async def _activate_release(
        self,
        *,
        actor: PortalActor,
        published_versions: list[KnowledgeVersionRecord],
        correlation_id: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> ReleaseRecord | None:
        previous_release_id = await self._ctx.repository.get_active_release_id()
        if not published_versions:
            await self._ctx.repository.set_active_release_id(None)
            write_active_release_pointer(self._ctx.settings.release_artifact_dir, None)
            await self._ctx.audit(
                actor=actor,
                action="release.clear",
                target_type="release",
                target_id=previous_release_id or "none",
                correlation_id=correlation_id,
                reason=reason,
                metadata=metadata or {},
            )
            return None

        release_id = new_id("release")
        try:
            release = self._ctx.publisher.build_release(
                release_id=release_id,
                published_versions=published_versions,
                created_by=actor.user_id,
                previous_release_id=previous_release_id,
            )
        except ReleaseBuildError as exc:
            await self._ctx.audit(
                actor=actor,
                action="release.failed",
                target_type="release",
                target_id=release_id,
                correlation_id=correlation_id,
                reason=str(exc),
                result="FAILURE",
            )
            raise

        release = release.model_copy(
            update={
                "status": "DEPLOYING",
                "activated_at": utc_now(),
                "approved_by": actor.user_id,
            }
        )
        await self._deactivate_other_releases(release.release_id)
        await self._ctx.repository.save_release(release)
        await self._ctx.repository.set_active_release_id(release.release_id)
        write_active_release_pointer(
            self._ctx.settings.release_artifact_dir,
            release.release_id,
        )

        reload_success, reload_error = await self._notify_agent_reload(
            release.release_id, correlation_id
        )
        if reload_success:
            release = release.model_copy(
                update={
                    "status": "ACTIVE",
                    "verified_at": utc_now(),
                    "failure_summary": "",
                }
            )
        else:
            release = release.model_copy(
                update={
                    "status": "RELOAD_FAILED",
                    "failure_summary": reload_error or "Agent reload failed",
                }
            )
        await self._ctx.repository.save_release(release)

        audit_meta = dict(metadata or {})
        audit_meta["reloadStatus"] = "SUCCESS" if reload_success else "FAILURE"
        if reload_error:
            audit_meta["reloadError"] = reload_error

        await self._ctx.audit(
            actor=actor,
            action="release.activate",
            target_type="release",
            target_id=release.release_id,
            correlation_id=correlation_id,
            reason=reason,
            metadata=audit_meta,
        )
        return release

    async def _deactivate_other_releases(self, active_release_id: str) -> None:
        for item in await self._ctx.repository.list_releases():
            if item.release_id == active_release_id:
                continue
            if item.status in {"ACTIVE", "DEPLOYING", "RELOAD_FAILED"}:
                await self._ctx.repository.save_release(
                    item.model_copy(update={"status": "ROLLED_BACK"})
                )

