"""Evidence context expansion after ranking/selection (RAG correctness).

Parent/neighbor expansion must not participate in retrieval ranking. It builds
``EvidenceBundle`` context for the generator from production layout chunks:

- ``parent_id`` is a synthetic group id (``parent-{doc}-{n}``), not a chunk_id
- Parent text is materialised by joining sibling chunks that share ``parent_id``
- Neighbors resolve via ``neighbor_ids`` → real ``chunk_id`` lookups
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult

_DEFAULT_TOP_SEEDS = 3
_DEFAULT_MAX_CONTEXT = 6

__all__ = [
    "EvidenceBundle",
    "build_evidence_bundles",
    "expand_retrieval_context",
    "materialize_parent_chunk",
]


@dataclass(frozen=True)
class EvidenceBundle:
    """One ranked seed plus non-ranked supporting context for generation."""

    seed: SearchResult
    supporting_chunks: list[DocumentChunk] = field(default_factory=list)

    def __init__(
        self,
        seed: SearchResult,
        supporting_chunks: Sequence[DocumentChunk] | None = None,
        *,
        context_chunks: Sequence[DocumentChunk] | None = None,
    ) -> None:
        chunks = (
            supporting_chunks
            if supporting_chunks is not None
            else (context_chunks or [])
        )
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "supporting_chunks", list(chunks))

    @property
    def citation_chunk(self) -> DocumentChunk:
        return self.seed.chunk

    @property
    def context_chunks(self) -> list[DocumentChunk]:
        """Backward-compatibility alias for supporting_chunks."""
        return self.supporting_chunks


def materialize_parent_chunk(
    parent_id: str,
    *,
    chunk_by_id: Mapping[str, DocumentChunk],
    seed: DocumentChunk,
) -> DocumentChunk | None:
    """Build a synthetic parent chunk from siblings sharing ``parent_id``.

    Retained for standalone callers; post-selection ``build_evidence_bundles``
    prefers discrete sibling chunks with provenance over synthetic parents.
    """
    siblings = [
        chunk
        for chunk in chunk_by_id.values()
        if chunk.parent_id == parent_id
    ]
    if not siblings:
        return None
    # Prefer document order via neighbor graph when present; else stable id.
    ordered = _order_siblings(siblings)
    content = "\n\n".join(chunk.content for chunk in ordered if chunk.content.strip())
    if not content.strip():
        return None
    return DocumentChunk(
        chunk_id=parent_id,
        title=seed.title,
        source_path=seed.source_path,
        content=content,
        classification=seed.classification,
        allowed_groups=list(seed.allowed_groups or []) or None,
        document_id=seed.document_id,
        version_id=seed.version_id,
        version_number=seed.version_number,
        release_id=seed.release_id,
        section=seed.section,
        page=min((c.page for c in ordered if c.page is not None), default=seed.page),
        page_end=max(
            (c.page_end or c.page for c in ordered if (c.page_end or c.page) is not None),
            default=seed.page_end,
        ),
        parent_id=None,
        neighbor_ids=[],
        heading_path=list(seed.heading_path or []),
    )


def _order_siblings(siblings: Sequence[DocumentChunk]) -> list[DocumentChunk]:
    by_id = {chunk.chunk_id: chunk for chunk in siblings}
    starts = [
        chunk
        for chunk in siblings
        if not any(
            chunk.chunk_id in (other.neighbor_ids or []) for other in siblings
        )
    ]
    if len(starts) == 1:
        ordered: list[DocumentChunk] = []
        current: DocumentChunk | None = starts[0]
        seen: set[str] = set()
        while current is not None and current.chunk_id not in seen:
            ordered.append(current)
            seen.add(current.chunk_id)
            next_id = next(
                (nid for nid in (current.neighbor_ids or []) if nid in by_id),
                None,
            )
            current = by_id.get(next_id) if next_id else None
        if len(ordered) == len(siblings):
            return ordered
    return sorted(siblings, key=lambda chunk: chunk.chunk_id)


def build_evidence_bundles(
    ranked: Sequence[SearchResult],
    *,
    chunk_by_id: Mapping[str, DocumentChunk],
    top_seeds: int = _DEFAULT_TOP_SEEDS,
    max_context: int = _DEFAULT_MAX_CONTEXT,
) -> list[EvidenceBundle]:
    """Attach supporting sibling/neighbor chunks without synthetic parent duplication."""
    if not ranked:
        return []
    expand_limit = len(ranked) if top_seeds <= 0 else min(top_seeds, len(ranked))
    remaining = max(max_context, 0)
    bundles: list[EvidenceBundle] = []
    global_seen_ids = {item.chunk.chunk_id for item in ranked}
    global_seen_content_hashes = {
        hash(item.chunk.content.strip())
        for item in ranked
        if item.chunk.content and item.chunk.content.strip()
    }

    for index, seed in enumerate(ranked):
        supporting: list[DocumentChunk] = []
        if index < expand_limit and remaining > 0 and chunk_by_id:
            candidate_chunks: list[DocumentChunk] = []
            parent_id = seed.chunk.parent_id
            if parent_id:
                siblings = [
                    chunk
                    for chunk in chunk_by_id.values()
                    if chunk.parent_id == parent_id and chunk.chunk_id != seed.chunk.chunk_id
                ]
                if siblings:
                    candidate_chunks.extend(_order_siblings(siblings))
            for neighbor_id in seed.chunk.neighbor_ids or []:
                neighbor = chunk_by_id.get(neighbor_id)
                if neighbor is not None and neighbor.chunk_id != seed.chunk.chunk_id:
                    candidate_chunks.append(neighbor)

            for cand in candidate_chunks:
                if remaining <= 0:
                    break
                if cand.chunk_id in global_seen_ids:
                    continue
                c_content = cand.content.strip() if cand.content else ""
                if not c_content:
                    continue
                chash = hash(c_content)
                if chash in global_seen_content_hashes:
                    continue
                supporting.append(cand)
                global_seen_ids.add(cand.chunk_id)
                global_seen_content_hashes.add(chash)
                remaining -= 1
        bundles.append(EvidenceBundle(seed=seed, supporting_chunks=supporting))
    return bundles


def expand_retrieval_context(
    ranked: Sequence[SearchResult],
    *,
    chunk_by_id: Mapping[str, DocumentChunk],
    top_seeds: int = _DEFAULT_TOP_SEEDS,
    max_extra: int = _DEFAULT_MAX_CONTEXT,
) -> list[SearchResult]:
    """Deprecated ranking-list expansion.

    Prefer ``build_evidence_bundles`` after document selection. Kept for
    callers that still flatten context into SearchResult rows.
    """
    bundles = build_evidence_bundles(
        ranked,
        chunk_by_id=chunk_by_id,
        top_seeds=top_seeds,
        max_context=max_extra,
    )
    flattened: list[SearchResult] = [bundle.seed for bundle in bundles]
    seen = {item.chunk.chunk_id for item in flattened}
    for bundle in bundles:
        for chunk in bundle.supporting_chunks:
            if chunk.chunk_id in seen:
                continue
            flattened.append(
                SearchResult(
                    chunk=chunk,
                    score=evidence_score_for_context(bundle.seed),
                    sparse_score=bundle.seed.sparse_score,
                    dense_score=bundle.seed.dense_score,
                    fusion_score=bundle.seed.fusion_score,
                    fusion_rank=bundle.seed.fusion_rank,
                    final_rank=None,
                )
            )
            seen.add(chunk.chunk_id)
    return flattened


def evidence_score_for_context(seed: SearchResult) -> float:
    return float(seed.score) * 0.99
