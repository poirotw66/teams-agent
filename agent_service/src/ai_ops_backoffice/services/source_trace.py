"""Resolve answer citations to a release-scoped, authorized source preview."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from agent_service.source_refs import (
    ResolvedSource,
    _find_manifest_entry,
    _manifest_by_key,
    _original_asset_path,
    make_source_ref_id,
    safe_source_path,
    source_path_stem,
)

_SAFE_RELEASE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_SOURCE_EVENTS = frozenset({"knowledge.retrieved", "knowledge.answered"})


class SourceTraceResolver:
    """Read-only resolver over private local release artifacts.

    The resolver never returns a filesystem path.  It exposes only stable IDs
    and derived evidence through the backoffice API after capability checks.
    A future GCS-backed implementation can keep the same interface.
    """

    def __init__(self, releases_dir: Path) -> None:
        self.releases_dir = releases_dir.expanduser().resolve()

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

    def _load_release(self, release_id: str) -> tuple[Path, list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]] | None:
        if not _SAFE_RELEASE_ID.fullmatch(release_id):
            return None
        release_root = (self.releases_dir / release_id).resolve()
        try:
            release_root.relative_to(self.releases_dir)
        except ValueError:
            return None
        index_path = release_root / "index" / "chunks.json"
        if not index_path.is_file():
            return None
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        chunks = [item for item in payload.get("chunks", []) if isinstance(item, dict)]
        by_id, by_title = _manifest_by_key(release_root)
        return release_root, chunks, by_id, by_title

    @staticmethod
    def _citation_values(citation: dict[str, Any]) -> tuple[str | None, ...]:
        return tuple(
            str(citation.get(key)) if citation.get(key) else None
            for key in (
                "sourceRefId",
                "documentId",
                "versionId",
                "releaseId",
                "chunkId",
                "sourcePath",
                "title",
            )
        )

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
        source_path = safe_source_path(citation.get("sourcePath"))
        if source_path and source_path != "[REDACTED_SOURCE]":
            for chunk in chunks:
                if safe_source_path(chunk.get("source_path")) == source_path:
                    return chunk
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

    def resolve_citation(
        self,
        citation: dict[str, Any],
        *,
        fallback_release_id: str | None = None,
    ) -> ResolvedSource | None:
        if not isinstance(citation, dict):
            return None
        explicit_ref = str(citation.get("sourceRefId") or "") or None
        preferred_release = str(
            citation.get("releaseId") or fallback_release_id or ""
        ) or None

        for release_id in self._release_ids(preferred_release):
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
                document_id=(str(citation.get("documentId")) if citation.get("documentId") else None),
                by_id=by_id,
                by_title=by_title,
            )
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            document_id = str(
                citation.get("documentId")
                or chunk.get("document_id")
                or (entry or {}).get("document_id")
                or (entry or {}).get("documentId")
                or (source_path_stem(chunk_source_path) or "")
            ) or None
            version_id = str(
                citation.get("versionId")
                or chunk.get("version_id")
                or (entry or {}).get("version_id")
                or (entry or {}).get("versionId")
                or ""
            ) or None
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
                "PDF" if original_path and original_path.suffix.lower() == ".pdf" else "DERIVED_MARKDOWN"
            )
            had_complete_identity = all(
                citation.get(key)
                for key in ("sourceRefId", "documentId", "versionId", "releaseId", "sourcePath")
            )
            return ResolvedSource(
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
            )

        return None

    def resolve_source_ref(self, source_ref_id: str) -> ResolvedSource | None:
        if not source_ref_id or not re.fullmatch(r"src-[0-9a-f]{24}", source_ref_id):
            return None
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
                return self.resolve_citation(
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
                )
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
                    fallback_release_id=(str(payload.get("releaseId")) if payload.get("releaseId") else None),
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
        }

    def preview_payload(self, source: ResolvedSource) -> dict[str, Any]:
        payload = self.reference_payload(source)
        content = source.content or ""
        excerpt_limit = 2400
        payload.update(
            {
                "evidence": {
                    "excerpt": content[:excerpt_limit],
                    "truncated": len(content) > excerpt_limit,
                },
                "message": (
                    "原始檔尚未保存，目前顯示發布時使用的轉換內容。"
                    if not source.original_asset_available
                    else "此來源可開啟原始檔。"
                ),
            }
        )
        return payload
