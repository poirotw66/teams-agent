"""Dual-mode Gemini backend resolution and dotenv key policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.gemini_backend import (
    UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER,
    GeminiApiBackend,
    GeminiConfigurationError,
    assert_vertex_process_has_no_api_keys,
    load_dotenv_for_gemini_backend,
    peek_gemini_api_backend,
    require_developer_api_for_file_search,
    require_developer_api_key,
    reset_gemini_backend_for_tests,
    resolve_gemini_backend,
)
from agent_service.runtime_dotenv import load_runtime_dotenv, reset_runtime_dotenv_for_tests


@pytest.fixture(autouse=True)
def _reset_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_gemini_backend_for_tests()
    reset_runtime_dotenv_for_tests()
    for name in (
        "GEMINI_API_BACKEND",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_EVAL_API_KEY",
        "GOOGLE_EVAL_API_KEY",
        "VERTEX_AI_PROJECT",
        "GCP_PROJECT_ID",
        "VERTEX_AI_CHAT_LOCATION",
        "VERTEX_AI_EMBEDDING_LOCATION",
        "VERTEX_AI_PDF_LOCATION",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_gemini_backend_for_tests()
    reset_runtime_dotenv_for_tests()


def test_unset_backend_defaults_to_developer_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_BACKEND", raising=False)
    config = resolve_gemini_backend()
    assert config.backend is GeminiApiBackend.DEVELOPER_API
    assert config.is_developer_api


def test_invalid_backend_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "AUTO")
    with pytest.raises(GeminiConfigurationError, match="DEVELOPER_API, VERTEX_AI"):
        resolve_gemini_backend()


def test_vertex_resolution_is_process_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    first = resolve_gemini_backend()
    monkeypatch.setenv("GEMINI_API_BACKEND", "DEVELOPER_API")
    second = resolve_gemini_backend()
    assert first is second
    assert second.backend is GeminiApiBackend.VERTEX_AI
    assert second.vertex_project == "proj-a"
    assert second.embedding_location == "us"


def test_vertex_missing_location_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GCP_PROJECT_ID", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="VERTEX_AI_EMBEDDING_LOCATION"):
        resolve_gemini_backend()


def test_vertex_maps_single_gcp_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GCP_PROJECT_ID", "proj-from-gcp")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    config = resolve_gemini_backend()
    assert config.vertex_project == "proj-from-gcp"


def test_vertex_maps_single_google_cloud_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-from-adc-env")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    config = resolve_gemini_backend()
    assert config.vertex_project == "proj-from-adc-env"


def test_vertex_maps_when_project_aliases_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GCP_PROJECT_ID", "shared-proj")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "shared-proj")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    config = resolve_gemini_backend()
    assert config.vertex_project == "shared-proj"


def test_vertex_rejects_disagreeing_project_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GCP_PROJECT_ID", "proj-a")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-b")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="single explicit project"):
        resolve_gemini_backend()


def test_vertex_project_field_wins_over_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "explicit-proj")
    monkeypatch.setenv("GCP_PROJECT_ID", "other-proj")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "third-proj")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    config = resolve_gemini_backend()
    assert config.vertex_project == "explicit-proj"


def test_vertex_missing_project_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="VERTEX_AI_PROJECT"):
        resolve_gemini_backend()


def test_vertex_does_not_guess_locations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    with pytest.raises(GeminiConfigurationError, match="VERTEX_AI_CHAT_LOCATION"):
        resolve_gemini_backend()


def test_vertex_rejects_unapproved_global_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv(
        "VERTEX_AI_CHAT_LOCATION", UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER
    )
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="unapproved P0 placeholder"):
        resolve_gemini_backend()


def test_vertex_rejects_whitespace_only_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "   ")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    with pytest.raises(GeminiConfigurationError, match="VERTEX_AI_CHAT_LOCATION"):
        resolve_gemini_backend()


def test_vertex_rejects_unapproved_global_pdf_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    monkeypatch.setenv(
        "VERTEX_AI_PDF_LOCATION", UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER
    )
    with pytest.raises(GeminiConfigurationError, match="unapproved P0 placeholder"):
        resolve_gemini_backend()


def test_developer_api_ignores_unapproved_vertex_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "DEVELOPER_API")
    monkeypatch.setenv(
        "VERTEX_AI_CHAT_LOCATION", UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER
    )
    config = resolve_gemini_backend()
    assert config.backend is GeminiApiBackend.DEVELOPER_API
    assert config.chat_location is None


def test_vertex_dotenv_does_not_load_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_BACKEND", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_BACKEND=VERTEX_AI\n"
        "VERTEX_AI_PROJECT=proj-a\n"
        "VERTEX_AI_CHAT_LOCATION=us\n"
        "VERTEX_AI_EMBEDDING_LOCATION=us\n"
        "GEMINI_API_KEY=should-not-load\n"
        "GOOGLE_API_KEY=also-should-not-load\n",
        encoding="utf-8",
    )
    backend = load_dotenv_for_gemini_backend(dotenv_path=env_file)
    assert backend is GeminiApiBackend.VERTEX_AI
    import os

    assert os.environ.get("GEMINI_API_KEY") is None
    assert os.environ.get("GOOGLE_API_KEY") is None
    assert os.environ.get("VERTEX_AI_PROJECT") == "proj-a"


def test_vertex_injected_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GOOGLE_API_KEY", "injected")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    resolve_gemini_backend()
    with pytest.raises(GeminiConfigurationError, match="refuses"):
        assert_vertex_process_has_no_api_keys()


def test_developer_api_does_not_switch_because_adc_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "adc-project")
    monkeypatch.setenv("GEMINI_API_KEY", "dev-key")
    config = resolve_gemini_backend()
    assert config.backend is GeminiApiBackend.DEVELOPER_API
    assert require_developer_api_key() == "dev-key"


def test_resolution_is_process_fixed_and_ignores_later_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "DEVELOPER_API")
    first = resolve_gemini_backend()
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "later-project")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    second = resolve_gemini_backend()
    assert first.backend is GeminiApiBackend.DEVELOPER_API
    assert second.backend is GeminiApiBackend.DEVELOPER_API
    assert first is second


def test_file_search_service_rejects_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_service.gemini_file_search import GeminiFileSearchKnowledgeService

    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    resolve_gemini_backend()
    with pytest.raises(GeminiConfigurationError, match="not supported on VERTEX_AI"):
        GeminiFileSearchKnowledgeService(
            api_key="should-not-be-used",
            file_search_store="fileSearchStores/x",
        )


def test_file_search_client_requires_developer_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_service.gemini_file_search import GeminiFileSearchKnowledgeService

    service = GeminiFileSearchKnowledgeService(
        api_key=None,
        file_search_store="fileSearchStores/x",
    )
    with pytest.raises(GeminiConfigurationError, match="GEMINI_API_KEY"):
        service._get_client()


def test_file_search_rejected_when_dotenv_selects_vertex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_BACKEND", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_BACKEND=VERTEX_AI\n"
        "VERTEX_AI_PROJECT=proj-a\n"
        "VERTEX_AI_CHAT_LOCATION=us\n"
        "VERTEX_AI_EMBEDDING_LOCATION=us\n"
        "GEMINI_API_KEY=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(GeminiConfigurationError, match="not supported on VERTEX_AI"):
        require_developer_api_for_file_search()


def test_file_search_rejected_on_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-a")
    monkeypatch.setenv("VERTEX_AI_CHAT_LOCATION", "us")
    monkeypatch.setenv("VERTEX_AI_EMBEDDING_LOCATION", "us")
    resolve_gemini_backend()
    with pytest.raises(GeminiConfigurationError, match="not supported on VERTEX_AI"):
        require_developer_api_for_file_search()


def test_runtime_dotenv_excludes_keys_on_vertex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    monkeypatch.delenv("GEMINI_API_BACKEND", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_BACKEND=VERTEX_AI\n"
        "VERTEX_AI_PROJECT=proj-a\n"
        "VERTEX_AI_CHAT_LOCATION=us\n"
        "VERTEX_AI_EMBEDDING_LOCATION=us\n"
        "GEMINI_API_KEY=from-file\n",
        encoding="utf-8",
    )
    assert load_runtime_dotenv(dotenv_path=env_file) is True
    assert os.environ.get("GEMINI_API_KEY") is None
    assert peek_gemini_api_backend() is GeminiApiBackend.VERTEX_AI
