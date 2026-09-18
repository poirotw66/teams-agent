"""Grounded answer generation stage extracted from HybridKnowledgeService.

I/O (LLM invoke, claim repair, citation URL build) is provided via callbacks
so this module stays free of HybridIndex / settings coupling.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agent_service.contracts import Citation, GroundedClaim, KnowledgeResult
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.security_policies import (
    advisories_from_text,
    citations_for_policy_ids,
    policy_ids_in_text,
    split_claims_by_provenance,
    strip_unknown_policy_markers,
)
from agent_service.temporal_claims import (
    annotate_historical_dates_in_text,
    sanitize_temporal_claims,
)

from .citation_assembly import (
    answer_has_knowledge_citation,
    build_chunk_document_maps,
    claimed_document_keys,
    filter_claims_to_doc_keys,
    infer_markers_from_claims,
    ordered_cited_keys_from_markers,
    remap_answer_citation_markers,
    resolve_doc_key_for_marker,
)
from .generator import is_unsupported_miss_answer
from .generation_retries import apply_generation_retries
from .grounding import (
    normalize_composite_citation_markers,
    prune_unbacked_sentences_and_citations,
    remap_claim_marker_ids_to_chunk_ids,
    repair_structured_answer,
    structured_answer_is_grounded,
)
from .models import StructuredKnowledgeAnswer
from .policy_overlay import merge_policy_advisories, sanitize_answer_security
from .prompts import ANSWER_PROMPT

logger = logging.getLogger(__name__)


class GenerationHost(Protocol):
    """Callbacks HybridKnowledgeService supplies to the generation stage."""

    async def invoke_llm(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        component: str,
        execution_context: ExecutionContext | None,
        counter: LlmCallCounter,
    ) -> Any: ...

    def document_key(self, result: SearchResult) -> str: ...

    def citation_for(
        self,
        result: SearchResult,
        *,
        evidence_results: list[SearchResult] | None = None,
    ) -> Citation: ...

    def images_for(self, cited_results: list[SearchResult]) -> list: ...

    def deterministic_grounded_answer(
        self,
        results: list[SearchResult],
        *,
        include_retrieval_evidence: bool,
    ) -> KnowledgeResult: ...

    def no_answer(self) -> KnowledgeResult: ...

    def evaluate_retrieval_confidence(self, state: Any) -> tuple[str, Any]: ...

    async def repair_claims_with_model(
        self,
        model: BaseChatModel,
        *,
        answer: str,
        results: list[SearchResult],
        counter: LlmCallCounter,
        execution_context: ExecutionContext | None = None,
    ) -> list[GroundedClaim]: ...


def _build_context_and_markers(
    results: list[SearchResult],
    chunk_to_doc_idx: dict[int, int],
) -> tuple[str, dict[str, list[str]], dict[str, str]]:
    context = "\n\n".join(
        f"[S{chunk_to_doc_idx[index]}] {result.chunk.title} "
        f"[chunkId={result.chunk.chunk_id}]\n"
        f"{annotate_historical_dates_in_text(result.chunk.content)}"
        for index, result in enumerate(results)
    )
    marker_to_chunk_ids: dict[str, list[str]] = {}
    chunk_content_by_id = {
        result.chunk.chunk_id: result.chunk.content for result in results
    }
    for index, result in enumerate(results):
        marker = f"S{chunk_to_doc_idx[index]}"
        marker_to_chunk_ids.setdefault(marker, []).append(result.chunk.chunk_id)
        marker_to_chunk_ids.setdefault(marker.lower(), marker_to_chunk_ids[marker])
    return context, marker_to_chunk_ids, chunk_content_by_id


async def generate_grounded_answer(
    host: GenerationHost,
    state: Any,
    counter: LlmCallCounter,
    *,
    execution_context: ExecutionContext | None = None,
    model: BaseChatModel | None = None,
    include_retrieval_evidence: bool,
) -> KnowledgeResult:
    results = state.results
    answer_model = model
    if not results:
        return host.no_answer()

    unique_doc_keys, chunk_to_doc_idx, document_by_chunk_id = build_chunk_document_maps(
        results,
        document_key=host.document_key,
    )

    if not answer_model:
        return host.deterministic_grounded_answer(
            results,
            include_retrieval_evidence=include_retrieval_evidence,
        )

    context, marker_to_chunk_ids, chunk_content_by_id = _build_context_and_markers(
        results, chunk_to_doc_idx
    )

    async def _invoke_answer() -> StructuredKnowledgeAnswer:

        return await answer_model.with_structured_output(StructuredKnowledgeAnswer).ainvoke(
            [
                SystemMessage(
                    content=ANSWER_PROMPT.format(
                        question=state.resolved_issue_query,
                        context=context,
                    )
                ),
                HumanMessage(
                    content=(
                        f"已解析問題：{state.resolved_issue_query}\n"
                        "請根據上述已授權知識內容直接回答。"
                    )
                ),
            ]
        )

    response = await host.invoke_llm(
        _invoke_answer,
        component="knowledge_generate",
        execution_context=execution_context,
        counter=counter,
    )
    response = repair_structured_answer(response)
    response.claims = remap_claim_marker_ids_to_chunk_ids(
        response.claims,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
    )
    answer = normalize_composite_citation_markers(response.answer.strip())
    answer = strip_unknown_policy_markers(answer)
    logger.info(
        "Knowledge generated candidate answer=%r answerability=%s claims=%s unknowns=%s",
        answer,
        response.answerability,
        response.claims,
        response.unknowns,
    )
    response, answer = await apply_generation_retries(
        host,
        state=state,
        results=results,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        response=response,
        answer=answer,
        counter=counter,
        execution_context=execution_context,
        enable_generation_retries=getattr(state, "enable_generation_retries", True),
    )
    if not structured_answer_is_grounded(response, results):
        logger.warning(
            "Knowledge answer rejected: _structured_answer_is_grounded failed. "
            "answerability=%s claims_count=%d unknowns=%s claims=%s answer_preview=%r",
            response.answerability,
            len(response.claims),
            response.unknowns,
            [
                {"text": claim.text, "chunkIds": claim.chunkIds}
                for claim in response.claims
            ],
            answer[:240],
        )
        return host.no_answer()

    document_by_chunk_id = {
        result.chunk.chunk_id: host.document_key(result) for result in results
    }

    def _resolve_doc_key(marker_num: int) -> str | None:
        return resolve_doc_key_for_marker(
            marker_num,
            unique_doc_keys=unique_doc_keys,
            chunk_to_doc_idx=chunk_to_doc_idx,
            results_len=len(results),
        )

    raw_markers = [int(value) for value in re.findall(r"\[S(\d+)\]", answer)]
    if not raw_markers and response.claims:
        inferred_markers = infer_markers_from_claims(
            response.claims,
            document_by_chunk_id=document_by_chunk_id,
            unique_doc_keys=unique_doc_keys,
        )
        if inferred_markers:
            markers_str = " ".join(f"[S{m}]" for m in inferred_markers)
            answer = f"{answer} {markers_str}"
            raw_markers = inferred_markers
            logger.info("Repaired missing [S#] markers from claims: %s", markers_str)

    if not raw_markers:
        logger.warning(
            "Knowledge answer rejected: no [S#] markers and no claim-derived markers"
        )
        return host.no_answer()

    ordered_cited_doc_keys = ordered_cited_keys_from_markers(
        raw_markers,
        resolve_doc_key=_resolve_doc_key,
    )

    if not ordered_cited_doc_keys:
        logger.warning(
            "Knowledge answer rejected: raw_markers=%s resolved=%s unique_doc_keys_len=%d",
            raw_markers,
            [_resolve_doc_key(m) for m in raw_markers],
            len(unique_doc_keys),
        )
        return host.no_answer()

    is_unsupported_miss = is_unsupported_miss_answer(
        answer=answer,
        answerability=response.answerability,
        claims=response.claims,
    )
    if is_unsupported_miss:
        logger.warning(
            "Knowledge answer rejected: unsupported_miss=%s ordered_cited_doc_keys=%s",
            is_unsupported_miss,
            ordered_cited_doc_keys,
        )
        return host.no_answer()

    claimed_doc_keys = claimed_document_keys(
        response.claims,
        document_by_chunk_id=document_by_chunk_id,
    )

    # Localized deterministic grounding and citation pruning:
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
            "Knowledge answer rejected: no common doc keys between claims (%s) and citations (%s)",
            claimed_doc_keys,
            ordered_cited_doc_keys,
        )
        return host.no_answer()

    response.claims = filter_claims_to_doc_keys(
        response.claims,
        allowed_doc_keys=common_doc_keys,
        document_by_chunk_id=document_by_chunk_id,
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

    knowledge_claims, claim_policy_advisories = split_claims_by_provenance(response.claims)
    response.claims = knowledge_claims
    text_policy_advisories = advisories_from_text(normalized_answer)
    policy_advisories = merge_policy_advisories(
        claim_policy_advisories,
        text_policy_advisories,
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

    sources: list[Citation] = []
    for doc_key in ordered_cited_doc_keys:
        document_results = [
            result for result in results if host.document_key(result) == doc_key
        ]
        sources.append(
            host.citation_for(
                document_results[0],
                evidence_results=(document_results if include_retrieval_evidence else None),
            )
        )
    sources.extend(
        citations_for_policy_ids(
            policy_ids,
            include_evidence=include_retrieval_evidence,
        )
    )

    if not answer_has_knowledge_citation(normalized_answer) or not ordered_cited_doc_keys:
        logger.warning(
            "Knowledge answer rejected after pruning: missing knowledge citations"
        )
        return host.no_answer()

    cited_results = [
        result for result in results if host.document_key(result) in ordered_cited_doc_keys
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


__all__ = ["GenerationHost", "generate_grounded_answer"]
