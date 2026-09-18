"""Retrieval helpers for RealRagRetrieverAdapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ai_ops_backoffice.ports.retrieval import get_hybrid_index_factory
from knowledge_core.document_models import DocumentChunk

from .runner_models import TargetManifest

logger = logging.getLogger(__name__)


def load_raw_chunks(
    *,
    manifest: TargetManifest,
    releases_dir: Path | None,
    corpus_provider: Any | None,
) -> list[dict[str, Any]]:
    if manifest.knowledge_release_id and releases_dir:
        rel_dir = releases_dir / manifest.knowledge_release_id
        cand1 = rel_dir / "index" / "chunks.json"
        cand2 = rel_dir / "chunks.json"
        chosen = cand1 if cand1.is_file() else (cand2 if cand2.is_file() else None)
        if chosen:
            try:
                data = json.loads(chosen.read_text(encoding="utf-8"))
                return list(data.get("chunks", []))
            except Exception as exc:
                logger.warning("Failed loading release chunks from %s: %s", chosen, exc)
    elif corpus_provider:
        return list(corpus_provider(manifest.target_id))
    return []


def build_document_chunks(
    raw_chunks: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[DocumentChunk]]:
    chunk_map: dict[str, dict[str, Any]] = {}
    doc_chunks: list[DocumentChunk] = []
    for item in raw_chunks:
        cid = str(item.get("chunk_id", ""))
        chunk_map[cid] = item
        groups = item.get("allowed_groups") or item.get("acl_groups")
        doc_chunks.append(
            DocumentChunk(
                chunk_id=cid,
                title=str(item.get("title", "")),
                source_path=str(item.get("source_path", item.get("source_id", cid))),
                content=str(item.get("content", "")),
                classification=str(item.get("classification", "internal")),
                allowed_groups=list(groups) if groups else None,
                document_id=item.get("document_id") or item.get("source_id"),
                version_id=item.get("version_id"),
                release_id=item.get("release_id"),
                section=item.get("section"),
                page=item.get("page"),
                source_type=item.get("source_type"),
            )
        )
    return chunk_map, doc_chunks


def score_retrieved_chunks(
    *,
    query: str,
    doc_chunks: list[DocumentChunk],
    chunk_map: dict[str, dict[str, Any]],
    user_groups: set[Any],
    acl_policy: str,
    top_k: int,
    min_score: float,
    excluded_sources: set[Any],
    excluded_chunk_ids: set[Any],
) -> list[dict[str, Any]]:
    try:
        hybrid_index = get_hybrid_index_factory().create(doc_chunks)
        if acl_policy == "STRICT":
            search_groups = user_groups
        else:
            search_groups = set(user_groups)
            for chunk in doc_chunks:
                if chunk.allowed_groups:
                    search_groups.update(chunk.allowed_groups)
        search_results = hybrid_index.search(query, top_k * 3, groups=search_groups)
    except Exception as exc:
        logger.warning("HybridIndex search failed: %s", exc)
        return []

    scored_chunks: list[dict[str, Any]] = []
    for res in search_results:
        chunk = res.chunk
        raw = chunk_map.get(chunk.chunk_id, {})
        source_id = str(raw.get("source_id") or chunk.document_id or chunk.source_path)
        if (
            chunk.chunk_id in excluded_chunk_ids
            or source_id in excluded_sources
            or chunk.source_path in excluded_sources
        ):
            continue
        if res.score < min_score:
            continue
        scored_chunks.append(
            {
                "chunk_id": chunk.chunk_id,
                "source_id": source_id,
                "source_path": chunk.source_path,
                "title": chunk.title,
                "content": chunk.content,
                "score": round(res.score, 4),
                "evidence_id": raw.get("evidence_id") or chunk.chunk_id,
            }
        )
        if len(scored_chunks) >= top_k:
            break
    return scored_chunks
