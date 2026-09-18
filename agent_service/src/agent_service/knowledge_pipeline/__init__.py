"""Pure knowledge pipeline helpers extracted from HybridKnowledgeService.

I/O-bound stages (retriever cache mutation, LLM relevance invoke, generator)
still orchestrate through ``agent_service.knowledge.HybridKnowledgeService``.
"""

from .candidate_policy import (
    filter_cross_scenario_chunks,
    is_non_production_knowledge_chunk,
)
from .grounding import (
    answer_covers_error_branches,
    answer_covers_procedure_steps,
    answer_covers_visual_evidence_plates,
    answer_passes_safety_checks,
    error_branch_codes_in_text,
    missing_procedure_steps,
    missing_visual_evidence_plates,
    normalize_composite_citation_markers,
    procedure_steps_in_text,
    prune_unbacked_sentences_and_citations,
    prune_uncited_material_sentences,
    query_asks_for_procedure,
    query_asks_for_visual_evidence,
    remap_claim_marker_ids_to_chunk_ids,
    repair_structured_answer,
    structured_answer_is_grounded,
    visual_evidence_plates_in_text,
)
from .models import (
    GroundedClaimRepair,
    RelevanceDecision,
    RewrittenQuery,
    StructuredKnowledgeAnswer,
)
from .planner import (
    bounded_facet_queries,
    missing_diagnosis_facet_queries,
    requested_diagnosis_facets,
)
from .policy_overlay import merge_policy_advisories, sanitize_answer_security
from .relevance import (
    GRADE_PROMPT,
    HIGH_CONFIDENCE_RETRIEVAL_MIN_SCORE,
    annotate_relevance_attempts,
    answer_indicates_insufficient_information,
    build_relevance_grade_context,
    conflicting_top_candidates,
    deterministic_relevance_without_model,
    distinctive_query_tokens,
    evaluate_retrieval_confidence,
    format_grade_prompt,
    high_confidence_retrieval_hit,
    primary_distinctive_tokens,
    query_lexically_matches_results,
)
from .retriever import (
    MAX_RETRIEVAL_CACHE_SIZE,
    RETRIEVAL_CANDIDATE_MULTIPLIER,
    accumulate_stage_timings,
    make_retrieval_cache_key,
    merge_best_chunk_results,
    resolve_retrieval_queries,
)
from .trace import attach_retrieval_trace, build_retrieval_attempt

__all__ = [
    "GRADE_PROMPT",
    "HIGH_CONFIDENCE_RETRIEVAL_MIN_SCORE",
    "MAX_RETRIEVAL_CACHE_SIZE",
    "RETRIEVAL_CANDIDATE_MULTIPLIER",
    "GroundedClaimRepair",
    "RelevanceDecision",
    "RewrittenQuery",
    "StructuredKnowledgeAnswer",
    "accumulate_stage_timings",
    "annotate_relevance_attempts",
    "answer_covers_error_branches",
    "answer_covers_procedure_steps",
    "answer_covers_visual_evidence_plates",
    "answer_indicates_insufficient_information",
    "answer_passes_safety_checks",
    "attach_retrieval_trace",
    "bounded_facet_queries",
    "build_relevance_grade_context",
    "build_retrieval_attempt",
    "conflicting_top_candidates",
    "deterministic_relevance_without_model",
    "distinctive_query_tokens",
    "error_branch_codes_in_text",
    "evaluate_retrieval_confidence",
    "filter_cross_scenario_chunks",
    "format_grade_prompt",
    "high_confidence_retrieval_hit",
    "is_non_production_knowledge_chunk",
    "make_retrieval_cache_key",
    "merge_best_chunk_results",
    "merge_policy_advisories",
    "missing_diagnosis_facet_queries",
    "missing_procedure_steps",
    "missing_visual_evidence_plates",
    "normalize_composite_citation_markers",
    "primary_distinctive_tokens",
    "procedure_steps_in_text",
    "prune_unbacked_sentences_and_citations",
    "prune_uncited_material_sentences",
    "query_asks_for_procedure",
    "query_asks_for_visual_evidence",
    "query_lexically_matches_results",
    "remap_claim_marker_ids_to_chunk_ids",
    "repair_structured_answer",
    "requested_diagnosis_facets",
    "resolve_retrieval_queries",
    "sanitize_answer_security",
    "structured_answer_is_grounded",
    "visual_evidence_plates_in_text",
]
