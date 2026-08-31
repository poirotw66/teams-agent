from __future__ import annotations

from typing import Any

from agent_service.knowledge_release import write_active_release_pointer

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
from ..rbac import ensure_can_publish, ensure_can_remove_document, ensure_not_found
from ..role_capabilities import ensure_can_list_releases
from ..repository import new_id
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
    ) -> ReleaseRecord:
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
    ) -> ReleaseRecord:
        ensure_can_publish(actor)
        target = await self._ctx.repository.get_release(request.release_id)
        ensure_not_found("release", request.release_id, target)
        previous_active_id = await self._ctx.repository.get_active_release_id()
        await self._deactivate_other_releases(target.release_id)
        await self._ctx.repository.set_active_release_id(target.release_id)
        write_active_release_pointer(
            self._ctx.settings.release_artifact_dir,
            target.release_id,
        )
        rolled_back = target.model_copy(
            update={"status": "ACTIVE", "activated_at": utc_now()}
        )
        await self._ctx.repository.save_release(rolled_back)
        await self._ctx.audit(
            actor=actor,
            action="release.rollback",
            target_type="release",
            target_id=target.release_id,
            correlation_id=correlation_id,
            reason=request.reason,
            metadata={"previousReleaseId": previous_active_id},
        )
        return rolled_back

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
        for other in await self._ctx.repository.list_documents(actor=actor):
            if other.document_id in excluded:
                continue
            if other.status != "PUBLISHED" or not other.current_published_version_id:
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
                "status": "ACTIVE",
                "activated_at": utc_now(),
                "verified_at": utc_now(),
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
        await self._ctx.audit(
            actor=actor,
            action="release.activate",
            target_type="release",
            target_id=release.release_id,
            correlation_id=correlation_id,
            reason=reason,
            metadata=metadata or {},
        )
        return release

    async def _deactivate_other_releases(self, active_release_id: str) -> None:
        for item in await self._ctx.repository.list_releases():
            if item.release_id == active_release_id:
                continue
            if item.status != "ACTIVE":
                continue
            await self._ctx.repository.save_release(
                item.model_copy(update={"status": "ROLLED_BACK"})
            )
