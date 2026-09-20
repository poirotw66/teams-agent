"""Tests for EvidenceBundle grounding contract (P0-1 regression).

Scenario:
The fact required to answer the question exists ONLY in a neighbor chunk.
- Retrieval returns the correct seed chunk.
- Post-selection expands neighbor into EvidenceBundle.supporting_chunks.
- Generation context includes seed and neighbor under [S1] without duplicating seed.
- LLM uses neighbor fact and cites [S1] (or concrete neighbor chunk_id).
- Claim remapping resolves marker to the supporting neighbor chunk.
- Grounding validator recognizes expanded supporting chunks as valid evidence.
- Citation resolves to the original document.
"""

from __future__ import annotations

import pytest

from agent_service.contracts import Citation, GroundedClaim
from agent_service.documents import DocumentChunk
from agent_service.knowledge_pipeline.generation_stage import (
    build_context_and_markers,
    resolve_cited_document_keys,
)
from agent_service.knowledge_pipeline.generation_stage_result import (
    align_claims_with_citations,
    assemble_grounded_knowledge_result,
)
from agent_service.knowledge_pipeline.grounding import (
    remap_claim_marker_ids_to_chunk_ids,
    structured_answer_is_grounded,
)
from agent_service.knowledge_pipeline.models import StructuredKnowledgeAnswer
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.retrieval_expand import build_evidence_bundles


class _DummyHost:
    def __init__(self, doc_key: str = "doc-forticlient") -> None:
        self._doc_key = doc_key

    def document_key(self, result: SearchResult) -> str:
        return (
            (result.chunk.document_id or "").strip()
            or (result.chunk.source_path or "").strip()
            or self._doc_key
        )

    def citation_for(
        self,
        result: SearchResult,
        *,
        evidence_results: list[SearchResult] | None = None,
    ) -> Citation:
        del evidence_results
        return Citation(
            title=result.chunk.title,
            url=f"https://wiki.corp/{result.chunk.source_path}",
            chunkId=result.chunk.chunk_id,
            sourceRefId="ref-1",
        )

    def images_for(self, cited_results: list[SearchResult]) -> list:
        del cited_results
        return []

    def no_answer(self) -> None:
        return None


