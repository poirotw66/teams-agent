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
    """One ranked seed plus non-ranked context for generation."""

    seed: SearchResult
    context_chunks: list[DocumentChunk] = field(default_factory=list)

    @property
    def citation_chunk(self) -> DocumentChunk:
        return self.seed.chunk


def materialize_parent_chunk(
    parent_id: str,
    *,
    chunk_by_id: Mapping[str, DocumentChunk],
    seed: DocumentChunk,
) -> DocumentChunk | None:
    """Build a synthetic parent chunk from siblings sharing ``parent_id``.

    Production layout chunking never stores ``parent_id`` as a ``chunk_id``.
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
    """Attach parent/neighbor context without changing ranking list order."""
    if not ranked:
        return []
    expand_limit = len(ranked) if top_seeds <= 0 else min(top_seeds, len(ranked))
    remaining = max(max_context, 0)
    bundles: list[EvidenceBundle] = []
    global_seen = {item.chunk.chunk_id for item in ranked}

    for index, seed in enumerate(ranked):
        context: list[DocumentChunk] = []
        if index < expand_limit and remaining > 0 and chunk_by_id:
            parent_id = seed.chunk.parent_id
            if parent_id and parent_id not in global_seen:
                parent = materialize_parent_chunk(
                    parent_id, chunk_by_id=chunk_by_id, seed=seed.chunk
                )
                if parent is not None:
                    context.append(parent)
                    global_seen.add(parent_id)
                    remaining -= 1
            for neighbor_id in seed.chunk.neighbor_ids or []:
                if remaining <= 0:
                    break
                if neighbor_id in global_seen:
                    continue
                neighbor = chunk_by_id.get(neighbor_id)
                if neighbor is None:
                    continue
                context.append(neighbor)
                global_seen.add(neighbor_id)
                remaining -= 1
        bundles.append(EvidenceBundle(seed=seed, context_chunks=context))
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
        for chunk in bundle.context_chunks:
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
