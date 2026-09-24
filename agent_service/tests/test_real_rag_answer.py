"""REAL_RAG answer extraction: Gemini list/dict content becomes a string."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ai_ops_backoffice.evaluation_domain.real_rag_answer import (
    invoke_chat_model_answer,
    normalize_gemini_message_content,
    normalize_model_invoker_result,
)
from ai_ops_backoffice.evaluation_domain.runner_models import (
    TargetExecutionInput,
    TargetManifest,
)


def test_normalize_gemini_message_content_joins_list_text_parts() -> None:
    content = [
        {"type": "text", "text": "Password reset uses "},
        {"type": "text", "text": "SSO self-service."},
    ]
    normalized = normalize_gemini_message_content(content)
    assert normalized == "Password reset uses SSO self-service."
    assert normalized.lower() == "password reset uses sso self-service."


def test_normalize_gemini_message_content_handles_dict_and_string() -> None:
    assert (
        normalize_gemini_message_content({"type": "text", "text": "Vertex answer"})
        == "Vertex answer"
    )
    assert normalize_gemini_message_content("Developer API answer") == "Developer API answer"


def test_invoke_chat_model_answer_normalizes_list_valued_content() -> None:
    class _ListContentChat:
        def invoke(self, _messages: list[Any]) -> SimpleNamespace:
            return SimpleNamespace(
                content=[
                    {"type": "thinking", "thinking": "internal"},
                    {"type": "text", "text": "Use SSO to reset the password."},
                ],
                usage_metadata={"total_tokens": 12},
                id="resp-list-1",
                response_metadata={},
            )

    answer, tokens, cost, tools, req_id = invoke_chat_model_answer(
        chat_model=_ListContentChat(),
        query="How do I reset my password?",
        manifest=TargetManifest(
            target_id="t1",
            target_side="CANDIDATE",
            manifest_hash="h",
            model_id="google_genai:gemini-3.8-flash",
        ),
        sanitized_input=TargetExecutionInput(query="How do I reset my password?"),
        retrieved_evidence=[{"title": "SSO", "content": "Use SSO self-service."}],
        conversation_history=None,
        prompt_template="Question: {question}\nContext: {context}",
        priced_cost=lambda **_kwargs: 0.001,
    )
    assert isinstance(answer, str)
    assert answer == "Use SSO to reset the password."
    assert answer.lower() == "use sso to reset the password."
    assert tokens == 12
    assert cost == 0.001
    assert tools == []
    assert req_id == "resp-list-1"


def test_normalize_model_invoker_result_joins_list_answer() -> None:
    normalized = normalize_model_invoker_result(
        ([{"type": "text", "text": "Joined from invoker"}], 8, 0.0, [], "req-1")
    )
    assert normalized is not None
    answer, tokens, cost, tools, req_id = normalized
    assert answer == "Joined from invoker"
    assert tokens == 8
    assert cost == 0.0
    assert tools == []
    assert req_id == "req-1"
