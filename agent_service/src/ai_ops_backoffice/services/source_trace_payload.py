"""Reference and preview payload builders for source trace responses."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from knowledge_core.source_resolution import ResolvedSource

from .source_models import MappingStatus
from .source_trace_release import SOURCE_EVENTS, ReleaseLoad
from .source_trace_resolve import resolve_citation

__all__ = [
    "preview_payload",
    "reference_payload",
    "references_for_events",
]


def references_for_events(
    *,
    releases_dir: Path,
    release_cache: dict[str, tuple[int, int, ReleaseLoad]],
    events: Iterable[Any],
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        if getattr(event, "event_type", None) not in SOURCE_EVENTS:
            continue
        payload = getattr(event, "payload", {}) or {}
        citations = payload.get("citations") or [payload]
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            resolved = resolve_citation(
                releases_dir=releases_dir,
                release_cache=release_cache,
                citation=citation,
                fallback_release_id=(
                    str(payload.get("releaseId")) if payload.get("releaseId") else None
                ),
            )
            if resolved is None or resolved.source_ref_id in seen:
                continue
            seen.add(resolved.source_ref_id)
            references.append(reference_payload(resolved))
    return references


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


def preview_payload(source: ResolvedSource) -> dict[str, Any]:
    payload = reference_payload(source)
    content = source.content or ""
    excerpt_limit = 2400

    # Traditional Chinese copy for all user-facing statuses
    message = _preview_message(source)
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
                    and source.mapping_status
                    not in {
                        MappingStatus.SOURCE_MISSING.value,
                        MappingStatus.LEGACY_UNVERIFIED.value,
                    }
                ),
                "canViewEvidence": bool(content),
                "nextSteps": _preview_next_steps(source),
            },
            "message": message,
        }
    )
    return payload


def _preview_message(source: ResolvedSource) -> str:
    if source.mapping_status == MappingStatus.EDITED_DERIVATIVE.value:
        return "此文件為手動編輯之衍生版本，與原始附件存在差異。"
    if source.mapping_status == MappingStatus.ORIGINAL_NOT_PRESERVED.value:
        return "原始檔尚未保存，目前顯示發布時使用的轉換內容。"
    if source.mapping_status == MappingStatus.SOURCE_MISSING.value:
        return "此歷史版本之原始檔案或段落已不存在，無法提供原檔。"
    if source.mapping_status == MappingStatus.LEGACY_UNVERIFIED.value:
        return "舊版引用尚未核對精準版本，標記為未確認歷史來源。"
    if source.original_asset_available:
        return "此來源可開啟原始檔。"
    return "目前顯示發布時使用的轉換內容。"


def _preview_next_steps(source: ResolvedSource) -> str:
    if source.mapping_status == MappingStatus.ORIGINAL_NOT_PRESERVED.value:
        return "可補上經核對之同版原始檔以恢復完整追溯。"
    if source.mapping_status == MappingStatus.SOURCE_MISSING.value:
        return "若需調閱已封存或遺失之原檔，請聯絡管理員。"
    if source.mapping_status == MappingStatus.LEGACY_UNVERIFIED.value:
        return "身分未確認前不可下載原檔；請先完成版本核對。"
    return "點擊開啟原檔檢視。"
