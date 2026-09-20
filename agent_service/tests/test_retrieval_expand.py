"""Tests for EvidenceBundle parent/neighbor expansion."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult
from agent_service.retrieval_expand import (
    build_evidence_bundles,
    expand_retrieval_context,
    materialize_parent_chunk,
)


def _chunk(
    chunk_id: str,
    *,
    parent_id: str | None = None,
    neighbors: list[str] | None = None,
    content: str | None = None,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title="t",
        source_path="doc.md",
        content=content or f"body-{chunk_id}",
        parent_id=parent_id,
        neighbor_ids=list(neighbors or []),
        document_id="doc-1",
    )


def _hit(chunk: DocumentChunk, *, score: float = 0.8, final_rank: int = 1) -> SearchResult:
    return SearchResult(
        chunk=chunk,
        score=score,
        sparse_score=score,
        dense_score=score,
        final_rank=final_rank,
    )


def test_materialize_parent_from_production_parent_id() -> None:
    """parent_id is a group key, not a chunk_id — synthesize from siblings."""
    parent_id = "parent-doc-1-1"
    child_a = _chunk("chk-a", parent_id=parent_id, neighbors=["chk-b"], content="step 1")
    child_b = _chunk("chk-b", parent_id=parent_id, neighbors=[], content="step 2")
    chunk_by_id = {"chk-a": child_a, "chk-b": child_b}
    parent = materialize_parent_chunk(parent_id, chunk_by_id=chunk_by_id, seed=child_a)
    assert parent is not None
    assert parent.chunk_id == parent_id
    assert "step 1" in parent.content and "step 2" in parent.content
    assert chunk_by_id.get(parent_id) is None  # never a real index chunk


def test_build_evidence_bundles_keeps_seed_order() -> None:
    parent_id = "parent-doc-1-1"
    seed = _chunk("seed", parent_id=parent_id, neighbors=["n1"])
    sibling = _chunk("sib", parent_id=parent_id, content="parent-sib")
    neighbor = _chunk("n1", content="neighbor-body")
    ranked = [_hit(seed, final_rank=1), _hit(_chunk("other"), score=0.5, final_rank=2)]
    bundles = build_evidence_bundles(
        ranked,
        chunk_by_id={"seed": seed, "sib": sibling, "n1": neighbor, "other": ranked[1].chunk},
    )
    assert [b.seed.chunk.chunk_id for b in bundles] == ["seed", "other"]
    assert bundles[0].citation_chunk.chunk_id == "seed"
    context_ids = [c.chunk_id for c in bundles[0].context_chunks]
    assert parent_id in context_ids
    assert "n1" in context_ids
    assert bundles[1].context_chunks == []


def test_expand_retrieval_context_compat_flattens_without_requiring_parent_chunk() -> None:
    parent_id = "parent-doc-1-1"
    seed = _chunk("seed", parent_id=parent_id, neighbors=["n1"])
    sibling = _chunk("sib", parent_id=parent_id, content="sib")
    neighbor = _chunk("n1")
    expanded = expand_retrieval_context(
        [_hit(seed)],
        chunk_by_id={"seed": seed, "sib": sibling, "n1": neighbor},
    )
    assert expanded[0].chunk.chunk_id == "seed"
    ids = [item.chunk.chunk_id for item in expanded]
    assert parent_id in ids
    assert "n1" in ids
