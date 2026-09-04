from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
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
    ReleaseManifestEntry,
    ReleaseRecord,
    RemoveDocumentRequest,
    RollbackRequest,
    utc_now,
)
from ..publisher import ReleaseBuildError
from ..rbac import (
    PortalPermissionError,
    can_edit_document,
    can_view_document,
    ensure_can_publish,
    ensure_not_found,
)
from ..repository import new_id
from ..role_capabilities import ensure_can_list_releases
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
        if idempotency_key:
            scope_key = f"publish::{actor.tenant_id or 'default'}::{actor.user_id}::{idempotency_key}"
            payload_hash = hashlib.sha256(f"{document_id}::{request.model_dump_json()}".encode()).hexdigest()
            status, cached = await self._ctx.claim_idempotency(scope_key, payload_hash)
            if status == "CACHED" and cached is not None:
                if isinstance(cached, dict):
                    return ReleaseRecord.model_validate(cached)
                return cached

        try:
            ensure_can_publish(actor)
            async with self._coordination_lock("publish"):
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
                await self._ctx.complete_idempotency(scope_key, payload_hash, release)
            return release
        except Exception:
            if idempotency_key:
                await self._ctx.fail_idempotency(scope_key)
            raise

    async def unpublish_document(
        self,
        actor: PortalActor,
        document_id: str,
        request: RemoveDocumentRequest,
        correlation_id: str,
    ) -> DocumentDetailResponse:
        ensure_can_publish(actor)
        async with self._coordination_lock("unpublish"):
            detail = await self._documents.get_document(actor, document_id)
            document = detail.document
            if document.status != "PUBLISHED" and not document.current_published_version_id:
                raise ValueError("Only published documents can be unpublished.")

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
            payload_hash = hashlib.sha256(f"{request.release_id}::{request.reason}".encode()).hexdigest()
            status, cached = await self._ctx.claim_idempotency(scope_key, payload_hash)
            if status == "CACHED" and cached is not None:
                if isinstance(cached, dict):
                    return ReleaseRecord.model_validate(cached)
                return cached

        try:
            ensure_can_publish(actor)
            target = await self._ctx.repository.get_release(request.release_id)
            ensure_not_found("release", request.release_id, target)
            previous_active_id = await self._ctx.repository.get_active_release_id()
            previous_release = (
                await self._ctx.repository.get_release(previous_active_id)
                if previous_active_id
                else None
            )

            target_manifest = {entry.document_id: entry.version_id for entry in target.manifest}
            prev_manifest = (
                {entry.document_id: entry.version_id for entry in previous_release.manifest}
                if previous_release
                else {}
            )

            # Issue 1: Unit managers cannot perform global rollbacks affecting documents from other units
            if actor.role != "PLATFORM":
                affected_doc_ids = set(target_manifest.keys()) | set(prev_manifest.keys())
                for doc_id in affected_doc_ids:
                    doc = await self._ctx.repository.get_document(doc_id)
                    if doc and not can_edit_document(
                        actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
                    ):
                        raise PortalPermissionError(
                            "Global rollback affects documents from other units. Only platform administrators can perform global rollbacks."
                        )

            async with self._coordination_lock("rollback"):
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
                current_active = await self._ctx.repository.get_active_release_id()
                if current_active == target.release_id:
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
                else:
                    logger.warning(
                        "Rollback %s reload finished, but active pointer has transitioned to %s.",
                        target.release_id,
                        current_active,
                    )

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
                await self._ctx.complete_idempotency(scope_key, payload_hash, rolled_back)
            return rolled_back
        except Exception:
            if idempotency_key:
                await self._ctx.fail_idempotency(scope_key)
            raise

    async def sync_agent_release(
        self,
        actor: PortalActor,
        release_id: str,
        correlation_id: str,
    ) -> ReleaseRecord:
        ensure_can_publish(actor)
        release = await self._ctx.repository.get_release(release_id)
        ensure_not_found("release", release_id, release)
        active_id = await self._ctx.repository.get_active_release_id()
        if release_id != active_id:
            raise ValueError(
                f"Cannot sync release '{release_id}' because it is not the current active release ('{active_id}'). Use rollback to switch versions."
            )

        reload_success, reload_error = await self._notify_agent_reload(
            release_id, correlation_id
        )
        async with self._coordination_lock("sync_agent"):
            current_active = await self._ctx.repository.get_active_release_id()
            if current_active != release_id:
                logger.warning(
                    "Agent reload completed for release %s, but active release has transitioned to %s; discarding stale state mutation.",
                    release_id,
                    current_active,
                )
                return release

            if reload_success:
                updated = release.model_copy(
                    update={
                        "status": "ACTIVE",
                        "verified_at": utc_now(),
                        "failure_summary": "",
                    }
                )
                await self._deactivate_other_releases(release_id)
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
                    try:
                        data = resp.json()
                        returned_release = data.get("releaseId")
                        if returned_release and returned_release != release_id:
                            err_msg = (
                                f"Agent reload returned release '{returned_release}' "
                                f"which does not match expected '{release_id}'"
                            )
                            logger.warning(err_msg)
                            return False, err_msg
                    except Exception:  # noqa: S110
                        pass
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
        releases = await self._ctx.repository.list_releases()
        if actor.role == "PLATFORM" or not actor.owner_unit_ids:
            return releases

        sanitized_releases: list[ReleaseRecord] = []
        for release in releases:
            sanitized_manifest: list[ReleaseManifestEntry] = []
            for entry in release.manifest:
                doc = await self._ctx.repository.get_document(entry.document_id)
                if doc and can_view_document(
                    actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
                ):
                    sanitized_manifest.append(entry)
                else:
                    sanitized_manifest.append(
                        entry.model_copy(update={"title": "[Restricted Document]"})
                    )
            sanitized_releases.append(
                release.model_copy(update={"manifest": sanitized_manifest})
            )
        return sanitized_releases

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
            doc = await self._ctx.repository.get_document(doc_id)
            is_visible = (
                actor.role == "PLATFORM"
                or not actor.owner_unit_ids
                or (
                    doc is not None
                    and can_view_document(
                        actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
                    )
                )
            )
            title = entry.title if is_visible else "[Restricted Document]"
            current_entry = current_manifest.get(doc_id)
            if current_entry is None:
                changes.append(
                    ReleaseDocumentChange(
                        document_id=doc_id,
                        title=title,
                        change_type="ADDED",
                        target_version_id=entry.version_id,
                    )
                )
            elif current_entry.version_id != entry.version_id:
                changes.append(
                    ReleaseDocumentChange(
                        document_id=doc_id,
                        title=title,
                        change_type="UPDATED",
                        current_version_id=current_entry.version_id,
                        target_version_id=entry.version_id,
                    )
                )
        for doc_id, entry in current_manifest.items():
            if doc_id not in target_manifest:
                doc = await self._ctx.repository.get_document(doc_id)
                is_visible = (
                    actor.role == "PLATFORM"
                    or not actor.owner_unit_ids
                    or (
                        doc is not None
                        and can_view_document(
                            actor, doc.owner_unit_id, doc.created_by, tenant_id=doc.tenant_id
                        )
                    )
                )
                title = entry.title if is_visible else "[Restricted Document]"
                changes.append(
                    ReleaseDocumentChange(
                        document_id=doc_id,
                        title=title,
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
    ) -> ReleaseRecord:
        previous_release_id = await self._ctx.repository.get_active_release_id()
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
        current_active = await self._ctx.repository.get_active_release_id()
        if current_active == release.release_id:
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
        else:
            logger.warning(
                "Release %s reload finished, but active pointer has transitioned to %s.",
                release.release_id,
                current_active,
            )

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

