"""Claim alignment, pruning, and KnowledgeResult assembly for generation."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel

from agent_service.contracts import Citation, KnowledgeResult
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.security_policies import is_policy_id, split_claims_by_provenance
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
from .policy_overlay import sanitize_answer_security

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
    remain when both sources are on-query. For single-topic queries, also prefer
    the document whose title better matches the query so sibling manuals
    (VPN Q&A vs FortiClient, 大州首次 vs 功能無法點選) are not over-cited.
    """
    keys = [key for key in ordered_cited_doc_keys if key]
    if len(keys) <= 1:
        return list(keys)

    from .generator import query_anchor_tokens

    anchors = query_anchor_tokens(query)
    if not anchors:
        return list(keys)

    def _doc_blob(doc_key: str) -> tuple[str, str]:
        title_parts: list[str] = []
        blob_parts: list[str] = []
        for result in results:
            if document_key(result) != doc_key:
                continue
            title_parts.append(result.chunk.title or "")
            blob_parts.append(f"{result.chunk.title}\n{result.chunk.content}")
        return "\n".join(title_parts), "\n".join(blob_parts)

    def _overlap(doc_key: str) -> int:
        _title, blob = _doc_blob(doc_key)
        blob_l = blob.lower()
        if not blob_l:
            return 0
        return sum(1 for anchor in anchors if anchor.lower() in blob_l)

    def _title_overlap(doc_key: str) -> int:
        title, _blob = _doc_blob(doc_key)
        expanded = title
        synonym_bonus = 0
        for left, right in (
            ("第一次", "首次"),
            ("首次", "第一次"),
        ):
            if left in (query or "") and right in title:
                expanded = f"{expanded}\n{left}"
                synonym_bonus += 4
        if not expanded:
            return 0
        score = synonym_bonus
        query_text = query or ""
        # Score title pieces present in the query (avoids long-run miss on CJK).
        seen: set[str] = set()
        for title_run in re.findall(
            r"[A-Za-z][A-Za-z0-9_./:-]{1,}|[\u3400-\u9fff]{2,}",
            expanded,
        ):
            key = title_run.casefold()
            if key in seen:
                continue
            if title_run.casefold() in query_text.casefold() or title_run in query_text:
                seen.add(key)
                score += min(4, max(1, len(title_run) // 2))
                continue
            for size in (4, 3, 2):
                if len(title_run) < size:
                    continue
                hit = False
                for index in range(len(title_run) - size + 1):
                    piece = title_run[index : index + size]
                    if piece.casefold() in query_text.casefold() or piece in query_text:
                        seen.add(piece.casefold())
                        score += size - 1
                        hit = True
                        break
                if hit:
                    break
        return score

    scored = [(key, _overlap(key)) for key in keys]
    best = max(score for _, score in scored)
    if best <= 0:
        return list(keys[:1])

    from .grounding import query_asks_for_procedure
    from .selector import query_asks_for_comparison

    positive = [(key, score) for key, score in scored if score > 0]
    # Comparison / coordinated product asks need both named manuals retained.
    multi_topic = (
        ("、" in query)
        or ("與" in query)
        or ("及" in query)
        or ("跟" in query)
        or ("vs" in (query or "").casefold())
        or query_asks_for_comparison(query)
    )
    procedure_query = query_asks_for_procedure(query)
    second = max((score for _, score in positive if score < best), default=0)
    # Require a clear relative gap before dropping a positive secondary source.
    # Absolute gaps of 2 are common with CJK bigram anchors on near-equal docs.
    clear_gap = second > 0 and second < (best * 0.5) and (best - second) >= 2
    # Procedure how-to companions (e.g. FortiClient Ctrl+Alt+Delete) often score
    # below the FAQ title match; keep every positive cite for procedure asks.
    if not multi_topic and not procedure_query and best >= 2 and clear_gap:
        keep = {key for key, score in positive if score == best}
    else:
        keep = {key for key, _score in positive}

    # Single-topic sibling prune: title alignment breaks near-ties when one
    # title clearly owns distinctive query wording the other lacks.
    # Skip when content overlap is near-equal (multi-doc supporting answers).
    # Also skip for procedure how-to: VPN Q&A titles beat FortiClient even when
    # the executable Ctrl+Alt+Delete steps live only in the companion.
    if not multi_topic and len(keep) > 1 and not procedure_query:
        near_equal_content = second > 0 and second >= (best * 0.75)
        if not near_equal_content:
            title_scored = [(key, _title_overlap(key)) for key in keys if key in keep]
            best_title = max((score for _, score in title_scored), default=0)
            second_title = max(
                (score for _, score in title_scored if score < best_title),
                default=0,
            )
            title_gap = best_title - second_title
            content_winners = {key for key, score in positive if score == best}
            title_winners = {
                key for key, score in title_scored if score == best_title
            }
            if (best_title >= 2 and title_gap >= 2) or (
                best_title >= 1 and second_title == 0
            ):
                keep = title_winners
            elif (
                best_title > second_title
                and best > second
                and content_winners & title_winners
            ):
                # Content and title agree on a unique primary sibling.
                keep = content_winners & title_winners

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
    return sources


def _knowledge_claims_only(claims: Sequence[Any]) -> list[Any]:
    """Drop POLICY-SEC claim ids; POLICY overlays are out of knowledge scope."""
    knowledge_claims, _policy_advisories = split_claims_by_provenance(claims)
    cleaned: list[Any] = []
    for claim in knowledge_claims:
        chunk_ids = [
            chunk_id
            for chunk_id in (getattr(claim, "chunkIds", None) or [])
            if chunk_id and not is_policy_id(str(chunk_id))
        ]
        if not chunk_ids and getattr(claim, "chunkIds", None):
            continue
        if chunk_ids != list(getattr(claim, "chunkIds", None) or []):
            cleaned.append(claim.model_copy(update={"chunkIds": chunk_ids}))
        else:
            cleaned.append(claim)
    return cleaned


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
    response.claims = _knowledge_claims_only(response.claims)
    sources = _build_answer_sources(
        host,
        results=results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
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
        policyAdvisories=[],
        unknowns=response.unknowns,
    )


__all__ = [
    "align_claims_with_citations",
    "assemble_grounded_knowledge_result",
    "drop_ad_unlock_citations_for_product_query",
    "prefer_query_aligned_citations",
]
