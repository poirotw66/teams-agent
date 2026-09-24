"""Tests for eval vs Playground Gemini credential isolation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_service.eval_credentials import (
    apply_eval_gemini_credentials,
    eval_gemini_report_fields,
)
from agent_service.gemini_backend import GeminiConfigurationError, reset_gemini_backend_for_tests


@pytest.fixture(autouse=True)
def _clear_gemini_env(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_gemini_backend_for_tests()
    for name in (
        "GEMINI_EVAL_API_KEY",
        "GOOGLE_EVAL_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_BACKEND",
        "VERTEX_AI_PROJECT",
        "VERTEX_AI_CHAT_LOCATION",
        "VERTEX_AI_EMBEDDING_LOCATION",
        "VERTEX_AI_EVAL_PROJECT",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_gemini_backend_for_tests()


def test_apply_eval_key_overrides_runtime_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "playground-key")
    monkeypatch.setenv("GEMINI_EVAL_API_KEY", "eval-key")

    source = apply_eval_gemini_credentials()

    assert source == "GEMINI_EVAL_API_KEY"
    assert os.environ["GEMINI_API_KEY"] == "eval-key"
    assert os.environ["GOOGLE_API_KEY"] == "eval-key"


def test_apply_falls_back_to_playground_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "playground-key")

    source = apply_eval_gemini_credentials()

    assert source == "GEMINI_API_KEY"
    assert os.environ["GEMINI_API_KEY"] == "playground-key"


def test_apply_raises_when_no_key_configured() -> None:
    with pytest.raises(RuntimeError, match="GEMINI_EVAL_API_KEY"):
        apply_eval_gemini_credentials()


def test_apply_loads_eval_key_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=playground-from-file\nGEMINI_EVAL_API_KEY=eval-from-file\n",
        encoding="utf-8",
    )

    source = apply_eval_gemini_credentials(dotenv_path=env_file)

    assert source == "GEMINI_EVAL_API_KEY"
    assert os.environ["GEMINI_API_KEY"] == "eval-from-file"
    assert os.environ["GOOGLE_API_KEY"] == "eval-from-file"


def test_vertex_eval_uses_adc_and_never_falls_back_to_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "eval-proj")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")

    source = apply_eval_gemini_credentials()

    assert source == "VERTEX_AI_ADC"
    assert os.environ.get("GEMINI_API_KEY") in {None, ""}
    assert os.environ.get("GOOGLE_API_KEY") in {None, ""}
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "true"
    assert os.environ["GOOGLE_CLOUD_PROJECT"] == "eval-proj"


def test_vertex_eval_refuses_injected_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "eval-proj")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    monkeypatch.setenv("GEMINI_API_KEY", "eval-key")

    with pytest.raises(GeminiConfigurationError, match="refuses"):
        apply_eval_gemini_credentials()


def test_eval_report_fields_record_backend_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "eval-proj")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "eu")
    apply_eval_gemini_credentials()
    fields = eval_gemini_report_fields()
    assert fields == {
        "geminiBackend": "VERTEX_AI",
        "vertexProject": "eval-proj",
        "vertexChatLocation": "us",
        "vertexEmbeddingLocation": "eu",
    }
    assert "key" not in json.dumps(fields).lower()
