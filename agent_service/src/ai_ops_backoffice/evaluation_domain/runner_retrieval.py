"""Knowledge retrieval helpers and answer-result normalization for evaluation runs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .models import CaseRevision
from .runner_models import TargetManifest

logger = logging.getLogger(__name__)

__all__ = [
    "default_knowledge_retriever",
    "evidence_ids",
    "normalize_token_usage",
    "persona_context",
    "tool_events",
    "unpack_answer_result",
]


def default_knowledge_retriever(
    query: str,
    manifest: TargetManifest,
    case_revision: CaseRevision,
    releases_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Default retriever loading from pinned knowledge release chunks.json if available."""
    if not manifest.knowledge_release_id or not releases_dir:
        return []

    index_path = releases_dir / manifest.knowledge_release_id / "index" / "chunks.json"
    if not index_path.is_file():
        return []

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        chunks = data.get("chunks", [])
    except Exception as e:
        logger.warning("Failed to load chunks from %s: %s", index_path, e)
        return []

    # Simple keyword relevance matching across chunks (supporting words and CJK n-grams)
    query_tokens = [t.lower() for t in query.split() if len(t) > 1]
    cjk_chars = [ch for ch in query if "\u4e00" <= ch <= "\u9fff" or ch.isalnum()]
    for i in range(len(cjk_chars) - 1):
        query_tokens.append("".join(cjk_chars[i : i + 2]).lower())
    if not query_tokens:
        query_tokens = [query.lower()]
    matched_chunks: list[dict[str, Any]] = []

    for chunk in chunks:
        content = str(chunk.get("content", "")).lower()
        title = str(chunk.get("title", "")).lower()
        score = sum(1 for tok in query_tokens if tok in content or tok in title)
        if score > 0:
            matched_chunks.append(
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "title": chunk.get("title"),
                    "source_id": chunk.get("source_id") or chunk.get("source_path"),
                    "source_path": chunk.get("source_path"),
                    "content": chunk.get("content"),
                    "score": float(score),
                }
            )

    matched_chunks.sort(key=lambda c: c["score"], reverse=True)
    top_k = manifest.retriever_config.get("top_k", 5)
    return matched_chunks[:top_k]


def persona_context(manifest: TargetManifest) -> dict[str, Any]:
    if not manifest.persona_fixture_id:
        return {}
    return manifest.retriever_config.get("persona_context", {})


def evidence_ids(retrieved: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(c.get("chunk_id") or c.get("evidence_id") or c.get("source_id"))
        for c in retrieved
        if (c.get("chunk_id") or c.get("evidence_id") or c.get("source_id"))
    )


def tool_events(tool_calls: list[Any]) -> tuple[dict[str, Any], ...]:
    return tuple(
        c.model_dump(mode="json") if hasattr(c, "model_dump") else dict(c) for c in tool_calls
    )


def normalize_token_usage(
    tokens: Any,
    upstream_usage_status: Any,
) -> tuple[int | None, int, str]:
    """Return (actual_tokens, used_tokens, usage_status) from provider token fields."""
    if tokens is None or str(tokens).upper() == "UNKNOWN":
        return None, 0, "UNKNOWN"
    actual_tokens = int(tokens)
    if upstream_usage_status and str(upstream_usage_status).upper() in {
        "ESTIMATED",
        "EXACT",
        "UNKNOWN",
    }:
        return actual_tokens, actual_tokens, str(upstream_usage_status).upper()
    return actual_tokens, actual_tokens, "EXACT"


def unpack_answer_result(
    ans_res: Any,
) -> tuple[Any, Any, Any, list[Any], Any, Any]:
    """Normalize answering adapter return shapes to a common 6-tuple."""
    if isinstance(ans_res, tuple) and len(ans_res) >= 6:
        answer, tokens, cost, raw_tool_calls, provider_req_id, upstream_usage_status = ans_res[:6]
        return (
            answer,
            tokens,
            cost,
            list(raw_tool_calls),
            provider_req_id,
            upstream_usage_status,
        )
    if isinstance(ans_res, tuple) and len(ans_res) == 5:
        answer, tokens, cost, raw_tool_calls, provider_req_id = ans_res
        return answer, tokens, cost, list(raw_tool_calls), provider_req_id, None
    if isinstance(ans_res, tuple) and len(ans_res) == 4:
        answer, tokens, cost, raw_tool_calls = ans_res
        return answer, tokens, cost, list(raw_tool_calls), None, None
    answer, tokens, cost = ans_res[:3]
    return answer, tokens, cost, [], None, None
