"""Light RAG v2 retrieval integration checks (spec §40)."""

from __future__ import annotations

import copy

from agent_service.retrieval import HybridIndex
from knowledge_core.contextual_representation import apply_contextual_representation
from knowledge_core.document_models import DocumentChunk, DocumentMetadata


def _chunk(chunk_id: str, title: str, content: str, **kwargs: object) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        title=title,
        source_path=f"{chunk_id}.md",
        content=content,
        metadata=DocumentMetadata(title=title, category="VPN"),
        **kwargs,  # type: ignore[arg-type]
    )


def test_rrf_and_legacy_weighted_both_return_positive_hits() -> None:
    chunks = [
        _chunk("a", "VPN FAQ", "Permission denied (-455)"),
        _chunk("b", "AD unlock", "account locked password reset"),
    ]
    rrf = HybridIndex(list(chunks), fusion_mode="RRF", fusion_candidate_k=10)
    assert rrf.search("Permission denied (-455)", limit=2)
    assert rrf.search(
        "Permission denied (-455)", limit=2, fusion_mode="LEGACY_WEIGHTED"
    )


def test_weighted_constructor_preserves_weighted_mode() -> None:
    chunks = [_chunk("a", "VPN FAQ", "Permission denied (-455)")]
    index = HybridIndex(chunks, fusion_mode="WEIGHTED")
    assert index.fusion_mode == "WEIGHTED"
    assert index.search("Permission denied (-455)", limit=1)


def test_contextual_bm25_prefers_alias_enriched_chunk() -> None:
    plain = _chunk("plain", "Remote access", "use the client to connect")
    rich = _chunk(
        "rich",
        "VPN常見Q&A問答",
        "Permission denied (-455)",
        source_aliases=["FortiClient VPN"],
        heading_path=["登入問題"],
    )
    contextual_rich = apply_contextual_representation(copy.deepcopy(rich))
    index = HybridIndex([plain, contextual_rich], fusion_mode="RRF", fusion_candidate_k=10)
    ranked = index.search("FortiClient VPN (-455)", limit=2)
    assert ranked
    assert ranked[0].chunk.chunk_id == "rich"
