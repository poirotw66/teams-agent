"""Grounded answer generation stage extracted from HybridKnowledgeService.

I/O (LLM invoke, claim repair, citation URL build) is provided via callbacks
so this module stays free of HybridIndex / settings coupling.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel

from agent_service.contracts import Citation, GroundedClaim, KnowledgeResult
from agent_service.execution_context import ExecutionContext
from agent_service.llm_call_counter import LlmCallCounter
from agent_service.retrieval import SearchResult
from agent_service.retrieval_expand import EvidenceBundle

from .citation_assembly import build_chunk_document_maps
from .generation_stage_invoke import (
    build_context_and_markers,
    invoke_initial_grounded_answer,
    resolve_cited_document_keys,
)
from .generation_stage_result import (
    align_claims_with_citations,
    assemble_grounded_knowledge_result,
)


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

    @property
    def chunk_by_id(self) -> dict[str, Any]: ...

    @property
    def chunks_by_parent_id(self) -> dict[str, list[Any]]: ...

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


def _prepare_generation_context(
    host: GenerationHost,
    state: Any,
    results: list[SearchResult],
    chunk_to_doc_idx: Mapping[str, int],
    *,
    execution_context: ExecutionContext | None = None,
) -> tuple[str, dict[str, list[str]], dict[str, str], list[EvidenceBundle]]:
    tier_val = (
        getattr(state, "query_tier", None)
        or getattr(getattr(state, "provisional_tier", None), "value", None)
        or (
            str(getattr(state, "provisional_tier", None))
            if getattr(state, "provisional_tier", None)
            else None
        )
    )
    override_budget = None
    if execution_context is not None:
        raw_override = execution_context.evaluation_override("evidence_token_budget")
        if raw_override is not None:
            override_budget = int(raw_override)
    if override_budget is not None:
        token_budget = override_budget
    else:
        budget_for = getattr(host, "evidence_token_budget_for", None)
        if callable(budget_for):
            token_budget = budget_for(tier_val)
        else:
            token_budget = getattr(host, "evidence_token_budget", None)
    context, marker_to_chunk_ids, chunk_content_by_id, bundles = build_context_and_markers(
        results,
        chunk_to_doc_idx,
        chunk_by_id=getattr(host, "chunk_by_id", None) or None,
        chunks_by_parent_id=getattr(host, "chunks_by_parent_id", None) or None,
        query_tier=tier_val,
        token_budget=token_budget,
    )
    context_ids: list[str] = []
    for chunk_ids in marker_to_chunk_ids.values():
        for chunk_id in chunk_ids:
            if chunk_id and chunk_id not in context_ids:
                context_ids.append(chunk_id)
    object.__setattr__(state, "generator_context_chunk_ids", tuple(context_ids))
    return context, marker_to_chunk_ids, chunk_content_by_id, bundles


async def _align_and_assemble(
    host: GenerationHost,
    *,
    response: Any,
    answer: str,
    results: list[SearchResult],
    unique_doc_keys: list[str],
    chunk_to_doc_idx: Mapping[str, int],
    bundles: list[EvidenceBundle],
    answer_model: BaseChatModel,
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
    include_retrieval_evidence: bool,
    resolved_issue_query: str = "",
) -> KnowledgeResult:
    cited = resolve_cited_document_keys(
        host=host,
        response=response,
        answer=answer,
        results=results,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        bundles=bundles,
        resolved_issue_query=resolved_issue_query,
    )
    if isinstance(cited, KnowledgeResult):
        return cited
    answer, ordered_cited_doc_keys = cited

    aligned = await align_claims_with_citations(
        host,
        response=response,
        answer=answer,
        results=results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        answer_model=answer_model,
        counter=counter,
        execution_context=execution_context,
        bundles=bundles,
    )
    if isinstance(aligned, KnowledgeResult):
        return aligned
    response, common_doc_keys = aligned

    return assemble_grounded_knowledge_result(
        host,
        response=response,
        answer=answer,
        results=results,
        ordered_cited_doc_keys=ordered_cited_doc_keys,
        common_doc_keys=common_doc_keys,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        include_retrieval_evidence=include_retrieval_evidence,
        resolved_issue_query=resolved_issue_query,
    )


def _model_label(model: BaseChatModel | None) -> str | None:
    if model is None:
        return None
    label = getattr(model, "model_name", None) or getattr(model, "model", None)
    return str(label) if label else None


def _rag_bundle(host: GenerationHost) -> tuple[str, BaseChatModel | None]:
    service = getattr(host, "_service", None)
    settings = getattr(service, "settings", None)
    policy = str(getattr(settings, "rag_answer_escalation_policy", "OFF") or "OFF")
    hard = getattr(getattr(service, "models", None), "hard_answer", None)
    return policy, hard


def _select_answer_model(
    host: GenerationHost,
    state: Any,
    model: BaseChatModel | None,
) -> BaseChatModel | None:
    from .answer_escalation import initial_answer_escalation
    from .trace import set_answer_trace

    policy, hard = _rag_bundle(host)
    decision = initial_answer_escalation(
        policy=policy,
        query_tier=getattr(state, "query_tier", None),
        hard_model_available=hard is not None,
    )
    selected = hard if decision.use_hard_model and hard is not None else model
    set_answer_trace(
        {
            "answerModel": _model_label(selected),
            "answerEscalated": decision.escalated,
            "answerEscalationModel": _model_label(hard) if decision.escalated else None,
            "answerEscalationReason": decision.reason,
            "answerAttemptCount": decision.attempt_count,
        }
    )
    if decision.escalated:
        from agent_service.observability import (
            METRIC_ANSWER_ESCALATION,
            record_metric_counter,
        )

        record_metric_counter(
            METRIC_ANSWER_ESCALATION,
            attributes={
                "escalation_reason": str(decision.reason or "HARD_TIER"),
                "model_role": "hard_answer",
            },
        )
    return selected


def _maybe_escalate_answer_model(
    host: GenerationHost,
    *,
    response: Any,
    results: list[SearchResult],
    bundles: list[EvidenceBundle],
    current_model: BaseChatModel | None,
    execution_context: ExecutionContext | None = None,
) -> BaseChatModel | None:
    from .answer_escalation import retry_answer_escalation
    from .grounding import structured_answer_is_grounded
    from .trace import current_answer_trace, set_answer_trace

    policy, hard = _rag_bundle(host)
    grounded = structured_answer_is_grounded(response, results, bundles=bundles)
    trace = current_answer_trace() or {}
    already = bool(trace.get("answerEscalated"))
    remaining = (
        execution_context.remaining_seconds()
        if execution_context is not None
        else None
    )
    deadline_ok = remaining is None or remaining > 1.0
    budget_ok = (
        execution_context.budget_remaining() >= 1
        if execution_context is not None
        else True
    )
    failure_reason = None if grounded else "GROUNDING_FAILURE"
    if failure_reason is None and getattr(response, "answerability", None) not in {
        "FULL",
        "PARTIAL",
        "NONE",
        None,
    }:
        failure_reason = "STRUCTURED_OUTPUT_FAILURE"
    decision = retry_answer_escalation(
        policy=policy,
        failure_reason=failure_reason,
        hard_model_available=hard is not None,
        already_escalated=already,
        has_evidence=bool(results),
        is_valid_no_answer=getattr(response, "answerability", None) == "NONE",
        deadline_allows_retry=deadline_ok,
        budget_allows_retry=budget_ok,
    )
    if not decision.use_hard_model or hard is None or hard is current_model:
        if decision.reason == "HARD_MODEL_UNAVAILABLE":
            set_answer_trace({**trace, "answerEscalationReason": "HARD_MODEL_UNAVAILABLE"})
        return current_model
    set_answer_trace(
        {
            "answerModel": trace.get("answerModel") or _model_label(current_model),
            "answerEscalated": True,
            "answerEscalationModel": _model_label(hard),
            "answerEscalationReason": decision.reason,
            "answerAttemptCount": 2,
        }
    )
    from agent_service.observability import (
        METRIC_ANSWER_ESCALATION,
        record_metric_counter,
    )

    record_metric_counter(
        METRIC_ANSWER_ESCALATION,
        attributes={
            "escalation_reason": str(decision.reason or "GROUNDING_FAILURE"),
            "model_role": "hard_answer",
        },
    )
    return hard


async def _invoke_with_optional_escalation(
    host: GenerationHost,
    *,
    state: Any,
    results: list[SearchResult],
    answer_model: BaseChatModel,
    context: str,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str],
    bundles: list[EvidenceBundle],
    counter: LlmCallCounter,
    execution_context: ExecutionContext | None,
) -> tuple[Any, str, BaseChatModel]:
    response, answer = await invoke_initial_grounded_answer(
        host,
        state=state,
        results=results,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        counter=counter,
        execution_context=execution_context,
    )
    escalated = _maybe_escalate_answer_model(
        host,
        response=response,
        results=results,
        bundles=bundles,
        current_model=answer_model,
        execution_context=execution_context,
    )
    if escalated is None or escalated is answer_model:
        return response, answer, answer_model
    response, answer = await invoke_initial_grounded_answer(
        host,
        state=state,
        results=results,
        answer_model=escalated,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        counter=counter,
        execution_context=execution_context,
        component="knowledge_answer_escalation",
    )
    from agent_service.observability import (
        METRIC_ANSWER_ESCALATION_SUCCESS,
        record_metric_counter,
    )

    from .grounding import structured_answer_is_grounded

    if structured_answer_is_grounded(response, results, bundles=bundles):
        record_metric_counter(
            METRIC_ANSWER_ESCALATION_SUCCESS,
            attributes={"model_role": "hard_answer"},
        )
    return response, answer, escalated


async def generate_grounded_answer(
    host: GenerationHost,
    state: Any,
    counter: LlmCallCounter,
    *,
    execution_context: ExecutionContext | None = None,
    model: BaseChatModel | None = None,
    include_retrieval_evidence: bool,
) -> KnowledgeResult:
    from .source_roles import SourceRole, assign_source_roles, filter_results_for_generation

    query = str(getattr(state, "resolved_issue_query", "") or "")
    results = filter_results_for_generation(
        query=query,
        results=list(state.results or []),
        document_key=host.document_key,
    )
    if not results:
        return host.no_answer()
    roles = assign_source_roles(
        query=query,
        results=results,
        document_key=host.document_key,
    )
    if roles and SourceRole.PRIMARY not in roles.values():
        return host.no_answer()
    unique_doc_keys, chunk_to_doc_idx, _document_by_chunk_id = build_chunk_document_maps(
        results,
        document_key=host.document_key,
    )
    if not model:
        return host.deterministic_grounded_answer(
            results,
            include_retrieval_evidence=include_retrieval_evidence,
        )
    context, marker_to_chunk_ids, chunk_content_by_id, bundles = _prepare_generation_context(
        host,
        state,
        results,
        chunk_to_doc_idx,
        execution_context=execution_context,
    )
    answer_model = _select_answer_model(host, state, model)
    if answer_model is None:
        return host.deterministic_grounded_answer(
            results,
            include_retrieval_evidence=include_retrieval_evidence,
        )
    response, answer, answer_model = await _invoke_with_optional_escalation(
        host,
        state=state,
        results=results,
        answer_model=answer_model,
        context=context,
        marker_to_chunk_ids=marker_to_chunk_ids,
        chunk_content_by_id=chunk_content_by_id,
        bundles=bundles,
        counter=counter,
        execution_context=execution_context,
    )
    assembled = await _align_and_assemble(
        host,
        response=response,
        answer=answer,
        results=results,
        unique_doc_keys=unique_doc_keys,
        chunk_to_doc_idx=chunk_to_doc_idx,
        bundles=bundles,
        answer_model=answer_model,
        counter=counter,
        execution_context=execution_context,
        include_retrieval_evidence=include_retrieval_evidence,
        resolved_issue_query=query,
    )
    if assembled.found:
        return assembled

    # Optional single-doc retry: when multi-doc packing produced an empty /
    # ungrounded wipe but a clear PRIMARY remains, regenerate on that doc alone.
    primary_results = [
        result
        for result in results
        if roles.get(host.document_key(result), SourceRole.PRIMARY) == SourceRole.PRIMARY
    ]
    primary_keys = {
        host.document_key(result) for result in primary_results if host.document_key(result)
    }
    all_keys = {host.document_key(result) for result in results if host.document_key(result)}
    if len(all_keys) <= 1 or not primary_keys or primary_keys >= all_keys:
        return assembled

    narrow_results = [
        result for result in results if host.document_key(result) in primary_keys
    ]
    narrow_unique, narrow_chunk_map, _ = build_chunk_document_maps(
        narrow_results,
        document_key=host.document_key,
    )
    narrow_context, narrow_markers, narrow_contents, narrow_bundles = (
        _prepare_generation_context(
            host,
            state,
            narrow_results,
            narrow_chunk_map,
            execution_context=execution_context,
        )
    )
    response, answer, answer_model = await _invoke_with_optional_escalation(
        host,
        state=state,
        results=narrow_results,
        answer_model=answer_model,
        context=narrow_context,
        marker_to_chunk_ids=narrow_markers,
        chunk_content_by_id=narrow_contents,
        bundles=narrow_bundles or [],
        counter=counter,
        execution_context=execution_context,
    )
    return await _align_and_assemble(
        host,
        response=response,
        answer=answer,
        results=narrow_results,
        unique_doc_keys=narrow_unique,
        chunk_to_doc_idx=narrow_chunk_map,
        bundles=narrow_bundles or [],
        answer_model=answer_model,
        counter=counter,
        execution_context=execution_context,
        include_retrieval_evidence=include_retrieval_evidence,
        resolved_issue_query=query,
    )


__all__ = ["GenerationHost", "generate_grounded_answer"]