@pytest.mark.asyncio
async def test_neighbor_expansion_grounding_and_citation_pass() -> None:
    # 1. Setup seed and neighbor chunks
    seed_chunk = DocumentChunk(
        chunk_id="chk-seed-vpn",
        title="FortiClient 連線異常排除手冊",
        source_path="it/vpn/forticlient.md",
        content="常見異常包含 FortiClient 錯誤碼 -455 與伺服器連線中斷。",
        document_id="doc-forticlient",
        neighbor_ids=["chk-neighbor-vpn"],
    )
    neighbor_chunk = DocumentChunk(
        chunk_id="chk-neighbor-vpn",
        title="FortiClient 連線異常排除手冊",
        source_path="it/vpn/forticlient.md",
        content="針對 -455 錯誤，解法是重新輸入網域密碼並重新建立 VPN 連線。",
        document_id="doc-forticlient",
        neighbor_ids=[],
    )
    chunk_by_id = {
        seed_chunk.chunk_id: seed_chunk,
        neighbor_chunk.chunk_id: neighbor_chunk,
    }

    # 2. Retrieval returns the seed
    seed_result = SearchResult(
        chunk=seed_chunk,
        score=0.88,
        sparse_score=0.85,
        dense_score=0.90,
        final_rank=1,
    )
    retrieval_results = [seed_result]

    # 3. Post-selection EvidenceBundle expansion
    bundles = build_evidence_bundles(
        retrieval_results,
        chunk_by_id=chunk_by_id,
        top_seeds=3,
        max_context=4,
    )
    assert len(bundles) == 1
    assert bundles[0].seed.chunk.chunk_id == "chk-seed-vpn"
    assert len(bundles[0].supporting_chunks) == 1
    assert bundles[0].supporting_chunks[0].chunk_id == "chk-neighbor-vpn"

    # 4. Generation context and marker mapping
    chunk_to_doc_idx = {0: 1}
    context, marker_to_chunk_ids, chunk_content_by_id, returned_bundles = build_context_and_markers(
        retrieval_results,
        chunk_to_doc_idx,
        chunk_by_id=chunk_by_id,
    )
    assert returned_bundles is not None
    # Context contains seed and neighbor
    assert "[S1] FortiClient 連線異常排除手冊" in context
    assert "chk-seed-vpn" in context
    assert "chk-neighbor-vpn" in context
    assert "重新輸入網域密碼並重新建立 VPN 連線" in context
    # Seed content is NOT duplicated in context
    assert context.count("常見異常包含 FortiClient 錯誤碼 -455 與伺服器連線中斷。") == 1

    # Both seed and neighbor IDs are registered under marker S1
    assert "chk-seed-vpn" in marker_to_chunk_ids["S1"]
    assert "chk-neighbor-vpn" in marker_to_chunk_ids["S1"]

    # 5. LLM produces answer citing S1 with fact solely from neighbor
    answer_text = "遇到 FortiClient -455 錯誤時，解法是重新輸入網域密碼並重新建立 VPN 連線 [S1]。"
    claim = GroundedClaim(
        text="針對 -455 錯誤解法是重新輸入網域密碼並重新建立 VPN 連線",
        chunkIds=["S1"],
    )
    structured_answer = StructuredKnowledgeAnswer(
        answerability="FULL",
        answer=answer_text,
        claims=[claim],
        unknowns=[],
    )

    # 6. Remap claim marker IDs
    remapped_claims = remap_claim_marker_ids_to_chunk_ids(
        structured_answer.claims,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    assert len(remapped_claims) == 1
    # Remapped to the neighbor chunk because the content matches neighbor, not seed
    assert "chk-neighbor-vpn" in remapped_claims[0].chunkIds
    structured_answer.claims = remapped_claims

    # 7. Grounding validation MUST pass when bundles are provided, and fail when omitted
    host = _DummyHost("doc-forticlient")
    # Without bundles, supporting chunk is not in seed results, so grounding rejects
    assert (
        structured_answer_is_grounded(
            structured_answer,
            retrieval_results,
            bundles=None,
        )
        is False
    )
    # With bundles, grounding validator recognizes expanded supporting evidence
    assert (
        structured_answer_is_grounded(
            structured_answer,
            retrieval_results,
            bundles=bundles,
        )
        is True
    )

    # 8. Document key and citation resolution
    unique_doc_keys = ["doc-forticlient"]
    cited = resolve_cited_document_keys(
        host=host,
        response=structured_answer,
        answer=answer_text,
        results=retrieval_results,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        bundles=bundles,
    )
    assert cited is not None
    resolved_answer, ordered_cited_doc_keys = cited
    assert ordered_cited_doc_keys == ["doc-forticlient"]

    # 9. Align claims with citations
    counter = LlmCallCounter()
    aligned = await align_claims_with_citations(
        host,
        response=structured_answer,
        answer=resolved_answer,
        results=retrieval_results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        answer_model=None,
        counter=counter,
        execution_context=None,
        bundles=bundles,
    )
    assert aligned is not None
    aligned_response, common_doc_keys = aligned
    assert common_doc_keys == {"doc-forticlient"}
    assert len(aligned_response.claims) == 1
    assert "chk-neighbor-vpn" in aligned_response.claims[0].chunkIds

    # 10. Assemble final KnowledgeResult
    final_result = assemble_grounded_knowledge_result(
        host,
        response=aligned_response,
        answer=resolved_answer,
        results=retrieval_results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        common_doc_keys=common_doc_keys,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        include_retrieval_evidence=False,
    )
    assert final_result.found is True
    assert "[S1]" in final_result.answer
    assert len(final_result.sources) >= 1
    assert final_result.sources[0].chunkId == "chk-seed-vpn"
    assert "forticlient.md" in final_result.sources[0].url
