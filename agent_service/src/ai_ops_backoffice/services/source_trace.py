"""Resolve answer citations to a release-scoped, authorized source preview.

Provides direct O(1) repository queries, bounded LRU/TTL caching, strict historical
version matching without fallbacks, and multi-format locators (F02, F03, F08, A06).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent_service.artifact_storage import ArtifactStorage
from agent_service.source_refs import (
    ResolvedSource,
    _find_manifest_entry,
    _manifest_by_key,
    _original_asset_path,
    make_source_ref_id,
    safe_source_path,
    source_path_stem,
)
from .source_models import (
    LocatorType,
    MappingStatus,
    SourceLocator,
    SourceRecord,
)
from .source_repository import (
    BoundedSourceCache,
    InMemorySourceRecordRepository,
    SourceRecordRepository,
)

_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_SOURCE_EVENTS = frozenset({"knowledge.retrieved", "knowledge.answered"})
_ReleaseLoad = tuple[
    Path,
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]


class SourceTraceResolver:
    """Read-only resolver over private release artifacts and direct SourceRecord repository.

    The resolver never exposes filesystem paths directly. It provides direct O(1) lookups
    via bounded cache and repository, avoiding release scans on direct citations.
    """

    def __init__(
        self,
        releases_dir: Path,
        source_repository: SourceRecordRepository | None = None,
        cache: BoundedSourceCache | None = None,
        artifact_storage: ArtifactStorage | None = None,
    ) -> None:
        self.releases_dir = releases_dir.expanduser().resolve()
        self.source_repository = source_repository or InMemorySourceRecordRepository()
        self.cache = cache or BoundedSourceCache(max_size=500, ttl_seconds=300.0)
        self.artifact_storage = artifact_storage
        self._release_cache: dict[str, tuple[int, int, _ReleaseLoad]] = {}

    def _active_release_id(self) -> str | None:
        pointer = self.releases_dir / "active_release.json"
        if not pointer.is_file():
            return None
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = payload.get("releaseId") or payload.get("release_id")
        return str(value) if value else None

    def _release_ids(self, preferred: str | None = None) -> list[str]:
        values: list[str] = []
        for value in (preferred, self._active_release_id()):
            if value and _SAFE_RELEASE_ID.fullmatch(value) and value not in values:
                values.append(value)
        if self.releases_dir.is_dir():
            for path in sorted(self.releases_dir.iterdir(), reverse=True):
                if path.is_dir() and _SAFE_RELEASE_ID.fullmatch(path.name):
                    if path.name not in values:
                        values.append(path.name)
        return values

    def _load_release(
        self, release_id: str
    ) -> tuple[Path, list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]] | None:
        if not _SAFE_RELEASE_ID.fullmatch(release_id):
            return None
        release_root = (self.releases_dir / release_id).resolve()
        try:
            release_root.relative_to(self.releases_dir)
        except ValueError:
            return None
        index_path = release_root / "index" / "chunks.json"
        if not index_path.is_file():
            self._release_cache.pop(release_id, None)
            return None
        try:
            stat = index_path.stat()
            cache_key = (stat.st_mtime_ns, stat.st_size)
            cached = self._release_cache.get(release_id)
            if cached is not None and cached[:2] == cache_key:
                return cached[2]
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._release_cache.pop(release_id, None)
            return None
        chunks = [item for item in payload.get("chunks", []) if isinstance(item, dict)]
        by_id, by_title = _manifest_by_key(release_root)
        loaded = (release_root, chunks, by_id, by_title)
        self._release_cache[release_id] = (cache_key[0], cache_key[1], loaded)
        return loaded

    @staticmethod
    def _match_chunk(
        chunks: list[dict[str, Any]],
        citation: dict[str, Any],
    ) -> dict[str, Any] | None:
        chunk_id = citation.get("chunkId")
        if chunk_id:
            for chunk in chunks:
                if str(chunk.get("chunk_id") or chunk.get("chunkId") or "") == str(chunk_id):
                    return chunk
            # F03: If chunk_id is specified but not found, DO NOT fallback to other chunks!
            return None
        source_path = safe_source_path(citation.get("sourcePath"))
        if source_path and source_path != "[REDACTED_SOURCE]":
            matches = [
                chunk
                for chunk in chunks
                if safe_source_path(chunk.get("source_path")) == source_path
            ]
            if len(matches) == 1:
                return matches[0]
            return None
        title = str(citation.get("title") or "").casefold()
        if title:
            matches = [
                chunk
                for chunk in chunks
                if str(chunk.get("title") or "").casefold() == title
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    @staticmethod
    def _build_locator(
        source_type: str,
        chunk: dict[str, Any],
        entry: dict[str, Any],
        citation: dict[str, Any],
    ) -> SourceLocator:
        st = (source_type or "").upper()
        if "PDF" in st:
            raw_idx = chunk.get("page_index") or citation.get("pageIndex")
            page_idx = int(raw_idx) if raw_idx is not None else None
            page_lbl = chunk.get("page_label") or citation.get("pageLabel")
            bbox = chunk.get("bbox") or citation.get("bbox")
            coord = (
                chunk.get("coordinate_system")
                or citation.get("coordinateSystem")
                or "PDF_POINTS_72DPI"
            )
            degraded = None if page_idx is not None else "原檔頁面定位不可用，已顯示段落摘錄。"
            return SourceLocator(
                locator_type=LocatorType.PDF,
                page_index=page_idx,
                page_label=str(page_lbl) if page_lbl is not None else (str(page_idx + 1) if page_idx is not None else None),
                bbox=bbox if isinstance(bbox, list) else None,
                coordinate_system=coord,
                degraded_reason=degraded,
            )
        if any(ext in st for ext in ("DOCX", "PPTX", "WORD", "POWERPOINT", "OFFICE")):
            preview_ref = (
                chunk.get("preview_replica_artifact_ref")
                or entry.get("preview_replica_artifact_ref")
                or citation.get("previewReplicaArtifactRef")
            )
            conv_ver = (
                chunk.get("converter_version")
                or entry.get("converter_version")
                or citation.get("converterVersion")
                or "libreoffice-7.6.2"
            )
            slide_idx = chunk.get("slide_index") or citation.get("slideIndex")
            sec_path = chunk.get("section_path") or citation.get("sectionPath")
            return SourceLocator(
                locator_type=LocatorType.OFFICE_PREVIEW,
                preview_replica_artifact_ref=preview_ref,
                converter_version=conv_ver,
                slide_index=int(slide_idx) if slide_idx is not None else None,
                section_path=str(sec_path) if sec_path else None,
                degraded_reason=(
                    "Office 文件已產生 PDF 預覽副本供比對，原檔可直接下載。"
                    if preview_ref
                    else "無可靠預覽副本，僅提供章節與摘錄。"
                ),
            )
        if any(ext in st for ext in ("XLSX", "XLS", "CSV", "SPREADSHEET", "EXCEL")):
            sheet = chunk.get("sheet_name") or citation.get("sheetName")
            cell_range = chunk.get("cell_range") or citation.get("cellRange")
            return SourceLocator(
                locator_type=LocatorType.SPREADSHEET,
                sheet_name=str(sheet) if sheet else None,
                cell_range=str(cell_range) if cell_range else None,
                degraded_reason="試算表格式不支援頁面高亮，請依工作表與儲存格範圍檢視。",
            )
        if "MARKDOWN" in st or "MD" in st:
            sec_path = (
                chunk.get("section_path")
                or citation.get("sectionPath")
                or chunk.get("heading")
            )
            para_id = chunk.get("paragraph_id") or citation.get("paragraphId")
            return SourceLocator(
                locator_type=LocatorType.MARKDOWN,
                section_path=str(sec_path) if sec_path else None,
                paragraph_id=str(para_id) if para_id else None,
            )
        return SourceLocator(
            locator_type=LocatorType.UNSUPPORTED,
            degraded_reason="此檔案格式不支援精準頁面高亮。",
        )

    def _source_record_to_resolved(self, rec: SourceRecord) -> ResolvedSource:
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
            mapping_status=rec.mapping_status.value if hasattr(rec.mapping_status, "value") else str(rec.mapping_status),
            locator=rec.locator,
            owner_unit_id=rec.owner_unit_id,
            acl_groups=tuple(rec.acl_groups),
            is_archived=rec.is_archived,
            is_deleted=rec.is_deleted,
        )

    def _resolved_to_source_record(
        self, resolved: ResolvedSource, *, tenant_id: str
    ) -> SourceRecord:
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

    def resolve_citation(
        self,
        citation: dict[str, Any],
        *,
        fallback_release_id: str | None = None,
        tenant_id: str = "default",
    ) -> ResolvedSource | None:
        if not isinstance(citation, dict):
            return None
        explicit_ref = str(citation.get("sourceRefId") or "") or None
        target_release = (
            str(citation.get("releaseId") or fallback_release_id or "") or None
        )

        # F03: If releaseId is specified, search ONLY that release. Do not fallback!
        candidate_releases = [target_release] if target_release else self._release_ids()

        for release_id in candidate_releases:
            if not release_id:
                continue
            loaded = self._load_release(release_id)
            if loaded is None:
                continue
            release_root, chunks, by_id, by_title = loaded
            chunk = self._match_chunk(chunks, citation)
            if chunk is None:
                continue

            chunk_source_path = safe_source_path(
                str(chunk.get("source_path") or chunk.get("sourcePath") or "")
            )
            chunk_title = str(chunk.get("title") or citation.get("title") or "") or None
            entry = _find_manifest_entry(
                source_path=chunk_source_path,
                title=chunk_title,
                document_id=(
                    str(citation.get("documentId"))
                    if citation.get("documentId")
                    else None
                ),
                by_id=by_id,
                by_title=by_title,
            )
            document_id = str(
                citation.get("documentId")
                or chunk.get("document_id")
                or (entry or {}).get("document_id")
                or (entry or {}).get("documentId")
                or (source_path_stem(chunk_source_path) or "")
            ) or None
            actual_chunk_version = str(
                chunk.get("version_id")
                or (entry or {}).get("version_id")
                or (entry or {}).get("versionId")
                or ""
            ) or None

            # F03: If version was specified in citation, enforce exact match with the actual chunk version
            expected_ver = citation.get("versionId")
            if expected_ver and actual_chunk_version and str(expected_ver) != str(actual_chunk_version):
                continue

            version_id = actual_chunk_version or (str(citation.get("versionId")) if citation.get("versionId") else None)

            resolved_release = str(citation.get("releaseId") or release_id)
            chunk_id = str(
                citation.get("chunkId")
                or chunk.get("chunk_id")
                or chunk.get("chunkId")
                or ""
            ) or None
            source_ref_id = explicit_ref or make_source_ref_id(
                release_id=resolved_release,
                document_id=document_id,
                version_id=version_id,
                chunk_id=chunk_id,
                source_path=chunk_source_path,
            )
            if not source_ref_id:
                continue
            original_path = _original_asset_path(
                release_root,
                document_id=document_id,
                version_id=version_id,
            )
            original_available = original_path is not None
            requested_type = str(citation.get("sourceType") or "").upper()
            manifest_type = str(
                (entry or {}).get("source_type")
                or (entry or {}).get("sourceType")
                or chunk.get("source_type")
                or ""
            ).upper()
            source_type = requested_type or manifest_type or (
                "PDF"
                if original_path and original_path.suffix.lower() == ".pdf"
                else "DERIVED_MARKDOWN"
            )
            had_complete_identity = all(
                citation.get(key)
                for key in (
                    "sourceRefId",
                    "documentId",
                    "versionId",
                    "releaseId",
                    "sourcePath",
                )
            )

            is_edited = bool(
                chunk.get("is_edited_derivative")
                or (entry or {}).get("is_edited_derivative")
                or citation.get("isEditedDerivative")
            )
            if is_edited:
                mapping_status = MappingStatus.EDITED_DERIVATIVE.value
            elif original_available:
                mapping_status = MappingStatus.AVAILABLE.value
            else:
                mapping_status = MappingStatus.ORIGINAL_NOT_PRESERVED.value

            locator = self._build_locator(source_type, chunk, entry or {}, citation)

            resolved = ResolvedSource(
                source_ref_id=source_ref_id,
                title=chunk_title,
                document_id=document_id,
                version_id=version_id,
                release_id=resolved_release,
                chunk_id=chunk_id,
                source_path=chunk_source_path,
                content=str(chunk.get("content") or "") or None,
                source_type=source_type,
                original_asset_available=original_available,
                original_asset_name=original_path.name if original_path else None,
                original_asset_path=original_path,
                trace_status="EXACT" if had_complete_identity else "LEGACY_BACKFILLED",
                tenant_id=tenant_id,
                artifact_ref=str((entry or {}).get("artifact_ref") or "") or None,
                mapping_status=mapping_status,
                locator=locator,
                owner_unit_id=str((entry or {}).get("owner_unit_id") or "") or None,
                acl_groups=tuple((entry or {}).get("acl_groups") or ()),
            )
            return resolved

        return None

    def resolve_source_ref(
        self,
        source_ref_id: str,
        *,
        tenant_id: str = "default",
    ) -> ResolvedSource | None:
        """Resolve a source reference directly using O(1) bounded cache and repository.

        Avoids scanning all release directories unless querying legacy unindexed releases.
        """
        if not source_ref_id or not re.fullmatch(r"src-[0-9a-f]{24}", source_ref_id):
            return None

        # 1. Bounded LRU/TTL Cache Check (A06)
        cached = self.cache.get(tenant_id, source_ref_id)
        if cached is not None:
            return self._source_record_to_resolved(cached)

        # 2. Direct Repository Check (A06)
        rec = None
        if hasattr(self.source_repository, "get_source_record_sync"):
            rec = self.source_repository.get_source_record_sync(tenant_id, source_ref_id)
        if rec is not None:
            self.cache.put(rec)
            return self._source_record_to_resolved(rec)

        # 3. Fallback only for legacy unindexed release directories
        for release_id in self._release_ids():
            loaded = self._load_release(release_id)
            if loaded is None:
                continue
            _release_root, chunks, by_id, by_title = loaded
            for chunk in chunks:
                source_path = safe_source_path(str(chunk.get("source_path") or ""))
                entry = _find_manifest_entry(
                    source_path=source_path,
                    title=str(chunk.get("title") or ""),
                    document_id=None,
                    by_id=by_id,
                    by_title=by_title,
                )
                document_id = str(
                    chunk.get("document_id")
                    or (entry or {}).get("document_id")
                    or (entry or {}).get("documentId")
                    or (source_path_stem(source_path) or "")
                ) or None
                version_id = str(
                    chunk.get("version_id")
                    or (entry or {}).get("version_id")
                    or (entry or {}).get("versionId")
                    or ""
                ) or None
                chunk_id = str(chunk.get("chunk_id") or chunk.get("chunkId") or "") or None
                expected = make_source_ref_id(
                    release_id=release_id,
                    document_id=document_id,
                    version_id=version_id,
                    chunk_id=chunk_id,
                    source_path=source_path,
                )
                if expected != source_ref_id:
                    continue
                resolved = self.resolve_citation(
                    {
                        "sourceRefId": source_ref_id,
                        "title": chunk.get("title"),
                        "chunkId": chunk_id,
                        "documentId": document_id,
                        "versionId": version_id,
                        "releaseId": release_id,
                        "sourcePath": source_path,
                    },
                    fallback_release_id=release_id,
                    tenant_id=tenant_id,
                )
                if resolved is not None:
                    record = self._resolved_to_source_record(resolved, tenant_id=tenant_id)
                    if hasattr(self.source_repository, "save_source_record_sync"):
                        self.source_repository.save_source_record_sync(record)
                    self.cache.put(record)
                    return resolved
        return None

    def references_for_events(self, events: Iterable[Any]) -> list[dict[str, Any]]:
        references: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event in events:
            if getattr(event, "event_type", None) not in _SOURCE_EVENTS:
                continue
            payload = getattr(event, "payload", {}) or {}
            citations = payload.get("citations") or [payload]
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                resolved = self.resolve_citation(
                    citation,
                    fallback_release_id=(
                        str(payload.get("releaseId"))
                        if payload.get("releaseId")
                        else None
                    ),
                )
                if resolved is None or resolved.source_ref_id in seen:
                    continue
                seen.add(resolved.source_ref_id)
                references.append(self.reference_payload(resolved))
        return references

    @staticmethod
    def reference_payload(source: ResolvedSource) -> dict[str, Any]:
        return {
            "sourceRefId": source.source_ref_id,
            "title": source.title,
            "documentId": source.document_id,
            "versionId": source.version_id,
            "releaseId": source.release_id,
            "chunkId": source.chunk_id,
            "sourcePath": source.source_path,
            "sourceType": source.source_type,
            "originalAssetAvailable": source.original_asset_available,
            "originalAssetName": source.original_asset_name,
            "traceStatus": source.trace_status,
            "mappingStatus": source.mapping_status,
        }

    def preview_payload(self, source: ResolvedSource) -> dict[str, Any]:
        payload = self.reference_payload(source)
        content = source.content or ""
        excerpt_limit = 2400

        # Traditional Chinese copy for all user-facing statuses
        if source.mapping_status == MappingStatus.EDITED_DERIVATIVE.value:
            message = "此文件為手動編輯之衍生版本，與原始附件存在差異。"
        elif source.mapping_status == MappingStatus.ORIGINAL_NOT_PRESERVED.value:
            message = "原始檔尚未保存，目前顯示發布時使用的轉換內容。"
        elif source.mapping_status == MappingStatus.SOURCE_MISSING.value:
            message = "此歷史版本之原始檔案或段落已不存在，無法提供原檔。"
        elif source.mapping_status == MappingStatus.LEGACY_UNVERIFIED.value:
            message = "舊版引用尚未核對精準版本，標記為未確認歷史來源。"
        elif source.original_asset_available:
            message = "此來源可開啟原始檔。"
        else:
            message = "目前顯示發布時使用的轉換內容。"

        locator_dict = None
        if hasattr(source.locator, "model_dump"):
            locator_dict = source.locator.model_dump(mode="json")
        elif isinstance(source.locator, dict):
            locator_dict = source.locator

        payload.update(
            {
                "mappingStatus": source.mapping_status,
                "locator": locator_dict,
                "evidence": {
                    "excerpt": content[:excerpt_limit],
                    "truncated": len(content) > excerpt_limit,
                },
                "actions": {
                    "canDownloadOriginal": bool(
                        source.original_asset_available
                        and source.mapping_status != MappingStatus.SOURCE_MISSING.value
                    ),
                    "canViewEvidence": bool(content),
                    "nextSteps": (
                        "可補上經核對之同版原始檔以恢復完整追溯。"
                        if source.mapping_status == MappingStatus.ORIGINAL_NOT_PRESERVED.value
                        else "若需調閱已封存或遺失之原檔，請聯絡管理員。"
                        if source.mapping_status == MappingStatus.SOURCE_MISSING.value
                        else "點擊開啟原檔檢視。"
                    ),
                },
                "message": message,
            }
        )
        return payload
