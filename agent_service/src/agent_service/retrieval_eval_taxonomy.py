"""Failure taxonomy for retrieval and Layer-3 answer evaluation.

Layer 2 classifies retrieval ranking misses. Layer 3 must not reuse that
path when Evidence Recall is measured against ``result.answer`` — answer
omissions are not retrieval misses.
"""

from __future__ import annotations

import re
from typing import Protocol

from agent_service.retrieval import SearchResult


class EvidenceCaseView(Protocol):
    expected_found: bool
    expected_documents: list[str] | tuple[str, ...] | None
    expected_source_titles: list[str] | tuple[str, ...] | None
    expected_evidence: object
    expected_version_id: str | None
    expected_release_id: str | None
    query: str


def classify_retrieval_failure(
    case: EvidenceCaseView,
    *,
    evidence_recall_4: float | None,
    candidate_recall_24: float | None,
    top4_chunk_ids: list[str],
    top4_titles: list[str],
    candidates_24: list[SearchResult],
    is_predicted_no_answer: bool,
) -> str:
    """Classify why a Layer-1/2 case failed Evidence Recall@4."""
    if not case.expected_found:
        return "CORRECT_NO_ANSWER" if is_predicted_no_answer else "NO_ANSWER_FALSE_NEGATIVE"
    if is_predicted_no_answer:
        return "NO_ANSWER_FALSE_POSITIVE"

    expected_doc_ids = set(case.expected_documents or ())
    expected_titles = set(case.expected_source_titles or ())
    document_hit_top4 = bool(
        (expected_doc_ids and (expected_doc_ids & set(top4_chunk_ids)))
        or (expected_titles and (expected_titles & set(top4_titles)))
    )

    if not case.expected_evidence:
        return "SUCCESS" if document_hit_top4 else "RETRIEVAL_RECALL_MISS"

    if evidence_recall_4 is not None and evidence_recall_4 >= 1.0:
        return "SUCCESS"

    if candidate_recall_24 is not None and candidate_recall_24 >= 1.0:
        expected_version = getattr(case, "expected_version_id", None) or getattr(
            case, "expected_release_id", None
        )
        if expected_version:
            top_versions = [
                r.chunk.version_id for r in candidates_24[:4] if r.chunk.version_id
            ]
            if top_versions and all(v != expected_version for v in top_versions):
                return "VERSION_CONFUSION"
        return "RANKING_OR_RERANKER_OPPORTUNITY"

    cand_doc_ids = {r.chunk.document_id for r in candidates_24 if r.chunk.document_id}
    cand_titles = {r.chunk.title for r in candidates_24 if r.chunk.title}

    if (expected_doc_ids and (expected_doc_ids & cand_doc_ids)) or (
        expected_titles and (expected_titles & cand_titles)
    ):
        return "WRONG_SECTION_OR_CHUNKING"

    if re.search(r"(?<![\w-])-?\d{3,5}(?![\w-])", case.query):
        return "LEXICON_OR_CODE_MISS"

    return "RETRIEVAL_RECALL_MISS"


def classify_layer3_failure(
    case: EvidenceCaseView,
    *,
    answer_evidence_recall: float | None,
    retrieval_evidence_recall: float | None,
    citation_precision: float,
    found: bool,
    sources_count: int,
    terminal_reason: str | None = None,
) -> str:
    """Classify Layer-3 misses using answer vs retrieval evidence coverage.

    Retrieval may be complete while the generated answer still omits facts.
    Those cases must not be labeled ``RETRIEVAL_RECALL_MISS``.
    """
    if not case.expected_found:
        return "CORRECT_NO_ANSWER" if not found else "NO_ANSWER_FALSE_NEGATIVE"
    if not found:
        reason = (terminal_reason or "").upper()
        if "RELEVANCE" in reason or "REJECT" in reason:
            return "RELEVANCE_MISJUDGE"
        return "NO_ANSWER_FALSE_POSITIVE"

    expected_docs = set(case.expected_documents or ()) | set(
        case.expected_source_titles or ()
    )
    if answer_evidence_recall is not None and answer_evidence_recall >= 1.0:
        if expected_docs and citation_precision < 1.0:
            return "BAD_CITATION"
        return "SUCCESS"

    if not case.expected_evidence:
        return "SUCCESS" if citation_precision >= 1.0 or not expected_docs else "BAD_CITATION"

    if retrieval_evidence_recall is not None and retrieval_evidence_recall >= 1.0:
        return "ANSWER_OMISSION"

    if sources_count <= 0:
        return "EVIDENCE_NOT_PASSED_TO_GENERATOR"

    if retrieval_evidence_recall is not None and retrieval_evidence_recall < 1.0:
        return "EVIDENCE_NOT_PASSED_TO_GENERATOR"

    return "ANSWER_OMISSION"


__all__ = [
    "classify_layer3_failure",
    "classify_retrieval_failure",
]
