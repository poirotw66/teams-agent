from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agent_service.documents import parse_front_matter

from .models import (
    AudienceType,
    AuditEventRecord,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    ReleaseRecord,
    new_etag,
    utc_now,
)
from .publisher import ReleaseBuildError, ReleasePublisher
from .rbac import require_minimum_role
from .repository import new_id
from .settings import PortalSettings
from .draft_assets import slug_from_title
from .validation import (
    build_front_matter_markdown,
    build_parse_preview,
    content_hash,
    validate_draft,
)


def _stable_document_id(source_path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", source_path.stem).strip("-").lower()
    digest = hashlib.sha256(source_path.as_posix().encode("utf-8")).hexdigest()[:10]
    return f"doc-{slug[:24]}-{digest}"


def _parse_source_file(
    source_path: Path,
    *,
    default_owner_unit_id: str,
) -> tuple[str, str, str, str, AudienceType, list[str], str]:
    raw = source_path.read_text(encoding="utf-8")
    front_matter, body = parse_front_matter(raw)
    title = str(front_matter.get("title") or source_path.stem)
    owner = str(front_matter.get("owner") or default_owner_unit_id)
    effective_at = str(front_matter.get("effectiveDate") or "2026-01-01")
    review_due_at = str(front_matter.get("reviewDate") or "2026-12-31")
    audience_raw = front_matter.get("audience") or ["all-employees"]
    if not isinstance(audience_raw, list):
        audience_raw = [audience_raw]
    audience_values = [str(item) for item in audience_raw]
    if "all-employees" in audience_values:
        audience_type: AudienceType = "ALL_EMPLOYEES"
        audience_group_ids: list[str] = []
    else:
        audience_type = "RESTRICTED_GROUPS"
        audience_group_ids = audience_values
    canonical = raw if raw.lstrip().startswith("---") else build_front_matter_markdown(
        title=title,
        owner_unit_id=owner,
        effective_at=effective_at,
        review_due_at=review_due_at,
        audience_type=audience_type,
        audience_group_ids=audience_group_ids,
        version_number=1,
        body=body or raw,
    )
    return title, owner, effective_at, review_due_at, audience_type, audience_group_ids, canonical


class KnowledgeMigrationService:
    def __init__(self, settings: PortalSettings, repository, publisher: ReleasePublisher) -> None:
        self._settings = settings
        self._repository = repository
        self._publisher = publisher

    async def bootstrap_release_0001(
        self,
        *,
        actor: PortalActor,
        sources_dir: Path,
        correlation_id: str,
        release_id: str = "release-0001",
        change_reason: str = "Baseline import from existing Markdown corpus.",
        bundled_index_path: Path | None = None,
    ) -> ReleaseRecord:
        require_minimum_role(actor, "PLATFORM")
        if not sources_dir.is_dir():
            raise FileNotFoundError(f"Sources directory not found: {sources_dir}")

        source_files = sorted(
            path
            for path in sources_dir.glob("*.md")
            if not path.name.upper().startswith("README")
        )
        if not source_files:
            raise ValueError(f"No Markdown sources found in {sources_dir}")

        now = utc_now()
        published_versions: list[KnowledgeVersionRecord] = []
        for index, source_path in enumerate(source_files, start=1):
            (
                title,
                owner_unit_id,
                effective_at,
                review_due_at,
                audience_type,
                audience_group_ids,
                canonical,
            ) = _parse_source_file(
                source_path,
                default_owner_unit_id=self._settings.default_owner_unit_id,
            )
            validation = validate_draft(
                title=title,
                owner_unit_id=owner_unit_id,
                change_reason=change_reason,
                effective_at=effective_at,
                review_due_at=review_due_at,
                audience_type=audience_type,
                audience_group_ids=audience_group_ids,
                markdown_content=canonical,
            )
            if validation.has_blocking:
                raise ValueError(
                    f"Source {source_path.name} failed validation: "
                    f"{validation.issues[0].message}"
                )

            document_id = _stable_document_id(source_path)
            version_id = f"ver-{document_id}-1"
            digest = content_hash(canonical)
            version = KnowledgeVersionRecord(
                version_id=version_id,
                document_id=document_id,
                version_number=1,
                content_hash=digest,
                canonical_content=canonical,
                change_summary="Baseline import",
                change_reason=change_reason,
                effective_at=effective_at,
                review_due_at=review_due_at,
                audience_type=audience_type,
                audience_group_ids=audience_group_ids,
                owner_unit_id=owner_unit_id,
                title=title,
                asset_slug=slug_from_title(title),
                status="PUBLISHED",
                validation_summary=validation,
                parse_preview=build_parse_preview(canonical, title),
                etag=new_etag(digest),
                created_at=now,
                created_by=actor.user_id,
            )
            document = KnowledgeDocumentRecord(
                document_id=document_id,
                title=title,
                summary=f"Imported from {source_path.name}",
                owner_unit_id=owner_unit_id,
                audience_type=audience_type,
                audience_group_ids=audience_group_ids,
                current_published_version_id=version_id,
                draft_version_id=None,
                status="PUBLISHED",
                etag=new_etag(document_id, index),
                created_at=now,
                created_by=actor.user_id,
                updated_at=now,
                updated_by=actor.user_id,
            )
            await self._repository.save_version(version)
            await self._repository.save_document(document)
            published_versions.append(version)

        try:
            release = self._publisher.build_release(
                release_id=release_id,
                published_versions=published_versions,
                created_by=actor.user_id,
                previous_release_id=await self._repository.get_active_release_id(),
                bundled_index_path=bundled_index_path,
            )
        except ReleaseBuildError as exc:
            raise ValueError(str(exc)) from exc

        from agent_service.knowledge_release import write_active_release_pointer

        release = release.model_copy(
            update={
                "status": "ACTIVE",
                "activated_at": now,
                "verified_at": now,
                "approved_by": actor.user_id,
            }
        )
        await self._repository.save_release(release)
        await self._repository.set_active_release_id(release.release_id)
        write_active_release_pointer(
            self._settings.release_artifact_dir,
            release.release_id,
        )
        await self._repository.append_audit(
            AuditEventRecord(
                event_id=new_id("audit"),
                actor_id=actor.user_id,
                actor_role=actor.role,
                action="release.sync" if bundled_index_path else "release.bootstrap",
                target_type="release",
                target_id=release.release_id,
                correlation_id=correlation_id,
                reason=change_reason,
                occurred_at=now,
                metadata={
                    "sourceCount": len(source_files),
                    "sourcesDir": str(sources_dir),
                    "bundledIndexPath": str(bundled_index_path) if bundled_index_path else None,
                },
            )
        )
        return release

    async def sync_from_local_corpus(
        self,
        *,
        actor: PortalActor,
        sources_dir: Path,
        bundled_index_path: Path | None,
        correlation_id: str,
        release_id: str = "release-0001",
    ) -> ReleaseRecord:
        return await self.bootstrap_release_0001(
            actor=actor,
            sources_dir=sources_dir,
            correlation_id=correlation_id,
            release_id=release_id,
            change_reason="Synced portal release from local sources and bundled index.",
            bundled_index_path=bundled_index_path,
        )
