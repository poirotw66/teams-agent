"""SourceRecord <-> ResolvedSource mapping helpers."""

from __future__ import annotations

from knowledge_core.source_resolution import ResolvedSource

from .source_models import MappingStatus, SourceLocator, SourceRecord

__all__ = [
    "resolved_to_source_record",
    "source_record_to_resolved",
]


def source_record_to_resolved(rec: SourceRecord) -> ResolvedSource:
    original_available = bool(
        rec.artifact_ref
        or (rec.original_asset_name and rec.mapping_status == MappingStatus.AVAILABLE)
    )
    return ResolvedSource(
        source_ref_id=rec.source_ref_id,
        title=rec.title,
        document_id=rec.document_id,
        version_id=rec.version_id,
        release_id=rec.release_id,
        chunk_id=rec.chunk_id,
        source_path=rec.source_path,
        content=rec.excerpt,
        source_type=rec.source_type,
        original_asset_available=original_available,
        original_asset_name=rec.original_asset_name,
        original_asset_path=None,
        trace_status="EXACT",
        tenant_id=rec.tenant_id,
        artifact_ref=rec.artifact_ref,
        mapping_status=(
            rec.mapping_status.value
            if hasattr(rec.mapping_status, "value")
            else str(rec.mapping_status)
        ),
        locator=rec.locator,
        owner_unit_id=rec.owner_unit_id,
        acl_groups=tuple(rec.acl_groups),
        is_archived=rec.is_archived,
        is_deleted=rec.is_deleted,
    )


def resolved_to_source_record(resolved: ResolvedSource, *, tenant_id: str) -> SourceRecord:
    mapping_status = (
        MappingStatus(resolved.mapping_status)
        if resolved.mapping_status in MappingStatus.__members__
        else MappingStatus.AVAILABLE
    )
    return SourceRecord(
        source_ref_id=resolved.source_ref_id,
        tenant_id=tenant_id,
        document_id=resolved.document_id or "",
        version_id=resolved.version_id or "",
        release_id=resolved.release_id or "",
        chunk_id=resolved.chunk_id,
        artifact_ref=resolved.artifact_ref,
        content_hash="",
        locator_ref=None,
        locator=resolved.locator if isinstance(resolved.locator, SourceLocator) else None,
        mapping_status=mapping_status,
        owner_unit_id=resolved.owner_unit_id,
        acl_groups=list(resolved.acl_groups),
        source_type=resolved.source_type,
        title=resolved.title,
        source_path=resolved.source_path,
        excerpt=resolved.content,
        original_asset_name=resolved.original_asset_name,
        is_archived=resolved.is_archived,
        is_deleted=resolved.is_deleted,
    )
