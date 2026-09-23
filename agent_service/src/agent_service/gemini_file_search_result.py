"""KnowledgeResult assembly helpers for Gemini File Search responses."""

from __future__ import annotations

from collections.abc import Callable

from .contracts import (
    EVALUATION_EVIDENCE_CHANNEL,
    AgentImage,
    AgentRequest,
    Citation,
    GroundedClaim,
    KnowledgeResult,
    RetrievalAttempt,
    RetrievalCandidate,
    RetrievalTrace,
)
from .execution_context import ExecutionContext
from .file_search_registry import FileSearchDocumentRegistry
from .gemini_file_search_grounding import GeminiGroundingChunk
from .source_refs import make_source_ref_id, safe_source_path

TitleResolver = Callable[[str], str]


def limit_result(terminal_reason: str) -> KnowledgeResult:
    return KnowledgeResult(
        found=False,
        answer="",
        sources=[],
        images=[],
        backend="GEMINI_FILE_SEARCH",
        terminalReason=terminal_reason,
    )


def empty_miss_result() -> KnowledgeResult:
    return KnowledgeResult(
        found=False,
        answer="",
        sources=[],
        images=[],
        backend="GEMINI_FILE_SEARCH",
    )


def images_for(
    chunks: list[GeminiGroundingChunk],
    *,
    registry: FileSearchDocumentRegistry | None,
    max_images: int,
) -> list[AgentImage]:
    """Images for the cited documents, via the local registry join."""
    if registry is None:
        return []
    images: list[AgentImage] = []
    seen: set[str] = set()
    seen_slugs: set[str] = set()
    for chunk in chunks:
        slug = chunk.title
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        for image in registry.images_for(slug):
            if image.path in seen:
                continue
            seen.add(image.path)
            images.append(image)
            if len(images) >= max_images:
                return images
    return images


def citations_from_chunks(
    chunks: list[GeminiGroundingChunk],
    *,
    registry: FileSearchDocumentRegistry | None,
    resolve_title: TitleResolver,
    request: AgentRequest | None,
) -> list[Citation]:
    sources: list[Citation] = []
    seen_documents: set[str] = set()
    include_retrieval_evidence = (
        request is not None and request.channel == EVALUATION_EVIDENCE_CHANNEL
    )
    for chunk in chunks:
        identity = registry.source_identity_for(chunk.title) if registry is not None else None
        raw_source_path = identity.source_path if identity is not None else None
        source_path = safe_source_path(raw_source_path)
        if source_path == "[REDACTED_SOURCE]":
            source_path = None
        document_key = (
            (identity.document_id if identity is not None else None)
            or source_path
            or chunk.title
            or chunk.document_name
            or ""
        ).strip()
        if document_key and document_key in seen_documents:
            continue
        if document_key:
            seen_documents.add(document_key)
        source_ref_id = (
            make_source_ref_id(
                release_id=identity.release_id,
                document_id=identity.document_id,
                version_id=identity.version_id,
                chunk_id=identity.chunk_id,
                source_path=source_path,
            )
            if identity is not None and identity.release_id
            else None
        )
        chunk_id = identity.chunk_id if identity is not None else chunk.document_name or chunk.title
        evidence = None
        if include_retrieval_evidence:
            evidence = (
                f"[chunkId={chunk_id}]\n{chunk.text}" if chunk_id and chunk.text else chunk.text
            )
        sources.append(
            Citation(
                title=resolve_title(chunk.title),
                url=None if source_ref_id else chunk.uri,
                chunkId=chunk_id,
                sourceRefId=source_ref_id,
                canonicalSourceId=(identity.document_id if identity is not None else None),
                documentId=identity.document_id if identity is not None else None,
                versionId=identity.version_id if identity is not None else None,
                releaseId=identity.release_id if identity is not None else None,
                sourcePath=source_path,
                evidence=evidence,
            )
        )
    return sources


def with_retrieval_trace(
    result: KnowledgeResult,
    *,
    query: str,
    chunks: list[GeminiGroundingChunk],
    request: AgentRequest | None,
    execution_context: ExecutionContext | None,
    decision: str,
    terminal_reason: str | None,
    registry: FileSearchDocumentRegistry | None,
    resolve_title: TitleResolver,
) -> KnowledgeResult:
    candidates: list[RetrievalCandidate] = []
    for rank, chunk in enumerate(chunks, start=1):
        identity = registry.source_identity_for(chunk.title) if registry is not None else None
        chunk_id = identity.chunk_id if identity is not None else chunk.document_name or chunk.title
        candidates.append(
            RetrievalCandidate(
                rank=rank,
                chunkId=chunk_id,
                documentId=identity.document_id if identity is not None else None,
                canonicalSourceId=(identity.document_id if identity is not None else None),
                title=resolve_title(chunk.title),
                scoreOrigin="PROVIDER_UNAVAILABLE",
            )
        )
    selected_backend = (
        execution_context.selected_knowledge_backend
        if execution_context is not None
        else "GEMINI_FILE_SEARCH"
    )
    trace = RetrievalTrace(
        rawUserUtterance=request.message.text if request is not None else query,
        resolvedIssueQuery=query,
        searchQuery=query,
        facetQueries=[],
        selectedBackend=selected_backend or "GEMINI_FILE_SEARCH",
        actualBackend="GEMINI_FILE_SEARCH",
        attempts=[
            RetrievalAttempt(
                searchQuery=query,
                candidates=candidates,
                decision=decision,
                isRelevant=result.found,
            )
        ],
        selectedChunkIds=[source.chunkId for source in result.sources if source.chunkId],
        answerability=result.answerability,
        claims=result.claims,
        unknowns=result.unknowns,
        fallbackPath=decision,
        terminalReason=terminal_reason,
    )
    return result.model_copy(
        update={
            "terminalReason": terminal_reason,
            "retrievalTrace": trace,
        }
    )


def grounded_answer_result(
    *,
    answer: str,
    sources: list[Citation],
    images: list[AgentImage],
) -> KnowledgeResult:
    return KnowledgeResult(
        found=True,
        answer=answer,
        sources=sources,
        images=images,
        backend="GEMINI_FILE_SEARCH",
        answerability="FULL",
        claims=[
            GroundedClaim(
                text=answer,
                chunkIds=[source.chunkId for source in sources if source.chunkId],
            )
        ],
        unknowns=[],
    )
