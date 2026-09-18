"""Claim alignment, pruning, and KnowledgeResult assembly for generation."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from agent_service.contracts import Citation, KnowledgeResult
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.security_policies import (
    advisories_from_text,
    citations_for_policy_ids,
    policy_ids_in_text,
    split_claims_by_provenance,
)
from agent_service.temporal_claims import sanitize_temporal_claims

from .citation_assembly import (
    answer_has_knowledge_citation,
    claimed_document_keys,
    filter_claims_to_doc_keys,
    remap_answer_citation_markers,
    resolve_doc_key_for_marker,
)
from .grounding import prune_unbacked_sentences_and_citations
from .models import StructuredKnowledgeAnswer
from .policy_overlay import merge_policy_advisories, sanitize_answer_security

logger = logging.getLogger(__name__)


async def align_claims_with_citations(
    host: Any,
    *,
    response: StructuredKnowledgeAnswer,
    answer: str,
    results: list[SearchResult],
    ordered_cited_doc_keys: list[str],
    answer_model: BaseChatModel | None,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[StructuredKnowledgeAnswer, set[str]] | KnowledgeResult:
    document_by_chunk_id = {
        result.chunk.chunk_id: host.document_key(result) for result in results
    }
    claimed_doc_keys = claimed_document_keys(
        response.claims,
        document_by_chunk_id=document_by_chunk_id,
    )
    cited_set = set(ordered_cited_doc_keys)
    common_doc_keys = claimed_doc_keys & cited_set

    if claimed_doc_keys != cited_set and answer_model is not None:
        repaired_claims = await host.repair_claims_with_model(
            answer_model,
            answer=answer,
            results=results,
            counter=counter,
            execution_context=execution_context,
        )
        if repaired_claims:
            response.claims = filter_claims_to_doc_keys(
                repaired_claims,
                allowed_doc_keys=cited_set,
                document_by_chunk_id=document_by_chunk_id,
            )
            claimed_doc_keys = claimed_document_keys(
                response.claims,
                document_by_chunk_id=document_by_chunk_id,
            )
            common_doc_keys = claimed_doc_keys & cited_set

    if not common_doc_keys:
        logger.warning(
            "Knowledge answer rejected: no common doc keys between claims (%s) "
            "and citations (%s)",
            claimed_doc_keys,
            ordered_cited_doc_keys,
        )
        return host.no_answer()

    response.claims = filter_claims_to_doc_keys(
        response.claims,
        allowed_doc_keys=common_doc_keys,
        document_by_chunk_id=document_by_chunk_id,
    )
    return response, common_doc_keys


def _normalize_pruned_answer(
    *,
    answer: str,
    ordered_cited_doc_keys: list[str],
    common_doc_keys: set[str],
    unique_doc_keys: list[str],
    chunk_to_doc_idx: dict[int, int],
    results_len: int,
) -> tuple[str, list[str]]:
    def _resolve_doc_key(marker_num: int) -> str | None:
        return resolve_doc_key_for_marker(
            marker_num,
            unique_doc_keys=unique_doc_keys,
            chunk_to_doc_idx=chunk_to_doc_idx,
            results_len=results_len,
        )

    answer = prune_unbacked_sentences_and_citations(
        answer,
        common_doc_keys,
        _resolve_doc_key,
    )
    ordered_cited_doc_keys = [k for k in ordered_cited_doc_keys if k in common_doc_keys]
    normalized_answer = remap_answer_citation_markers(
        answer,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        unique_doc_keys=unique_doc_keys,
        resolve_doc_key=_resolve_doc_key,
    )
    normalized_answer = sanitize_answer_security(normalized_answer)
    normalized_answer = sanitize_temporal_claims(normalized_answer)
    return normalized_answer, ordered_cited_doc_keys


def _build_answer_sources(
    host: Any,
    *,
    results: list[SearchResult],
    ordered_cited_doc_keys: list[str],
    policy_ids: list[str],
    include_retrieval_evidence: bool,
) -> list[Citation]:
    sources: list[Citation] = []
    for doc_key in ordered_cited_doc_keys:
        document_results = [
            result for result in results if host.document_key(result) == doc_key
        ]
        sources.append(
            host.citation_for(
                document_results[0],
                evidence_results=(
                    document_results if include_retrieval_evidence else None
                ),
            )
        )
    sources.extend(
        citations_for_policy_ids(
            policy_ids,
            include_evidence=include_retrieval_evidence,
        )
    )
    return sources


def assemble_grounded_knowledge_result(
    host: Any,
    *,
    response: StructuredKnowledgeAnswer,
    answer: str,
    results: list[SearchResult],
    ordered_cited_doc_keys: list[str],
    common_doc_keys: set[str],
    unique_doc_keys: list[str],
    chunk_to_doc_idx: dict[int, int],
    include_retrieval_evidence: bool,
) -> KnowledgeResult:
    normalized_answer, ordered_cited_doc_keys = _normalize_pruned_answer(
        answer=answer,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        common_doc_keys=common_doc_keys,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        results_len=len(results),
    )
    knowledge_claims, claim_policy_advisories = split_claims_by_provenance(
        response.claims
    )
    response.claims = knowledge_claims
    policy_advisories = merge_policy_advisories(
        claim_policy_advisories,
        advisories_from_text(normalized_answer),
    )
    policy_ids = list(
        dict.fromkeys(
            policy_id
            for advisory in policy_advisories
            for policy_id in advisory.policyIds
        )
    )
    if not policy_ids:
        policy_ids = policy_ids_in_text(normalized_answer)

    sources = _build_answer_sources(
        host,
        results=results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        policy_ids=policy_ids,
        include_retrieval_evidence=include_retrieval_evidence,
    )
    if not answer_has_knowledge_citation(normalized_answer) or not ordered_cited_doc_keys:
        logger.warning(
            "Knowledge answer rejected after pruning: missing knowledge citations"
        )
        return host.no_answer()

    cited_results = [
        result
        for result in results
        if host.document_key(result) in ordered_cited_doc_keys
    ]
    return KnowledgeResult(
        found=True,
        answer=normalized_answer,
        sources=sources,
        images=host.images_for(cited_results),
        backend="HYBRID",
        answerability=response.answerability,
        claims=response.claims,
        policyAdvisories=policy_advisories,
        unknowns=response.unknowns,
    )


__all__ = [
    "align_claims_with_citations",
    "assemble_grounded_knowledge_result",
]
