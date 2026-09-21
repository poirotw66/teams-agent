"""Tests for evidence progression and hard-answer escalation decisions."""

from __future__ import annotations

from agent_service.knowledge_pipeline.answer_escalation import (
    initial_answer_escalation,
    retry_answer_escalation,
)
from agent_service.knowledge_pipeline.evidence_trace import build_evidence_progression


def test_evidence_progression_records_drop_stage_without_content() -> None:
    progression = build_evidence_progression(
        candidate_chunk_ids=["a", "b", "c"],
        post_selection_chunk_ids=["a", "b"],
        bundle_chunk_ids=["a"],
        generator_context_chunk_ids=["a"],
        cited_chunk_ids=[],
    )
    stages = {item["chunkId"]: item["stage"] for item in progression["droppedEvidence"]}
    assert stages["c"] == "DOCUMENT_SELECTION"
    assert stages["b"] == "EVIDENCE_EXPANSION"
    assert stages["a"] == "CITATION_PRUNING"
    assert "content" not in str(progression)


def test_hard_direct_uses_hard_model_only_for_hard_tier() -> None:
    hard = initial_answer_escalation(
        policy="HARD_DIRECT",
        query_tier="hard",
        hard_model_available=True,
    )
    standard = initial_answer_escalation(
        policy="HARD_DIRECT",
        query_tier="standard",
        hard_model_available=True,
    )
    assert hard.use_hard_model is True
    assert hard.reason == "HARD_TIER"
    assert standard.use_hard_model is False


def test_grounding_failure_retries_once_when_policy_allows() -> None:
    retry = retry_answer_escalation(
        policy="ON_GROUNDING_FAILURE",
        failure_reason="GROUNDING_FAILURE",
        hard_model_available=True,
        already_escalated=False,
        has_evidence=True,
        is_valid_no_answer=False,
    )
    second = retry_answer_escalation(
        policy="ON_GROUNDING_FAILURE",
        failure_reason="GROUNDING_FAILURE",
        hard_model_available=True,
        already_escalated=True,
        has_evidence=True,
        is_valid_no_answer=False,
    )
    missing = retry_answer_escalation(
        policy="ON_GROUNDING_FAILURE",
        failure_reason="GROUNDING_FAILURE",
        hard_model_available=False,
        already_escalated=False,
        has_evidence=True,
        is_valid_no_answer=False,
    )
    assert retry.use_hard_model is True
    assert retry.attempt_count == 2
    assert second.use_hard_model is False
    assert missing.reason == "HARD_MODEL_UNAVAILABLE"


def test_valid_no_answer_does_not_escalate() -> None:
    decision = retry_answer_escalation(
        policy="HARD_OR_GROUNDING_FAILURE",
        failure_reason="GROUNDING_FAILURE",
        hard_model_available=True,
        already_escalated=False,
        has_evidence=True,
        is_valid_no_answer=True,
    )
    assert decision.use_hard_model is False
