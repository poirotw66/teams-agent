"""Tests for parent/neighbor retrieval expansion (RAG v2.1 P2)."""

from __future__ import annotations

from agent_service.documents import DocumentChunk
from agent_service.retrieval import SearchResult
from agent_service.retrieval_expand import expand_retrieval_context


def _chunk(chunk_id: str, *, parent_id: str | None = None, neighbors: list[str] | None = None) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title="VPN",
        source_path="vpn.md",
        content=chunk_id,
        parent_id=parent_id,
        neighbor_ids=neighbors or [],
    )


def test_expand_appends_parent_and_neighbors() -> None:
    parent = _chunk("parent")
    seed = _chunk("seed", parent_id="parent", neighbors=["n1", "n2"])
    n1 = _chunk("n1")
    n2 = _chunk("n2")
    ranked = [SearchResult(chunk=seed, score=0.9, sparse_score=0.9)]
    expanded = expand_retrieval_context(
        ranked,
        chunk_by_id={"parent": parent, "seed": seed, "n1": n1, "n2": n2},
        top_seeds=1,
        max_extra=3,
    )
    ids = [item.chunk.chunk_id for item in expanded]
    assert ids[0] == "seed"
    assert "parent" in ids
    assert "n1" in ids


def test_expand_skips_missing_lookup() -> None:
    seed = _chunk("seed", parent_id="missing", neighbors=["also-missing"])
    ranked = [SearchResult(chunk=seed, score=0.5, sparse_score=0.5)]
    expanded = expand_retrieval_context(ranked, chunk_by_id={"seed": seed})
    assert [item.chunk.chunk_id for item in expanded] == ["seed"]
