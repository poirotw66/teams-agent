"""Tests for RAG role-specific model resolution."""

from __future__ import annotations

from dataclasses import replace

from agent_service.rag_models import (
    apply_governance_model_override,
    build_rag_model_bundle,
    resolve_rag_model_ids,
    selection_audit_event,
)
from agent_service.settings import RagSettings


def _settings(**overrides: object) -> RagSettings:
    base = RagSettings.from_env()
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_only_rag_model_shared_across_roles() -> None:
    ids = resolve_rag_model_ids(
        _settings(
            model="google_genai:gemini-3.1-flash-lite",
            rag_answer_model=None,
            rag_relevance_model=None,
            rag_rewrite_model=None,
            rag_hard_answer_model=None,
        )
    )
    assert ids.answer == "google_genai:gemini-3.1-flash-lite"
    assert ids.relevance == ids.answer
    assert ids.rewrite == ids.answer
    assert ids.hard_answer is None
    assert ids.escalation_policy == "OFF"


def test_answer_model_inherited_by_relevance_and_rewrite() -> None:
    ids = resolve_rag_model_ids(
        _settings(
            model="google_genai:legacy",
            rag_answer_model="google_genai:answer",
            rag_relevance_model=None,
            rag_rewrite_model=None,
        )
    )
    assert ids.answer == "google_genai:answer"
    assert ids.relevance == "google_genai:answer"
    assert ids.rewrite == "google_genai:answer"
    assert ids.answer_source == "environment"
    assert ids.relevance_source == "fallback"


def test_every_role_configured_independently() -> None:
    ids = resolve_rag_model_ids(
        _settings(
            model="google_genai:legacy",
            rag_answer_model="google_genai:answer",
            rag_relevance_model="google_genai:relevance",
            rag_rewrite_model="google_genai:rewrite",
            rag_hard_answer_model="google_genai:hard",
            rag_answer_escalation_policy="ON_GROUNDING_FAILURE",
        )
    )
    assert ids.answer == "google_genai:answer"
    assert ids.relevance == "google_genai:relevance"
    assert ids.rewrite == "google_genai:rewrite"
    assert ids.hard_answer == "google_genai:hard"
    assert ids.escalation_policy == "ON_GROUNDING_FAILURE"


def test_governance_override_changes_only_intended_role() -> None:
    ids = resolve_rag_model_ids(
        _settings(
            rag_answer_model="google_genai:answer",
            rag_relevance_model="google_genai:relevance",
            rag_rewrite_model="google_genai:rewrite",
        )
    )
    overridden = apply_governance_model_override(
        ids, role="relevance", model_id="google_genai:gov-relevance"
    )
    assert overridden.answer == "google_genai:answer"
    assert overridden.relevance == "google_genai:gov-relevance"
    assert overridden.relevance_source == "governance"
    assert overridden.rewrite == "google_genai:rewrite"
    event = selection_audit_event(overridden, role="relevance")
    assert event["source"] == "governance"
    assert event["selectedModel"] == "google_genai:gov-relevance"


def test_build_rag_model_bundle_reuses_identical_model_ids() -> None:
    built: list[str] = []

    def fake_build(model_id: str, temperature: float = 0.0):
        built.append(model_id)
        return object()

    bundle = build_rag_model_bundle(
        _settings(
            rag_answer_model="google_genai:shared",
            rag_relevance_model="google_genai:shared",
            rag_rewrite_model="google_genai:shared",
            rag_hard_answer_model=None,
        ),
        build_chat_model=fake_build,
    )
    assert built == ["google_genai:shared"]
    assert bundle.answer is bundle.relevance is bundle.rewrite
    assert bundle.hard_answer is None


def test_build_rag_model_bundle_applies_governance_overrides() -> None:
    built: list[str] = []

    def fake_build(model_id: str, temperature: float = 0.0):
        built.append(model_id)
        return object()

    bundle = build_rag_model_bundle(
        _settings(
            rag_answer_model="google_genai:answer",
            rag_relevance_model="google_genai:relevance",
            rag_rewrite_model="google_genai:rewrite",
        ),
        build_chat_model=fake_build,
        governance_overrides={"relevance": "google_genai:gov-relevance"},
    )
    assert bundle.ids is not None
    assert bundle.ids.relevance == "google_genai:gov-relevance"
    assert bundle.ids.relevance_source == "governance"
    assert bundle.ids.answer == "google_genai:answer"
    assert "google_genai:gov-relevance" in built
