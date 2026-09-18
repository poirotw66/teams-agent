"""Knowledge Service facade: protocol, hybrid adapter, compatibility re-exports."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from langchain_core.messages import BaseMessage

from .contracts import AgentRequest, KnowledgeResult, UserContext
from .execution_context import ExecutionContext
from .knowledge_hybrid import HybridKnowledgeService, KnowledgeLLM, _RetrievalState
from .knowledge_pipeline import (
    GroundedClaimRepair,
    RelevanceDecision,
    RewrittenQuery,
    StructuredKnowledgeAnswer,
    answer_covers_procedure_steps,
    answer_covers_visual_evidence_plates,
    answer_indicates_insufficient_information,
    bounded_facet_queries,
    high_confidence_retrieval_hit,
    missing_diagnosis_facet_queries,
    missing_procedure_steps,
    missing_visual_evidence_plates,
    normalize_composite_citation_markers,
    procedure_steps_in_text,
    query_asks_for_procedure,
    query_asks_for_visual_evidence,
    query_lexically_matches_results,
    remap_claim_marker_ids_to_chunk_ids,
    visual_evidence_plates_in_text,
)
from .knowledge_pipeline.prompts import ANSWER_PROMPT
from .llm_call_counter import LlmCallCounter

__all__ = [
    "ANSWER_PROMPT",
    "GroundedClaimRepair",
    "HybridKnowledgeService",
    "KnowledgeLLM",
    "KnowledgeResult",
    "KnowledgeService",
    "RelevanceDecision",
    "RewrittenQuery",
    "StructuredKnowledgeAnswer",
    "_RetrievalState",
    "answer_covers_procedure_steps",
    "answer_covers_visual_evidence_plates",
    "answer_indicates_insufficient_information",
    "bounded_facet_queries",
    "high_confidence_retrieval_hit",
    "missing_diagnosis_facet_queries",
    "missing_procedure_steps",
    "missing_visual_evidence_plates",
    "normalize_composite_citation_markers",
    "procedure_steps_in_text",
    "query_asks_for_procedure",
    "query_asks_for_visual_evidence",
    "query_lexically_matches_results",
    "remap_claim_marker_ids_to_chunk_ids",
    "visual_evidence_plates_in_text",
]


def message_text(message: BaseMessage) -> str:
    return str(message.text).strip()


@runtime_checkable
class KnowledgeService(Protocol):
    """Spec §8.1 Knowledge Service; correlation_id is keyword-only for §15.1."""

    async def search(
        self,
        query: str,
        user_context: UserContext,
        *,
        correlation_id: str | None = None,
        call_counter: LlmCallCounter | None = None,
        execution_context: ExecutionContext | None = None,
        request: AgentRequest | None = None,
    ) -> KnowledgeResult: ...
