"""Citation and image assembly for HybridKnowledgeService."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_service.contracts import AgentImage, Citation, GroundedClaim, KnowledgeResult
from agent_service.retrieval import SearchResult
from agent_service.source_refs import build_citation_url, make_source_ref_id, safe_source_path


def document_key(result: SearchResult) -> str:
    return (
        (result.chunk.document_id or "").strip()
        or (result.chunk.source_path or "").strip()
        or result.chunk.title.strip()
    )


def retrieval_evidence(results: Sequence[SearchResult]) -> str | None:
    chunks = [
        f"[chunkId={result.chunk.chunk_id}]\n{result.chunk.content}"
        for result in results
        if result.chunk.content
    ]
    return "\n\n".join(chunks) or None


def build_citation(
    result: SearchResult,
    *,
    release_id: str | None,
    source_base_url: str | None,
    evidence_results: Sequence[SearchResult] | None = None,
) -> Citation:
    resolved_release_id = result.chunk.release_id or release_id
    source_ref_id = make_source_ref_id(
        release_id=resolved_release_id,
        document_id=result.chunk.document_id,
        version_id=result.chunk.version_id,
        chunk_id=result.chunk.chunk_id,
        source_path=result.chunk.source_path,
    )
    source_path = safe_source_path(result.chunk.source_path)
    if source_path == "[REDACTED_SOURCE]":
        source_path = None
    url = build_citation_url(
        source_base_url=source_base_url,
        source_path=source_path,
        source_ref_id=source_ref_id,
    )
    page = result.chunk.page if (result.chunk.page or 0) >= 1 else None
    evidence = (
        retrieval_evidence(evidence_results) if evidence_results is not None else None
    )
    return Citation(
        title=result.chunk.title,
        url=url,
        chunkId=result.chunk.chunk_id,
        sourceRefId=source_ref_id,
        canonicalSourceId=result.chunk.document_id,
        sourceAliases=result.chunk.source_aliases,
        documentId=result.chunk.document_id,
        versionId=result.chunk.version_id,
        releaseId=resolved_release_id,
        sourcePath=source_path,
        section=result.chunk.section,
        page=page,
        evidence=evidence,
        sourceType=(
            result.chunk.source_type
            or ("PDF" if result.chunk.original_asset_available else "DERIVED_MARKDOWN")
        ),
        originalAssetAvailable=result.chunk.original_asset_available,
        originalAssetName=result.chunk.original_asset_name,
    )


def unique_citations(
    results: Sequence[SearchResult],
    *,
    citation_for: Callable[..., Citation],
    key_fn: Callable[[SearchResult], str] = document_key,
    include_retrieval_evidence: bool,
) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[str] = set()
    for result in results:
        doc_key = key_fn(result)
        if doc_key in seen:
            continue
        seen.add(doc_key)
        document_results = [
            candidate for candidate in results if key_fn(candidate) == doc_key
        ]
        citations.append(
            citation_for(
                result,
                evidence_results=(document_results if include_retrieval_evidence else None),
            )
        )
    return citations


def collect_images(
    results: Sequence[SearchResult],
    *,
    release_id: str | None,
    max_images: int,
) -> list[AgentImage]:
    images: list[AgentImage] = []
    seen: set[str] = set()
    for result in results:
        for image in result.chunk.images or []:
            if image.path in seen:
                continue
            seen.add(image.path)
            images.append(
                AgentImage(
                    path=image.path,
                    title=image.title,
                    altText=image.alt_text,
                    sourceChunkId=result.chunk.chunk_id,
                    releaseId=result.chunk.release_id or release_id,
                )
            )
            if len(images) >= max_images:
                return images
    return images


def images_for_cited_results(
    cited_results: Sequence[SearchResult],
    *,
    index_chunks: Sequence,
    release_id: str | None,
    max_images: int,
) -> list[AgentImage]:
    """Prefer cited-chunk images; fall back to same-document sibling chunks."""
    images = collect_images(
        cited_results, release_id=release_id, max_images=max_images
    )
    if images:
        return images
    cited_paths = {result.chunk.source_path for result in cited_results}
    if not cited_paths:
        return []
    sibling_results = [
        SearchResult(chunk=chunk, score=0.0, sparse_score=0.0)
        for chunk in index_chunks
        if chunk.source_path in cited_paths and chunk.images
    ]
    return collect_images(sibling_results, release_id=release_id, max_images=max_images)


def deterministic_grounded_answer(
    results: Sequence[SearchResult],
    *,
    include_retrieval_evidence: bool,
    citation_for: Callable[..., Citation],
    images_for: Callable[[Sequence[SearchResult]], list[AgentImage]],
) -> KnowledgeResult:
    selected_results = list(results[:2])
    citations = unique_citations(
        selected_results,
        citation_for=citation_for,
        include_retrieval_evidence=include_retrieval_evidence,
    )
    excerpts = "\n\n".join(
        f"[S{index}] {citation.title}\n{selected_results[index - 1].chunk.content}"
        if index <= len(selected_results)
        else f"[S{index}] {citation.title}"
        for index, citation in enumerate(citations, start=1)
    )
    return KnowledgeResult(
        found=True,
        answer=f"根據內部知識庫找到以下資訊：\n\n{excerpts}",
        sources=citations,
        images=images_for(selected_results),
        backend="HYBRID",
        answerability="FULL",
        claims=[
            GroundedClaim(
                text=result.chunk.content,
                chunkIds=[result.chunk.chunk_id],
            )
            for result in selected_results
        ],
        unknowns=[],
    )


__all__ = [
    "build_citation",
    "collect_images",
    "deterministic_grounded_answer",
    "document_key",
    "images_for_cited_results",
    "retrieval_evidence",
    "unique_citations",
]
