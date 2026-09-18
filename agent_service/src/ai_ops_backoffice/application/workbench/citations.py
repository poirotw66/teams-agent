"""Citation building for workbench conversation turns."""

from __future__ import annotations

import re
from typing import Any, Protocol

from operations_core.security_policies import SECURITY_POLICIES, known_policy_ids_in_text


class SourceExcerptResolver(Protocol):
    def resolve_source_content_excerpt(
        self,
        source_ref_id: str,
        *,
        max_chars: int = 2400,
    ) -> str | None: ...


def _append_source_ref_citations(
    citations: list[dict[str, Any]],
    seen_keys: set[str],
    turn: dict[str, Any],
    query_service: SourceExcerptResolver,
) -> None:
    for rank_idx, ref in enumerate(turn.get("sourceRefs") or [], 1):
        doc_title = ref.get("title") or ref.get("sourcePath") or "資訊操作手冊依據"
        doc_id = str(ref.get("documentId") or f"doc-{rank_idx}")
        source_ref_id = ref.get("sourceRefId")
        chunk_id = ref.get("chunkId")
        dedupe_key = f"{doc_id}::{chunk_id or ''}::{doc_title}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        preview_url = f"/api/sources/{source_ref_id}" if source_ref_id else None
        download_url = (
            f"/api/sources/{source_ref_id}/file"
            if source_ref_id and ref.get("originalAssetAvailable")
            else None
        )
        content_excerpt = None
        if source_ref_id:
            content_excerpt = query_service.resolve_source_content_excerpt(source_ref_id)

        citations.append(
            {
                "document_id": doc_id,
                "document_title": doc_title,
                "similarity_score": round(ref.get("score", 0.9) * 100)
                if ref.get("score")
                else (92 if rank_idx == 1 else 82),
                "snippet": ref.get("section") or ref.get("snippet") or "正文標準作業程序指引說明",
                "content": content_excerpt,
                "updated_at": "2026-09-10",
                "is_stale": "old" in doc_title.lower()
                or "2024" in doc_title
                or "v1.0" in doc_title,
                "chunk_id": chunk_id,
                "source_ref_id": source_ref_id,
                "source_type": ref.get("sourceType") or "DOCUMENT",
                "source_path": ref.get("sourcePath"),
                "section": ref.get("section"),
                "preview_url": preview_url,
                "download_url": download_url,
            }
        )


def _append_event_citations(
    citations: list[dict[str, Any]],
    seen_keys: set[str],
    turn: dict[str, Any],
) -> None:
    for ev in turn.get("events") or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("eventType") not in ("knowledge.answered", "faq.answered"):
            continue
        payload = ev.get("payload") or {}
        for ev_cite in payload.get("citations") or []:
            if not isinstance(ev_cite, dict):
                continue
            c_title = ev_cite.get("title") or "知識庫依據"
            c_doc_id = str(ev_cite.get("documentId") or f"doc-{len(citations) + 1}")
            c_chunk_id = ev_cite.get("chunkId")
            dedupe_key = f"{c_doc_id}::{c_chunk_id or ''}::{c_title}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            c_ref_id = ev_cite.get("sourceRefId")
            c_source_type = ev_cite.get("sourceType") or "DOCUMENT"
            is_policy = c_source_type == "POLICY_ADVISORY" or bool(
                c_chunk_id and c_chunk_id.startswith("POLICY-SEC-")
            )
            citations.append(
                {
                    "document_id": c_doc_id,
                    "document_title": c_title,
                    "similarity_score": 100 if is_policy else 90,
                    "snippet": ev_cite.get("section") or "條文規範與操作指引",
                    "updated_at": "2026-09-10",
                    "is_stale": False,
                    "chunk_id": c_chunk_id,
                    "source_ref_id": c_ref_id,
                    "source_type": c_source_type,
                    "source_path": ev_cite.get("sourcePath"),
                    "section": ev_cite.get("section"),
                    "preview_url": f"/api/sources/{c_ref_id}" if c_ref_id else None,
                    "download_url": (
                        f"/api/sources/{c_ref_id}/file"
                        if c_ref_id and ev_cite.get("originalAssetAvailable")
                        else None
                    ),
                    "is_policy": is_policy,
                    "policy_id": c_chunk_id if is_policy else None,
                }
            )


def _append_policy_citations(citations: list[dict[str, Any]], ai_text: str) -> None:
    for pol_id in known_policy_ids_in_text(ai_text):
        if any(c.get("policy_id") == pol_id or c.get("chunk_id") == pol_id for c in citations):
            continue
        policy = SECURITY_POLICIES.get(pol_id)
        if not policy:
            continue
        citations.append(
            {
                "document_id": policy.policy_id,
                "document_title": f"{policy.title} ({policy.policy_id})",
                "similarity_score": 100,
                "snippet": policy.summary,
                "content": policy.body,
                "updated_at": "2026-09-10",
                "is_stale": False,
                "chunk_id": policy.policy_id,
                "source_type": "POLICY_ADVISORY",
                "is_policy": True,
                "policy_id": policy.policy_id,
            }
        )


def _append_fallback_text_citations(citations: list[dict[str, Any]], ai_text: str) -> None:
    source_matches = re.finditer(
        r"(?:^|\n)\s*(?:-\s*)?\[(S\d+)\]\s*(?:\[([^\]]+)\]\(([^)]+)\)|([^\n]+))",
        ai_text,
    )
    for s_idx, match in enumerate(source_matches, 1):
        s_tag = match.group(1)
        link_title = match.group(2)
        link_url = match.group(3)
        plain_title = (match.group(4) or "").strip()
        item_title = link_title or plain_title or f"檢索依據 {s_tag}"

        pol_match = re.search(r"POLICY-SEC-\d{3}", item_title)
        pol_id = pol_match.group(0) if pol_match else None
        is_policy = pol_id in SECURITY_POLICIES if pol_id else False
        policy = SECURITY_POLICIES.get(pol_id) if is_policy and pol_id else None

        citations.append(
            {
                "document_id": pol_id if is_policy and pol_id else f"src-{s_idx}",
                "document_title": item_title,
                "similarity_score": 100 if is_policy else (92 if s_idx == 1 else 85),
                "snippet": policy.summary if policy else "知識檢索相關條目",
                "content": policy.body if policy else None,
                "updated_at": "2026-09-10",
                "is_stale": False,
                "chunk_id": pol_id if is_policy else f"chunk-{s_idx}",
                "source_type": "POLICY_ADVISORY" if is_policy else "DOCUMENT",
                "is_policy": is_policy,
                "policy_id": pol_id if is_policy else None,
                "url": link_url,
            }
        )


def build_citations_for_turn(
    turn: dict[str, Any],
    ai_text: str,
    query_service: SourceExcerptResolver,
) -> list[dict[str, Any]]:
    """Build citation payloads for a single conversation turn."""
    citations: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    _append_source_ref_citations(citations, seen_keys, turn, query_service)
    _append_event_citations(citations, seen_keys, turn)
    _append_policy_citations(citations, ai_text)
    if not citations:
        _append_fallback_text_citations(citations, ai_text)
    return citations
