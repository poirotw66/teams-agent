"""Document listing, upload, and delete use cases for the workbench."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_ops_backoffice.adapters.workbench_json_store import build_portal_upload_body

_TITLE_EXCLUSIONS = ("測試", "Untitled", "Agent Sync", "[UX-AUDIT]", "簡報講者", "活動簡章")
_IMPORT_PATHS = {
    ".pdf": "documents/import-pdf",
    ".docx": "documents/import-docx",
    ".md": "documents/import-markdown",
    ".markdown": "documents/import-markdown",
}
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class DocumentOperationError(Exception):
    """Domain error mapped to an HTTP status by the router."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _chunk_item_from_raw(chunk: dict[str, Any]) -> dict[str, Any]:
    raw_content = chunk.get("content", "")
    clean_content = raw_content.replace("## 正文（canonical）\n\n", "").strip()
    preview = (clean_content[:140] + "...") if len(clean_content) > 140 else clean_content
    return {
        "id": chunk.get("chunk_id", ""),
        "title": chunk.get("title", ""),
        "content_preview": preview,
        "content": clean_content,
        "character_count": len(clean_content),
        "page_number": chunk.get("page"),
        "source_path": chunk.get("source_path", ""),
    }


def _document_id_from_chunk(chunk: dict[str, Any]) -> str | None:
    doc_id_val = chunk.get("document_id")
    if doc_id_val:
        return str(doc_id_val)
    chunk_id = chunk.get("chunk_id", "")
    if chunk_id.startswith("chk-doc-"):
        parts = chunk_id.split("-")
        if len(parts) >= 3:
            return f"{parts[1]}-{parts[2]}"
    return None


