"""Claim alignment, pruning, and KnowledgeResult assembly for generation."""

from __future__ import annotations

import logging
from collections.abc import Sequence
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


def prefer_query_aligned_citations(
    *,
    query: str,
    ordered_cited_doc_keys: Sequence[str],
    results: Sequence[SearchResult],
    document_key: Any,
) -> list[str]:
    """Drop peripheral citations that do not overlap the query anchors.

    Keeps every citation tied for the best overlap score so multi-doc answers
    remain when both sources are on-query.
    """
    keys = [key for key in ordered_cited_doc_keys if key]
    if len(keys) <= 1:
        return list(keys)

    from .generator import query_anchor_tokens

    anchors = query_anchor_tokens(query)
    if not anchors:
        return list(keys)

    def _overlap(doc_key: str) -> int:
        blob_parts: list[str] = []
        for result in results:
            if document_key(result) != doc_key:
                continue
            blob_parts.append(f"{result.chunk.title}\n{result.chunk.content}")
        blob = "\n".join(blob_parts).lower()
        if not blob:
            return 0
        return sum(1 for anchor in anchors if anchor.lower() in blob)

    scored = [(key, _overlap(key)) for key in keys]
    best = max(score for _, score in scored)
    if best <= 0:
        return list(keys[:1])

    positive = [(key, score) for key, score in scored if score > 0]
    multi_topic = ("、" in query) or ("與" in query) or ("及" in query)
    second = max((score for _, score in positive if score < best), default=0)
    if (
        not multi_topic
        and best >= 2
        and second > 0
        and (best - second) >= 2
    ):
        keep = {key for key, score in positive if score == best}
    else:
        keep = {key for key, _score in positive}
    return [key for key in keys if key in keep]


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
    bundles: Sequence[Any] | None = None,
) -> tuple[StructuredKnowledgeAnswer, set[str]] | KnowledgeResult:
    document_by_chunk_id = {
        result.chunk.chunk_id: host.document_key(result) for result in results
    }
    if bundles:
        for bundle in bundles:
            seed_doc_key = host.document_key(bundle.seed)
            for chunk in getattr(bundle, "supporting_chunks", None) or getattr(bundle, "context_chunks", None) or []:
                doc_key = (
                    (chunk.document_id or "").strip()
                    or (chunk.source_path or "").strip()
                    or chunk.title.strip()
                    or seed_doc_key
                )
                document_by_chunk_id.setdefault(chunk.chunk_id, doc_key)
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
    resolved_issue_query: str = "",
) -> KnowledgeResult:
    if resolved_issue_query and len(ordered_cited_doc_keys) > 1:
        aligned_keys = prefer_query_aligned_citations(
            query=resolved_issue_query,
            ordered_cited_doc_keys=ordered_cited_doc_keys,
            results=results,
            document_key=host.document_key,
        )
        if aligned_keys and set(aligned_keys) != set(ordered_cited_doc_keys):
            ordered_cited_doc_keys = aligned_keys
            common_doc_keys = set(aligned_keys) & common_doc_keys
            if not common_doc_keys:
                common_doc_keys = set(aligned_keys)

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
