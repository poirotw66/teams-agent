"""Dual-mode Gemini chat/embedding construction contracts."""

from __future__ import annotations

from typing import Any

import pytest

from agent_service.gemini_backend import (
    GeminiConfigurationError,
    reset_gemini_backend_for_tests,
    resolve_gemini_backend,
)
from agent_service.gemini_clients import (
    build_embeddings,
    build_genai_sdk_client_kwargs,
    chat_model_init_kwargs,
    embedding_payloads_compatible,
    filter_chat_model_kwargs,
    provenance_from_index_payload,
)
from agent_service.gemini_errors import GeminiErrorClass, classify_gemini_error
from agent_service.graph import build_chat_model


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_gemini_backend_for_tests()
    for name in (
        "GEMINI_API_BACKEND",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "VERTEX_AI_PROJECT",
        "GCP_PROJECT_ID",
        "VERTEX_AI_CHAT_LOCATION",
        "VERTEX_AI_EMBEDDING_LOCATION",
        "VERTEX_AI_PDF_LOCATION",
        "GOOGLE_GENAI_USE_VERTEXAI",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_gemini_backend_for_tests()


def _vertex_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-vertex")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_PDF_LOCATION", "us")


def test_developer_api_chat_kwargs_use_key_not_vertex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "dev-key")
    captured: dict[str, Any] = {}

    def fake_init(model_name: str, **kwargs: Any) -> str:
        captured["model_name"] = model_name
        captured["kwargs"] = kwargs
        return "chat-client"

    monkeypatch.setattr("agent_service.graph.init_chat_model", fake_init)
    model = build_chat_model("google_genai:gemini-3.1-flash-lite", temperature=0.0)
    assert model == "chat-client"
    assert captured["model_name"] == "google_genai:gemini-3.1-flash-lite"
    assert "vertexai" not in captured["kwargs"]
    assert "project" not in captured["kwargs"]
    assert captured["kwargs"]["temperature"] == 0.0


def test_vertex_chat_kwargs_use_vertexai_project_location_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _vertex_env(monkeypatch)
    kwargs = chat_model_init_kwargs("google_genai:gemini-3.1-flash-lite", temperature=0.0)
    assert kwargs["vertexai"] is True
    assert kwargs["project"] == "proj-vertex"
    assert kwargs["location"] == "us"
    assert "google_api_key" not in kwargs
    assert "api_key" not in kwargs


def test_vertex_injected_key_blocks_chat_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _vertex_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "injected")
    with pytest.raises(GeminiConfigurationError, match="refuses"):
        chat_model_init_kwargs("google_genai:gemini-3.1-flash-lite")


def test_vertex_strips_temperature_on_gemini_38(monkeypatch: pytest.MonkeyPatch) -> None:
    _vertex_env(monkeypatch)
    kwargs = chat_model_init_kwargs("google_genai:gemini-3.8-flash", temperature=0.0)
    assert "temperature" not in kwargs
    assert kwargs["vertexai"] is True


def test_developer_api_keeps_temperature_on_gemini_38(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "dev-key")
    kwargs = filter_chat_model_kwargs(
        "google_genai:gemini-3.8-flash",
        {"temperature": 0.0},
        backend=resolve_gemini_backend().backend,
    )
    assert kwargs["temperature"] == 0.0


def test_non_gemini_provider_kwargs_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-vertex")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    kwargs = chat_model_init_kwargs("openai:gpt-4.1-mini", temperature=0.2)
    assert kwargs == {"temperature": 0.2}


def test_vertex_embeddings_pass_explicit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    _vertex_env(monkeypatch)
    captured: dict[str, Any] = {}

    class FakeEmbeddings:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "langchain_google_genai.GoogleGenerativeAIEmbeddings",
        FakeEmbeddings,
    )
    client = build_embeddings("google_genai:gemini-embedding-2")
    assert isinstance(client, FakeEmbeddings)
    assert captured["vertexai"] is True
    assert captured["project"] == "proj-vertex"
    assert captured["location"] == "us"
    assert "google_api_key" not in captured


def test_developer_api_embeddings_do_not_set_vertex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "dev-key")
    captured: dict[str, Any] = {}

    class FakeEmbeddings:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "langchain_google_genai.GoogleGenerativeAIEmbeddings",
        FakeEmbeddings,
    )
    build_embeddings("google_genai:gemini-embedding-2")
    assert "vertexai" not in captured
    assert captured["model"] == "gemini-embedding-2"


def test_non_gemini_embeddings_use_init_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, Any] = {}

    def fake_init(model_name: str) -> str:
        called["model_name"] = model_name
        return "openai-embeddings"

    monkeypatch.setattr("langchain.embeddings.init_embeddings", fake_init)
    result = build_embeddings("openai:text-embedding-3-small")
    assert result == "openai-embeddings"
    assert called["model_name"] == "openai:text-embedding-3-small"


def test_vertex_sdk_client_kwargs_have_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _vertex_env(monkeypatch)
    kwargs = build_genai_sdk_client_kwargs(require_pdf_location=True)
    assert kwargs == {
        "vertexai": True,
        "project": "proj-vertex",
        "location": "us",
    }


def test_old_release_is_not_compatible_by_model_id_alone() -> None:
    payload = {
        "embeddingModel": "google_genai:gemini-embedding-2",
        "chunks": [{"vector": [0.1, 0.2]}],
    }
    assert embedding_payloads_compatible(payload, "google_genai:gemini-embedding-2") is False


def test_complete_provenance_must_match_backend_and_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _vertex_env(monkeypatch)
    payload = {
        "embeddingModel": "google_genai:gemini-embedding-2",
        "embeddingBackend": "DEVELOPER_API",
        "embeddingDimensions": 2,
        "chunks": [{"vector": [0.1, 0.2]}],
    }
    assert embedding_payloads_compatible(payload, "google_genai:gemini-embedding-2") is False
    index = provenance_from_index_payload(
        {
            **payload,
            "embeddingBackend": "VERTEX_AI",
            "embeddingVertexLocation": "us",
        }
    )
    assert index.has_complete_fields()


def test_classify_missing_key_and_iam() -> None:
    assert (
        classify_gemini_error(GeminiConfigurationError("requires GEMINI_API_KEY"))
        is GeminiErrorClass.MISSING_API_KEY
    )
    assert (
        classify_gemini_error(RuntimeError("403 PermissionDenied on aiplatform"))
        is GeminiErrorClass.IAM_DENIED
    )
    assert (
        classify_gemini_error(RuntimeError("429 resource_exhausted quota exceeded"))
        is GeminiErrorClass.QUOTA_EXCEEDED
    )
