"""Issue-result payload builders for operational turn events."""

from __future__ import annotations

from typing import Any

from ..contracts import IssueResult
from .emitter_source import safe_source
from .masking import mask_text

ResultPayload = tuple[str, dict[str, Any], object]


def _ticket_payloads(result: IssueResult) -> list[ResultPayload]:
    if result.resultType == "TICKET_CREATED":
        return [("ticket.created", {"ticketId": result.ticketId, "backend": result.backend}, None)]
    if result.resultType == "FAILED" and result.ticketId:
        return [
            (
                "ticket.failed",
                {
                    "error": mask_text(result.error).text if result.error else None,
                    "backend": result.backend,
                },
                None,
            )
        ]
    return []


def _answer_body(result: IssueResult) -> dict[str, Any]:
    body: dict[str, Any] = {"resultType": result.resultType, "backend": result.backend}
    if result.answer:
        answer = mask_text(result.answer)
        body.update(answerMasked=answer.text, answerWasMasked=answer.was_masked)
    return body


def _knowledge_citations(
    result: IssueResult, release_id: str | None,
) -> tuple[list[dict[str, Any]], list[ResultPayload]]:
    citations: list[dict[str, Any]] = []
    events: list[ResultPayload] = []
    for rank, source in enumerate(result.sources, 1):
        # New citations carry the release-manifest identity directly.
        # Keep the URL fallback for FAQ/legacy adapters, but never make
        # a null URL erase an otherwise valid document/chunk identity.
        source_path, derived_document_id = safe_source(source.sourcePath or source.url)
        document_id = source.documentId or derived_document_id
        source_release_id = source.releaseId or release_id
        citation = {
            "rank": rank,
            "title": mask_text(source.title).text,
            "chunkId": mask_text(source.chunkId).text if source.chunkId else None,
            "documentId": document_id,
            "sourcePath": source_path,
            "sourceRefId": source.sourceRefId,
            "versionId": source.versionId,
            "releaseId": source_release_id,
            "section": mask_text(source.section).text if source.section else None,
            "page": source.page,
            "sourceType": source.sourceType,
            "originalAssetAvailable": source.originalAssetAvailable,
            "originalAssetName": (
                mask_text(source.originalAssetName).text
                if source.originalAssetName
                else None
            ),
        }
        citations.append(citation)
        events.append(("knowledge.retrieved", citation, rank))
    return citations, events


def _knowledge_answered_payloads(
    result: IssueResult, release_id: str | None, body: dict[str, Any],
) -> list[ResultPayload]:
    citations, events = _knowledge_citations(result, release_id)
    body.update(citations=citations, releaseId=release_id, sourceCount=len(citations))
    # Retrieval success sample. Latency may be absent; health UI must not
    # treat SUCCESS without elapsedMs as a full latency picture.
    events.append(
        (
            "usage.recorded",
            {
                "component": "knowledge_index",
                "status": "SUCCESS",
                "releaseId": release_id,
                "sourceCount": len(citations),
                "attributionScope": "RETRIEVAL_INDEX",
                "phase": "retrieval",
            },
            "knowledge-index",
        )
    )
    events.append(("knowledge.answered", body, None))
    return events


def _no_knowledge_payloads(result: IssueResult, release_id: str | None) -> list[ResultPayload]:
    return [
        (
            "usage.recorded",
            {
                "component": "knowledge_index",
                "status": "SUCCESS",
                "releaseId": release_id,
                "attributionScope": "RETRIEVAL_INDEX",
                "phase": "retrieval",
                "resultType": "NO_KNOWLEDGE",
                **({"backend": result.backend} if result.backend else {}),
            },
            "knowledge-index-no-knowledge",
        )
    ]


def _knowledge_failed_payloads(result: IssueResult, release_id: str | None) -> list[ResultPayload]:
    if not (
        result.resultType == "FAILED"
        and not result.ticketId
        and result.backend
        and "ticket" not in str(result.backend).lower()
    ):
        return []
    return [
        (
            "usage.recorded",
            {
                "component": "knowledge_index",
                "status": "FAILED",
                "releaseId": release_id,
                "attributionScope": "RETRIEVAL_INDEX",
                "phase": "retrieval",
                "resultType": "FAILED",
                "backend": result.backend,
                **(
                    {"errorType": mask_text(result.error).text}
                    if result.error
                    else {}
                ),
            },
            "knowledge-index-failed",
        )
    ]


def result_payloads(
    result: IssueResult, release_id: str | None,
) -> list[ResultPayload]:
    events = _ticket_payloads(result)
    kind = "answer.completed"
    body = _answer_body(result)
    if result.resultType == "FAQ_ANSWERED":
        kind = "faq.answered"
        body.update(
            faqId=result.faqId,
            faqKey=result.faqKey,
            faqVersionId=result.faqVersionId,
        )
    elif result.resultType == "KNOWLEDGE_ANSWERED":
        return events + _knowledge_answered_payloads(result, release_id, body)
    elif result.resultType == "NO_KNOWLEDGE":
        events.extend(_no_knowledge_payloads(result, release_id))
    else:
        events.extend(_knowledge_failed_payloads(result, release_id))
    events.append((kind, body, None))
    return events
