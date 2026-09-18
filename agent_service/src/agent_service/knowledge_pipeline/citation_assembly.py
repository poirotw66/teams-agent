"""Pure helpers for citation marker maps and answer finalization."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from agent_service.contracts import GroundedClaim
from agent_service.retrieval import SearchResult


def build_chunk_document_maps(
    results: Sequence[SearchResult],
    *,
    document_key: Callable[[SearchResult], str],
) -> tuple[list[str], list[int], dict[str, str]]:
    """Return unique doc keys, chunk→doc index (1-based), and chunkId→doc key."""
    unique_doc_keys: list[str] = []
    chunk_to_doc_idx: list[int] = []
    document_by_chunk_id: dict[str, str] = {}
    for result in results:
        key = document_key(result)
        if key not in unique_doc_keys:
            unique_doc_keys.append(key)
        chunk_to_doc_idx.append(unique_doc_keys.index(key) + 1)
        document_by_chunk_id[result.chunk.chunk_id] = key
    return unique_doc_keys, chunk_to_doc_idx, document_by_chunk_id


def resolve_doc_key_for_marker(
    marker_num: int,
    *,
    unique_doc_keys: Sequence[str],
    chunk_to_doc_idx: Sequence[int],
    results_len: int,
) -> str | None:
    if 1 <= marker_num <= len(unique_doc_keys):
        return unique_doc_keys[marker_num - 1]
    if 1 <= marker_num <= results_len:
        doc_idx = chunk_to_doc_idx[marker_num - 1]
        return unique_doc_keys[doc_idx - 1]
    return None


def infer_markers_from_claims(
    claims: Sequence[GroundedClaim],
    *,
    document_by_chunk_id: dict[str, str],
    unique_doc_keys: Sequence[str],
) -> list[int]:
    inferred: list[int] = []
    for claim in claims:
        for chunk_id in claim.chunkIds:
            doc_key = document_by_chunk_id.get(chunk_id)
            if doc_key and doc_key in unique_doc_keys:
                doc_idx = list(unique_doc_keys).index(doc_key) + 1
                if doc_idx not in inferred:
                    inferred.append(doc_idx)
    return inferred


def ordered_cited_keys_from_markers(
    raw_markers: Sequence[int],
    *,
    resolve_doc_key: Callable[[int], str | None],
) -> list[str]:
    ordered: list[str] = []
    for marker in raw_markers:
        doc_key = resolve_doc_key(marker)
        if doc_key is not None and doc_key not in ordered:
            ordered.append(doc_key)
    return ordered


def claimed_document_keys(
    claims: Sequence[GroundedClaim],
    *,
    document_by_chunk_id: dict[str, str],
) -> set[str]:
    return {
        document_by_chunk_id[chunk_id]
        for claim in claims
        for chunk_id in claim.chunkIds
        if chunk_id in document_by_chunk_id
    }


def filter_claims_to_doc_keys(
    claims: Sequence[GroundedClaim],
    *,
    allowed_doc_keys: set[str],
    document_by_chunk_id: dict[str, str],
) -> list[GroundedClaim]:
    return [
        claim
        for claim in claims
        if any(
            document_by_chunk_id.get(chunk_id) in allowed_doc_keys
            for chunk_id in claim.chunkIds
        )
    ]


def remap_answer_citation_markers(
    answer: str,
    *,
    ordered_cited_doc_keys: Sequence[str],
    unique_doc_keys: Sequence[str],
    resolve_doc_key: Callable[[int], str | None],
) -> str:
    doc_key_to_final_idx = {
        key: idx for idx, key in enumerate(ordered_cited_doc_keys, start=1)
    }

    def _remap_marker(match: re.Match[str]) -> str:
        value = int(match.group(1))
        doc_key = resolve_doc_key(value)
        if doc_key is None and unique_doc_keys:
            doc_key = unique_doc_keys[0]
        if doc_key is not None and doc_key in doc_key_to_final_idx:
            return f"[S{doc_key_to_final_idx[doc_key]}]"
        return match.group(0)

    normalized = re.sub(r"\[S(\d+)\]", _remap_marker, answer)
    return re.sub(r"(\[S\d+\])\1+", r"\1", normalized)


def answer_has_knowledge_citation(answer: str) -> bool:
    return bool(re.search(r"\[S\d+\]", answer))
