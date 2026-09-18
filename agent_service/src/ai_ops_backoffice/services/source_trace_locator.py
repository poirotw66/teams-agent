"""Chunk matching and multi-format locator builders for source trace."""

from __future__ import annotations

from typing import Any

from knowledge_core.source_identity import safe_source_path

from .source_models import LocatorType, SourceLocator

__all__ = [
    "build_locator",
    "match_chunk",
]


def match_chunk(
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
            chunk for chunk in chunks if safe_source_path(chunk.get("source_path")) == source_path
        ]
        if len(matches) == 1:
            return matches[0]
        return None
    title = str(citation.get("title") or "").casefold()
    if title:
        matches = [chunk for chunk in chunks if str(chunk.get("title") or "").casefold() == title]
        if len(matches) == 1:
            return matches[0]
    return None


def build_locator(
    source_type: str,
    chunk: dict[str, Any],
    entry: dict[str, Any],
    citation: dict[str, Any],
) -> SourceLocator:
    st = (source_type or "").upper()
    if "PDF" in st:
        return _pdf_locator(chunk, citation)
    if any(ext in st for ext in ("DOCX", "PPTX", "WORD", "POWERPOINT", "OFFICE")):
        return _office_locator(chunk, entry, citation)
    if any(ext in st for ext in ("XLSX", "XLS", "CSV", "SPREADSHEET", "EXCEL")):
        return _spreadsheet_locator(chunk, citation)
    if "MARKDOWN" in st or "MD" in st:
        return _markdown_locator(chunk, citation)
    return SourceLocator(
        locator_type=LocatorType.UNSUPPORTED,
        degraded_reason="此檔案格式不支援精準頁面高亮。",
    )


def _pdf_locator(chunk: dict[str, Any], citation: dict[str, Any]) -> SourceLocator:
    raw_idx = (
        chunk.get("page_index")
        if chunk.get("page_index") is not None
        else chunk.get("page")
        if chunk.get("page") is not None
        else citation.get("pageIndex")
    )
    page_idx = int(raw_idx) if raw_idx is not None else None
    page_lbl = chunk.get("page_label") or citation.get("pageLabel")
    bbox = chunk.get("bbox") or citation.get("bbox")
    coord = chunk.get("coordinate_system") or citation.get("coordinateSystem") or "PDF_POINTS_72DPI"
    degraded = None if page_idx is not None else "原檔頁面定位不可用，已顯示段落摘錄。"
    return SourceLocator(
        locator_type=LocatorType.PDF,
        page_index=page_idx,
        page_label=(
            str(page_lbl)
            if page_lbl is not None
            else (str(page_idx + 1) if page_idx is not None else None)
        ),
        bbox=bbox if isinstance(bbox, list) else None,
        coordinate_system=coord,
        degraded_reason=degraded,
    )


def _office_locator(
    chunk: dict[str, Any],
    entry: dict[str, Any],
    citation: dict[str, Any],
) -> SourceLocator:
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


def _spreadsheet_locator(chunk: dict[str, Any], citation: dict[str, Any]) -> SourceLocator:
    sheet = chunk.get("sheet_name") or citation.get("sheetName")
    cell_range = chunk.get("cell_range") or citation.get("cellRange")
    return SourceLocator(
        locator_type=LocatorType.SPREADSHEET,
        sheet_name=str(sheet) if sheet else None,
        cell_range=str(cell_range) if cell_range else None,
        degraded_reason="試算表格式不支援頁面高亮，請依工作表與儲存格範圍檢視。",
    )


def _markdown_locator(chunk: dict[str, Any], citation: dict[str, Any]) -> SourceLocator:
    sec_path = (
        chunk.get("section_path")
        or citation.get("sectionPath")
        or chunk.get("section")
        or chunk.get("heading")
    )
    para_id = chunk.get("paragraph_id") or citation.get("paragraphId")
    return SourceLocator(
        locator_type=LocatorType.MARKDOWN,
        section_path=str(sec_path) if sec_path else None,
        paragraph_id=str(para_id) if para_id else None,
    )
