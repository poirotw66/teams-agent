"""Vertex SA smoke preflight refuses keys and missing project/locations."""

from __future__ import annotations

import pytest

from agent_service.gemini_backend import GeminiConfigurationError, reset_gemini_backend_for_tests
from agent_service.gemini_errors import GeminiErrorClass, classify_gemini_error
from agent_service.vertex_sa_smoke import (
    EXIT_SKIP,
    main,
    preflight_vertex_sa_smoke,
)


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_gemini_backend_for_tests()
    for name in (
        "GEMINI_API_BACKEND",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "VERTEX_AI_PROJECT",
        "GCP_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEX_AI_CHAT_LOCATION",
        "VERTEX_AI_EMBEDDING_LOCATION",
        "VERTEX_AI_PDF_LOCATION",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_LOCATION",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_gemini_backend_for_tests()


def test_preflight_refuses_process_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "injected")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="refuses") as caught:
        preflight_vertex_sa_smoke()
    assert classify_gemini_error(caught.value) is GeminiErrorClass.CONFIGURATION_CONFLICT


def test_preflight_refuses_missing_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="VERTEX_AI_PROJECT"):
        preflight_vertex_sa_smoke()


def test_preflight_refuses_missing_chat_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="VERTEX_AI_CHAT_LOCATION"):
        preflight_vertex_sa_smoke()


def test_preflight_refuses_missing_embedding_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="VERTEX_AI_EMBEDDING_LOCATION"):
        preflight_vertex_sa_smoke()


def test_preflight_refuses_unapproved_global_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "global")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="unapproved P0 placeholder"):
        preflight_vertex_sa_smoke()


def test_preflight_accepts_explicit_project_and_locations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    config = preflight_vertex_sa_smoke()
    assert config.vertex_project == "proj-a"
    assert config.chat_location == "us"
    assert config.embedding_location == "us"


def test_cli_preflight_exits_nonzero_when_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "injected")
    assert main(["--preflight-only"]) == EXIT_SKIP
