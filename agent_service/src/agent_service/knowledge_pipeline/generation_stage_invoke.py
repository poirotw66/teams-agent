"""Invoke and post-retry citation resolution for grounded generation."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from agent_service.contracts import KnowledgeResult
from agent_service.documents import DocumentChunk
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.retrieval_expand import EvidenceBundle, build_evidence_bundles
from agent_service.security_policies import strip_unknown_policy_markers
from agent_service.structured_invoke import ainvoke_structured
from agent_service.temporal_claims import annotate_historical_dates_in_text

from .citation_assembly import (
    infer_markers_from_claims,
    ordered_cited_keys_from_markers,
    resolve_doc_key_for_marker,
)
from .generation_retries import apply_generation_retries
from .generator import is_unsupported_miss_answer
from .grounding import (
    normalize_composite_citation_markers,
    remap_claim_marker_ids_to_chunk_ids,
    repair_structured_answer,
    structured_answer_is_grounded,
)
from .models import StructuredKnowledgeAnswer
from .prompts import ANSWER_PROMPT

logger = logging.getLogger(__name__)


def build_context_and_markers(
    results: list[SearchResult],
    chunk_to_doc_idx: dict[int, int],
    *,
    chunk_by_id: Mapping[str, DocumentChunk] | None = None,
    chunks_by_parent_id: Mapping[str, Sequence[DocumentChunk]] | None = None,
    query_tier: str | None = None,
    token_budget: int | None = None,
) -> tuple[str, dict[str, list[str]], dict[str, str], list[EvidenceBundle] | None]:
    """Build generator context; optionally expand parent/neighbor per seed.

    Ranking order of ``results`` is preserved. Expanded context is appended
    under the same citation marker as the seed and is not treated as a hit.
    """
    bundles = (
        build_evidence_bundles(
            results,
            chunk_by_id=chunk_by_id,
            chunks_by_parent_id=chunks_by_parent_id,
            query_tier=query_tier,
            token_budget=token_budget,
        )
        if chunk_by_id
        else None
    )
    if bundles is not None:
        context_parts: list[str] = []
        for index, bundle in enumerate(bundles):
            marker = f"[S{chunk_to_doc_idx[index]}]"
            seed = bundle.seed
            body = annotate_historical_dates_in_text(seed.chunk.content)
            seed_block = f"{marker} {seed.chunk.title} [chunkId={seed.chunk.chunk_id}]\n{body}"
            supporting_blocks = [
                f"[chunkId={chunk.chunk_id}]\n{annotate_historical_dates_in_text(chunk.content)}"
                for chunk in bundle.supporting_chunks
                if chunk.content.strip()
            ]
            if supporting_blocks:
                block = f"{seed_block}\n\n" + "\n\n".join(supporting_blocks)
            else:
                block = seed_block
            context_parts.append(block)
        context = "\n\n".join(context_parts)
    else:
        context = "\n\n".join(
            f"[S{chunk_to_doc_idx[index]}] {result.chunk.title} "
            f"[chunkId={result.chunk.chunk_id}]\n"
            f"{annotate_historical_dates_in_text(result.chunk.content)}"
            for index, result in enumerate(results)
        )
    marker_to_chunk_ids: dict[str, list[str]] = {}
    chunk_content_by_id = {result.chunk.chunk_id: result.chunk.content for result in results}
    if bundles is not None:
        for index, bundle in enumerate(bundles):
            marker = f"S{chunk_to_doc_idx[index]}"
            cids = [bundle.seed.chunk.chunk_id]
            for chunk in bundle.supporting_chunks:
                cids.append(chunk.chunk_id)
                chunk_content_by_id.setdefault(chunk.chunk_id, chunk.content)
            marker_to_chunk_ids.setdefault(marker, []).extend(cids)
            marker_to_chunk_ids.setdefault(marker.lower(), marker_to_chunk_ids[marker])
    else:
        for index, result in enumerate(results):
            marker = f"S{chunk_to_doc_idx[index]}"
            marker_to_chunk_ids.setdefault(marker, []).append(result.chunk.chunk_id)
            marker_to_chunk_ids.setdefault(marker.lower(), marker_to_chunk_ids[marker])
    return context, marker_to_chunk_ids, chunk_content_by_id, bundles


async def invoke_initial_grounded_answer(
    host: Any,
    *,
    state: Any,
    results: list[SearchResult],
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[StructuredKnowledgeAnswer, str]:
    async def _invoke_answer() -> StructuredKnowledgeAnswer:
        return await ainvoke_structured(
            answer_model,
            StructuredKnowledgeAnswer,
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
            ],
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
    return await apply_generation_retries(
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


def _reject_ungrounded_answer(
    host: Any,
    *,
    response: StructuredKnowledgeAnswer,
    answer: str,
    results: list[SearchResult],
    bundles: Sequence[EvidenceBundle] | None = None,
) -> KnowledgeResult | None:
    if structured_answer_is_grounded(response, results, bundles=bundles):
        return None
    logger.warning(
        "Knowledge answer rejected: _structured_answer_is_grounded failed. "
        "answerability=%s claims_count=%d unknowns=%s claims=%s answer_preview=%r",
        response.answerability,
        len(response.claims),
        response.unknowns,
        [{"text": claim.text, "chunkIds": claim.chunkIds} for claim in response.claims],
        answer[:240],
    )
    return host.no_answer()


def _markers_from_answer_or_claims(
    *,
    host: Any,
    response: StructuredKnowledgeAnswer,
    answer: str,
    results: list[SearchResult],
    unique_doc_keys: list[str],
    bundles: Sequence[EvidenceBundle] | None = None,
) -> tuple[str, list[int]] | KnowledgeResult:
    document_by_chunk_id = {result.chunk.chunk_id: host.document_key(result) for result in results}
    if bundles:
        for bundle in bundles:
            seed_doc_key = host.document_key(bundle.seed)
            for chunk in bundle.supporting_chunks:
                doc_key = (
                    (chunk.document_id or "").strip()
                    or (chunk.source_path or "").strip()
                    or chunk.title.strip()
                    or seed_doc_key
                )
                document_by_chunk_id.setdefault(chunk.chunk_id, doc_key)
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
        logger.warning("Knowledge answer rejected: no [S#] markers and no claim-derived markers")
        return host.no_answer()
    return answer, raw_markers


def resolve_cited_document_keys(
    *,
    host: Any,
    response: StructuredKnowledgeAnswer,
    answer: str,
    results: list[SearchResult],
    unique_doc_keys: list[str],
    chunk_to_doc_idx: dict[int, int],
    bundles: Sequence[EvidenceBundle] | None = None,
    resolved_issue_query: str = "",
) -> tuple[str, list[str]] | KnowledgeResult:
    """Return (answer, ordered_cited_doc_keys) or a no-answer KnowledgeResult."""
    rejected = _reject_ungrounded_answer(
        host, response=response, answer=answer, results=results, bundles=bundles
    )
    if rejected is not None:
        return rejected

    markers = _markers_from_answer_or_claims(
        host=host,
        response=response,
        answer=answer,
        results=results,
        unique_doc_keys=unique_doc_keys,
        bundles=bundles,
    )
    if isinstance(markers, KnowledgeResult):
        return markers
    answer, raw_markers = markers

    def _resolve_doc_key(marker_num: int) -> str | None:
        return resolve_doc_key_for_marker(
            marker_num,
            unique_doc_keys=unique_doc_keys,
            chunk_to_doc_idx=chunk_to_doc_idx,
            results_len=len(results),
        )

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

    if is_unsupported_miss_answer(
        answer=answer,
        answerability=response.answerability,
        claims=response.claims,
        resolved_issue_query=resolved_issue_query,
    ):
        logger.warning(
            "Knowledge answer rejected: unsupported_miss ordered_cited_doc_keys=%s",
            ordered_cited_doc_keys,
        )
        return host.no_answer()

    return answer, ordered_cited_doc_keys


__all__ = [
    "build_context_and_markers",
    "invoke_initial_grounded_answer",
    "resolve_cited_document_keys",
]
