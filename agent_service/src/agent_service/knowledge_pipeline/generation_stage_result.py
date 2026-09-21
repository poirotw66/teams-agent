"""Claim alignment, pruning, and KnowledgeResult assembly for generation."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel

from agent_service.contracts import Citation, KnowledgeResult, PolicyAdvisory
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
    # Require a clear relative gap before dropping a positive secondary source.
    # Absolute gaps of 2 are common with CJK bigram anchors on near-equal docs.
    clear_gap = second > 0 and second < (best * 0.5) and (best - second) >= 2
    if not multi_topic and best >= 2 and clear_gap:
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
    evidence_text: str = "",
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
    normalized_answer = sanitize_answer_security(
        normalized_answer,
        evidence_text=evidence_text,
    )
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


def _evidence_text_for_docs(
    host: Any,
    *,
    results: list[SearchResult],
    doc_keys: set[str],
) -> str:
    parts: list[str] = []
    for result in results:
        if host.document_key(result) not in doc_keys:
            continue
        parts.append(f"{result.chunk.title}\n{result.chunk.content}")
    return "\n".join(parts)


def drop_ad_unlock_citations_for_product_query(
    *,
    query: str,
    ordered_cited_doc_keys: Sequence[str],
    common_doc_keys: set[str],
    results: Sequence[SearchResult],
    document_key: Any,
) -> tuple[list[str], set[str]]:
    """Drop AD unlock FAQ cites when the query is about another product.

    Short product queries such as「CRM OTP」must not keep the AD self-unlock
    FAQ merely because that FAQ mentions CRM in its system list. AD-oriented
    queries keep those citations.
    """
    keys = [key for key in ordered_cited_doc_keys if key]
    if len(keys) <= 1:
        return list(keys), set(common_doc_keys)

    normalized = query.casefold()
    ad_intent = bool(re.search(r"(?<![a-z0-9])ad(?![a-z0-9])", normalized)) or any(
        token in normalized for token in ("自助解鎖", "帳號鎖定", "網域")
    ) or any(token in query for token in ("鎖定", "被鎖", "解鎖"))
    if ad_intent:
        return list(keys), set(common_doc_keys)

    def _is_ad_unlock_doc(doc_key: str) -> bool:
        for result in results:
            if document_key(result) != doc_key:
                continue
            title = result.chunk.title or ""
            if "AD 帳號與系統解鎖" in title or "AD帳號與系統解鎖" in title:
                return True
        return False

    # Non-AD queries that already cite a product/process doc should not keep the
    # AD self-unlock FAQ as a secondary citation (common precision leak).
    kept = [key for key in keys if not _is_ad_unlock_doc(key)]
    if not kept:
        return list(keys), set(common_doc_keys)
    return kept, {key for key in common_doc_keys if key in kept}


def _apply_product_citation_guards(
    host: Any,
    *,
    response: StructuredKnowledgeAnswer,
    results: list[SearchResult],
    ordered_cited_doc_keys: list[str],
    common_doc_keys: set[str],
    resolved_issue_query: str,
) -> tuple[list[str], set[str]]:
    if not resolved_issue_query or len(ordered_cited_doc_keys) <= 1:
        return ordered_cited_doc_keys, common_doc_keys
    pruned_keys, pruned_common = drop_ad_unlock_citations_for_product_query(
        query=resolved_issue_query,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        common_doc_keys=common_doc_keys,
        results=results,
        document_key=host.document_key,
    )
    aligned_keys = prefer_query_aligned_citations(
        query=resolved_issue_query,
        ordered_cited_doc_keys=pruned_keys,
        results=results,
        document_key=host.document_key,
    )
    if aligned_keys == list(ordered_cited_doc_keys):
        return ordered_cited_doc_keys, common_doc_keys
    pruned_common = {key for key in pruned_common if key in aligned_keys}
    if not pruned_common:
        return ordered_cited_doc_keys, common_doc_keys
    pruned_count = len(ordered_cited_doc_keys) - len(aligned_keys)
    if pruned_count > 0:
        from agent_service.observability import (
            METRIC_CITATION_PRUNED,
            record_metric_counter,
        )

        record_metric_counter(
            METRIC_CITATION_PRUNED,
            amount=float(pruned_count),
            attributes={"result_type": "CITATION_GUARD"},
        )
    response.claims = filter_claims_to_doc_keys(
        response.claims,
        allowed_doc_keys=pruned_common,
        document_by_chunk_id={
            result.chunk.chunk_id: host.document_key(result) for result in results
        },
    )
    return aligned_keys, pruned_common


def _policy_ids_for_answer(
    *,
    claims: Sequence[Any],
    normalized_answer: str,
) -> tuple[list[Any], list[PolicyAdvisory], list[str]]:
    knowledge_claims, claim_policy_advisories = split_claims_by_provenance(claims)
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
    return knowledge_claims, policy_advisories, policy_ids


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
    # Claim∩citation keys remain the retention basis; only drop clearly
    # off-topic AD unlock cites for non-AD product queries (e.g. CRM OTP).
    ordered_cited_doc_keys, common_doc_keys = _apply_product_citation_guards(
        host,
        response=response,
        results=results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        common_doc_keys=common_doc_keys,
        resolved_issue_query=resolved_issue_query,
    )
    evidence_text = _evidence_text_for_docs(
        host,
        results=results,
        doc_keys=set(ordered_cited_doc_keys) | set(common_doc_keys),
    )
    normalized_answer, ordered_cited_doc_keys = _normalize_pruned_answer(
        answer=answer,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        common_doc_keys=common_doc_keys,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        results_len=len(results),
        evidence_text=evidence_text,
    )
    knowledge_claims, policy_advisories, policy_ids = _policy_ids_for_answer(
        claims=response.claims,
        normalized_answer=normalized_answer,
    )
    response.claims = knowledge_claims
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
    "drop_ad_unlock_citations_for_product_query",
    "prefer_query_aligned_citations",
]