def _build_chunk_indexes(
    all_chunks: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    chunk_by_doc_id: dict[str, list[dict[str, Any]]] = {}
    chunk_by_doc_title: dict[str, list[dict[str, Any]]] = {}
    for chunk in all_chunks:
        chunk_item = _chunk_item_from_raw(chunk)
        doc_id_val = _document_id_from_chunk(chunk)
        if doc_id_val:
            chunk_by_doc_id.setdefault(doc_id_val, []).append(chunk_item)
        chunk_by_doc_title.setdefault(chunk.get("title", ""), []).append(chunk_item)
    return chunk_by_doc_id, chunk_by_doc_title


def _match_chunks_for_document(
    *,
    doc_id: str,
    title: str,
    chunk_by_doc_id: dict[str, list[dict[str, Any]]],
    chunk_by_doc_title: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    doc_chunks = chunk_by_doc_id.get(doc_id) or []
    if doc_chunks:
        return list(doc_chunks)
    doc_chunks = chunk_by_doc_title.get(title) or []
    if doc_chunks:
        return list(doc_chunks)
    matched: list[dict[str, Any]] = []
    for chunk_title, chunk_list in chunk_by_doc_title.items():
        if chunk_title.startswith(f"{title} -") or chunk_title == title:
            matched.extend(chunk_list)
    if matched:
        return matched
    for chunk_title, chunk_list in chunk_by_doc_title.items():
        if chunk_title in title or title in chunk_title:
            return list(chunk_list)
    return []


def _chunks_from_canonical(doc: dict[str, Any], version_map: dict[str, Any]) -> list[dict[str, Any]]:
    version_id = doc.get("current_published_version_id")
    version = version_map.get(version_id, {})
    canonical = version.get("canonical_content", "")
    if not canonical:
        return []
    if canonical.startswith("---"):
        parts = canonical.split("---", 2)
        if len(parts) >= 3:
            canonical = parts[2].strip()
    sections = [section.strip() for section in canonical.split("\n## ") if section.strip()]
    if not sections:
        return []
    title = doc.get("title", "").strip()
    doc_chunks: list[dict[str, Any]] = []
    for section_idx, section in enumerate(sections, 1):
        section_lines = section.splitlines()
        section_title = (
            section_lines[0].replace("#", "").strip() if section_lines else f"段落 #{section_idx}"
        )
        section_body = "\n".join(section_lines[1:]).strip() if len(section_lines) > 1 else section
        if not section_body:
            section_body = section
        preview = (section_body[:140] + "...") if len(section_body) > 140 else section_body
        doc_chunks.append(
            {
                "id": f"chk-{doc.get('document_id')}-{section_idx}",
                "title": section_title or title,
                "content_preview": preview,
                "content": section_body,
                "character_count": len(section_body),
                "page_number": section_idx,
            }
        )
    return doc_chunks


def _fallback_chunk(doc: dict[str, Any], title: str) -> list[dict[str, Any]]:
    summary_text = doc.get("summary") or "標準作業流程指引說明..."
    return [
        {
            "id": f"chk-{doc.get('document_id')}-1",
            "title": f"{title} - 標準程序",
            "content_preview": summary_text,
            "content": summary_text,
            "character_count": len(summary_text),
        }
    ]


def _infer_category(title: str) -> str:
    if "VPN" in title or "FortiClient" in title:
        return "網路通訊"
    if any(key in title for key in ["密碼", "帳號", "AD", "Gitlab", "CTeam", "OTP"]):
        return "帳號安全"
    if "Outlook" in title or "郵件" in title:
        return "電子郵件"
    if "Webex" in title or "話機" in title:
        return "通訊協作"
    if any(key in title for key in ["大州", "樹精靈", "XQ", "超音樹", "艾揚", "CRM"]):
        return "業務交易系統"
    if "手冊" in title or "通報" in title:
        return "IT服務指引"
    if "公槽" in title:
        return "檔案權限"
    if "座位" in title:
        return "總務硬體"
    return "辦公系統"


def _should_include_document(doc: dict[str, Any], seen_titles: set[str]) -> str | None:
    if doc.get("status") not in ("PUBLISHED", "ARCHIVED"):
        return None
    title = doc.get("title", "").strip()
    if not title or any(bad in title for bad in _TITLE_EXCLUSIONS):
        return None
    if title in seen_titles:
        return None
    return title


def _build_chunk_count_indexes(
    all_chunks: list[dict[str, Any]],
) -> tuple[dict[str, int], dict[str, int]]:
    """Count chunks per document without retaining full chunk payloads."""
    count_by_doc_id: dict[str, int] = {}
    count_by_doc_title: dict[str, int] = {}
    for chunk in all_chunks:
        doc_id_val = _document_id_from_chunk(chunk)
        if doc_id_val:
            count_by_doc_id[doc_id_val] = count_by_doc_id.get(doc_id_val, 0) + 1
        title = str(chunk.get("title", "") or "")
        if title:
            count_by_doc_title[title] = count_by_doc_title.get(title, 0) + 1
    return count_by_doc_id, count_by_doc_title


def _match_chunk_count_for_document(
    *,
    doc_id: str,
    title: str,
    count_by_doc_id: dict[str, int],
    count_by_doc_title: dict[str, int],
) -> int:
    if doc_id in count_by_doc_id:
        return count_by_doc_id[doc_id]
    if title in count_by_doc_title:
        return count_by_doc_title[title]
    matched = 0
    for chunk_title, count in count_by_doc_title.items():
        if chunk_title.startswith(f"{title} -") or chunk_title == title:
            matched += count
    if matched:
        return matched
    for chunk_title, count in count_by_doc_title.items():
        if chunk_title in title or title in chunk_title:
            return count
    return 0


def list_workbench_documents(
    *,
    portal_data: dict[str, Any],
    all_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate published portal documents with matched chunk counts.

    List responses intentionally omit full chunk payloads so Knowledge page
    loads stay fast; chunk bodies are loaded on demand via preview APIs.
    """
    if "documents" not in portal_data:
        return []

    count_by_doc_id, count_by_doc_title = _build_chunk_count_indexes(all_chunks)
    version_map = {version["version_id"]: version for version in portal_data.get("versions", [])}
    results: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for doc in portal_data.get("documents", []):
        title = _should_include_document(doc, seen_titles)
        if title is None:
            continue
        seen_titles.add(title)
        doc_id = doc.get("document_id", "")
        chunk_count = _match_chunk_count_for_document(
            doc_id=doc_id,
            title=title,
            count_by_doc_id=count_by_doc_id,
            count_by_doc_title=count_by_doc_title,
        )
        if chunk_count <= 0:
            canonical = _chunks_from_canonical(doc, version_map)
            chunk_count = len(canonical) if canonical else 1

        doc_format = doc.get("format") or "md"
        results.append(
            {
                "id": doc.get("document_id", ""),
                "title": title,
                "file_name": f"{title}.{doc_format}",
                "file_size_bytes": int(doc.get("byte_size") or 0),
                "category": _infer_category(title),
                "version": str(doc.get("current_published_version_id") or "v1.0")[:12],
                "status": "LIVE" if doc.get("status") == "PUBLISHED" else "ARCHIVED",
                "updated_at": str(doc.get("updated_at", ""))[:10],
                "updated_by": doc.get("updated_by", "資訊處知識中心"),
                "chunk_count": chunk_count,
                "chunks": [],
            }
        )
    return results


def _validate_upload_bytes(file_bytes: bytes) -> None:
    if not file_bytes:
        raise DocumentOperationError(400, "上傳檔案內容不能為空。")
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise DocumentOperationError(400, "檔案大小超過 50MB 限制。")


def _import_path_for_filename(filename: str) -> tuple[str, str]:
    extension = Path(filename).suffix.lower()
    import_path = _IMPORT_PATHS.get(extension)
    if import_path is None:
        raise DocumentOperationError(400, "僅支援 PDF、DOCX 與 Markdown。")
    return extension, import_path


def _async_import_response(
    *,
    imported: dict[str, Any],
    actor: Any,
    file_bytes: bytes,
    safe_filename: str,
    title: str,
    category: str,
    version: str,
) -> tuple[int, dict[str, Any]]:
    return 202, {
        "id": imported.get("jobId"),
        "job_id": imported.get("jobId"),
        "title": title.strip() or Path(safe_filename).stem,
        "file_name": safe_filename,
        "file_size_bytes": len(file_bytes),
        "category": category.strip() or "辦公系統",
        "version": version.strip() or "v1.0",
        "status": "PARSING",
        "ingestion_stage": "UPLOADED",
        "updated_at": datetime.now(UTC).date().isoformat(),
        "updated_by": actor.user_id,
        "chunk_count": 0,
        "chunks": [],
    }


def _draft_create_payload(
    *,
    imported: dict[str, Any],
    safe_filename: str,
    title: str,
    category: str,
    version: str,
    extension: str,
) -> dict[str, Any]:
    return {
        "title": title.strip() or str(imported.get("title") or Path(safe_filename).stem),
        "summary": "",
        "category": category.strip() or "辦公系統",
        "owner_unit_id": imported.get("owner_unit_id") or "IT Service Desk",
        "business_contact": "",
        "audience_type": imported.get("audience_type") or "ALL_EMPLOYEES",
        "audience_group_ids": imported.get("audience_group_ids") or [],
        "effective_at": imported.get("effective_at"),
        "review_due_at": imported.get("review_due_at"),
        "change_summary": f"Imported as {version.strip() or 'v1.0'}",
        "change_reason": "Uploaded through the operations workbench for governed review.",
        "markdown_content": imported.get("markdown_content"),
        "source_type": imported.get("source_type")
        or ("DOCX" if extension == ".docx" else "MARKDOWN_UPLOAD"),
        "assets": imported.get("assets") or [],
        "original_asset_token": imported.get("original_asset_token"),
    }


def _draft_created_response(
    *,
    detail: dict[str, Any],
    actor: Any,
    file_bytes: bytes,
    safe_filename: str,
    category: str,
    version: str,
) -> tuple[int, dict[str, Any]]:
    document = detail["document"]
    draft = detail.get("draft_version") or {}
    return 202, {
        "id": document["document_id"],
        "title": document["title"],
        "file_name": draft.get("original_asset_name") or safe_filename,
        "file_size_bytes": draft.get("original_asset_size") or len(file_bytes),
        "category": document.get("category") or category,
        "version": version.strip() or "v1.0",
        "status": "CHUNK_REVIEW",
        "ingestion_stage": "CHUNK_REVIEW",
        "updated_at": str(document.get("updated_at") or "")[:10],
        "updated_by": document.get("updated_by") or actor.user_id,
        "chunk_count": 0,
        "chunks": [],
    }


async def upload_workbench_document(
    *,
    knowledge_client: Any,
    actor: Any,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    title: str,
    category: str,
    version: str,
) -> tuple[int, dict[str, Any]]:
    """Create a governed Portal ingestion draft; returns (status_code, body)."""
    if not knowledge_client.configured:
        raise DocumentOperationError(503, "知識服務整合尚未啟用。")
    _validate_upload_bytes(file_bytes)
    safe_filename = Path(filename or "document.pdf").name
    extension, import_path = _import_path_for_filename(safe_filename)
    upload_body, multipart_type = build_portal_upload_body(
        filename=safe_filename,
        payload=file_bytes,
        content_type=content_type or "application/octet-stream",
    )
    correlation_id = uuid.uuid4().hex
    idempotency = hashlib.sha256(file_bytes).hexdigest()
    upstream = await knowledge_client.request(
        method="POST",
        relative_path=import_path,
        actor=actor,
        correlation_id=correlation_id,
        query={"async_mode": "async"} if extension == ".pdf" else None,
        content=upload_body,
        content_type=multipart_type,
        headers={"Idempotency-Key": idempotency},
    )
    if upstream.status_code >= 400:
        raise DocumentOperationError(upstream.status_code, "文件 ingestion 工作建立失敗。")

    imported = upstream.json()
    if imported.get("mode") == "async":
        return _async_import_response(
            imported=imported,
            actor=actor,
            file_bytes=file_bytes,
            safe_filename=safe_filename,
            title=title,
            category=category,
            version=version,
        )

    created = await knowledge_client.request(
        method="POST",
        relative_path="documents",
        actor=actor,
        correlation_id=correlation_id,
        json_body=_draft_create_payload(
            imported=imported,
            safe_filename=safe_filename,
            title=title,
            category=category,
            version=version,
            extension=extension,
        ),
        headers={"Idempotency-Key": idempotency},
    )
    if created.status_code >= 400:
        raise DocumentOperationError(created.status_code, "文件草稿建立失敗。")
    return _draft_created_response(
        detail=created.json(),
        actor=actor,
        file_bytes=file_bytes,
        safe_filename=safe_filename,
        category=category,
        version=version,
    )


async def delete_workbench_document(
    *,
    knowledge_client: Any,
    actor: Any,
    document_id: str,
) -> dict[str, Any]:
    """Request governed Portal removal for a document."""
    upstream = await knowledge_client.request(
        method="DELETE",
        relative_path=f"documents/{document_id}",
        actor=actor,
        correlation_id=uuid.uuid4().hex,
        query={"reason": "Removed through the operations workbench."},
    )
    if upstream.status_code >= 400:
        raise DocumentOperationError(upstream.status_code, "知識文件移除失敗。")
    return {
        "ok": True,
        "deleted_document_id": document_id,
        "message": "知識文件已進入受控移除流程。",
    }
