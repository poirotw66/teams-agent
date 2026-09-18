"""Bootstrap helpers for importing a Markdown corpus into release-0001."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from knowledge_core.front_matter import parse_front_matter
from knowledge_core.release_gate import ReleaseGateBlockedError, require_release_gate
from knowledge_core.release_pointer import write_active_release_pointer
from knowledge_core.target_manifest import knowledge_release_target_manifest_hash

from .draft_assets import slug_from_title
from .models import (
    AudienceType,
    AuditEventRecord,
    KnowledgeDocumentRecord,
    KnowledgeVersionRecord,
    PortalActor,
    ReleaseRecord,
    new_etag,
)
from .publisher import ReleaseBuildError, ReleasePublisher
from .repository import new_id
from .settings import PortalSettings
from .validation import (
    build_front_matter_markdown,
    build_parse_preview,
    content_hash,
    validate_draft,
)


def stable_document_id(source_path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", source_path.stem).strip("-").lower()
    digest = hashlib.sha256(source_path.as_posix().encode("utf-8")).hexdigest()[:10]
    return f"doc-{slug[:24]}-{digest}"


def parse_source_file(
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
    canonical = (
        raw
        if raw.lstrip().startswith("---")
        else build_front_matter_markdown(
            title=title,
            owner_unit_id=owner,
            effective_at=effective_at,
            review_due_at=review_due_at,
            audience_type=audience_type,
            audience_group_ids=audience_group_ids,
            version_number=1,
            body=body or raw,
        )
    )
    return title, owner, effective_at, review_due_at, audience_type, audience_group_ids, canonical


def build_imported_records(
    *,
    source_path: Path,
    index: int,
    settings: PortalSettings,
    actor: PortalActor,
    change_reason: str,
    now: Any,
) -> tuple[KnowledgeVersionRecord, KnowledgeDocumentRecord]:
    """Parse, validate, and build version/document records for one source file."""
    (
        title,
        owner_unit_id,
        effective_at,
        review_due_at,
        audience_type,
        audience_group_ids,
        canonical,
    ) = parse_source_file(
        source_path,
        default_owner_unit_id=settings.default_owner_unit_id,
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
            f"Source {source_path.name} failed validation: {validation.issues[0].message}"
        )

    document_id = stable_document_id(source_path)
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
    return version, document


async def import_source_versions(
    *,
    repository: Any,
    settings: PortalSettings,
    actor: PortalActor,
    source_files: list[Path],
    change_reason: str,
    now: Any,
) -> list[KnowledgeVersionRecord]:
    """Validate and persist one published version per Markdown source file."""
    published_versions: list[KnowledgeVersionRecord] = []
    for index, source_path in enumerate(source_files, start=1):
        version, document = build_imported_records(
            source_path=source_path,
            index=index,
            settings=settings,
            actor=actor,
            change_reason=change_reason,
            now=now,
        )
        await repository.save_version(version)
        await repository.save_document(document)
        published_versions.append(version)
    return published_versions


async def _persist_active_bootstrap_release(
    *,
    repository: Any,
    settings: PortalSettings,
    actor: PortalActor,
    release: ReleaseRecord,
    gate_hash: str,
    now: Any,
    bundled_index_path: Path | None,
    source_files: list[Path],
    sources_dir: Path,
    change_reason: str,
    correlation_id: str,
) -> ReleaseRecord:
    release = release.model_copy(
        update={
            "status": "DEPLOYING",
            "activated_at": now,
            "verified_at": None,
            "approved_by": actor.user_id,
            "target_manifest_hash": gate_hash,
        }
    )
    await repository.save_release(release)
    await repository.set_active_release_id(release.release_id)
    if not settings.release_gcs_bucket:
        write_active_release_pointer(settings.release_artifact_dir, release.release_id)
    await repository.append_audit(
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


async def activate_bootstrap_release(
    *,
    repository: Any,
    settings: PortalSettings,
    publisher: ReleasePublisher,
    actor: PortalActor,
    release_id: str,
    published_versions: list[KnowledgeVersionRecord],
    bundled_index_path: Path | None,
    source_files: list[Path],
    sources_dir: Path,
    change_reason: str,
    correlation_id: str,
    now: Any,
    release_gate_checker: Any | None,
) -> ReleaseRecord:
    """Build, gate-check, and activate a bootstrap release artifact."""
    try:
        release = publisher.build_release(
            release_id=release_id,
            published_versions=published_versions,
            created_by=actor.user_id,
            previous_release_id=await repository.get_active_release_id(),
            bundled_index_path=bundled_index_path,
            tenant_id=actor.tenant_id,
        )
    except ReleaseBuildError as exc:
        raise ValueError(str(exc)) from exc

    gate_hash = release.target_manifest_hash or knowledge_release_target_manifest_hash(
        release_id=release.release_id
    )
    try:
        require_release_gate(
            release_gate_checker,
            target_manifest_hash=gate_hash,
            target_type="KNOWLEDGE",
            tenant_id=getattr(actor, "tenant_id", None),
        )
    except ReleaseGateBlockedError as exc:
        blocked = release.model_copy(
            update={
                "status": "GATE_BLOCKED",
                "failure_summary": str(exc),
                "target_manifest_hash": gate_hash,
            }
        )
        await repository.save_release(blocked)
        raise PermissionError(str(exc)) from exc

    return await _persist_active_bootstrap_release(
        repository=repository,
        settings=settings,
        actor=actor,
        release=release,
        gate_hash=gate_hash,
        now=now,
        bundled_index_path=bundled_index_path,
        source_files=source_files,
        sources_dir=sources_dir,
        change_reason=change_reason,
        correlation_id=correlation_id,
    )
