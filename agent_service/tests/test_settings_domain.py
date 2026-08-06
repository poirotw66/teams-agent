from pathlib import Path

import pytest

from agent_service.settings import RagSettings


def _minimal_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Clear every RagSettings-related env var, then point RAG_DATA_DIR at tmp_path."""
    names = [
        "RAG_DATA_DIR",
        "RAG_INDEX_PATH",
        "RAG_AUTO_BUILD_INDEX",
        "RAG_MODEL",
        "RAG_EMBEDDING_MODEL",
        "RAG_TOP_K",
        "RAG_MIN_SCORE",
        "RAG_MAX_REWRITES",
        "RAG_CHUNK_SIZE",
        "RAG_CHUNK_OVERLAP",
        "RAG_ALLOWED_TENANTS",
        "RAG_SOURCE_BASE_URL",
        "AGENT_SERVICE_TOKEN",
        "RAG_MAX_IMAGES",
        "MAX_ISSUES_PER_MESSAGE",
        "MAX_MISSING_INFO_PER_ISSUE",
        "MAX_HISTORY_MESSAGES",
        "CONVERSATION_HISTORY_ROUNDS",
        "CONVERSATION_TIMEOUT_HOURS",
        "MAX_LLM_CALLS_PER_REQUEST",
        "MAX_RETRIEVAL_REWRITES",
        "KNOWLEDGE_SERVICE_MODE",
        "GEMINI_FILE_SEARCH_STORE",
        "TICKET_SERVICE_MODE",
        "TICKET_SERVICE_BASE_URL",
        "TICKET_SERVICE_TOKEN",
        "TICKET_SERVICE_TIMEOUT_SECONDS",
        "CONVERSATION_REPOSITORY_MODE",
        "CONVERSATION_STORE_PATH",
        "FAQ_PATH",
        "FEEDBACK_ENABLED",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path))


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _minimal_env(monkeypatch, tmp_path)

    settings = RagSettings.from_env()

    assert settings.max_issues_per_message == 3
    assert settings.max_missing_info_per_issue == 2
    assert settings.max_history_messages == 10
    assert settings.conversation_history_rounds == 5
    assert settings.conversation_timeout_hours == 24
    assert settings.max_llm_calls_per_request == 5
    assert settings.max_retrieval_rewrites == 1
    assert settings.knowledge_service_mode == "HYBRID"
    assert settings.gemini_file_search_store is None
    assert settings.ticket_service_mode == "DISABLED"
    assert settings.ticket_service_base_url is None
    assert settings.ticket_service_timeout_seconds == 10.0
    assert settings.conversation_repository_mode == "MEMORY"
    assert settings.conversation_store_path == (tmp_path / "conversations").resolve()
    assert settings.faq_path == (tmp_path / "faq.json").resolve()
    assert settings.feedback_enabled is True


def test_max_retrieval_rewrites_falls_back_to_rag_max_rewrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("RAG_MAX_REWRITES", "2")

    settings = RagSettings.from_env()

    assert settings.max_rewrites == 2
    assert settings.max_retrieval_rewrites == 2


def test_max_retrieval_rewrites_explicit_overrides_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("RAG_MAX_REWRITES", "2")
    monkeypatch.setenv("MAX_RETRIEVAL_REWRITES", "0")

    settings = RagSettings.from_env()

    assert settings.max_retrieval_rewrites == 0


@pytest.mark.parametrize(
    "env_name, value",
    [
        ("MAX_ISSUES_PER_MESSAGE", "0"),
        ("MAX_ISSUES_PER_MESSAGE", "6"),
        ("MAX_MISSING_INFO_PER_ISSUE", "0"),
        ("MAX_MISSING_INFO_PER_ISSUE", "4"),
        ("MAX_HISTORY_MESSAGES", "-1"),
        ("MAX_HISTORY_MESSAGES", "51"),
        ("CONVERSATION_HISTORY_ROUNDS", "0"),
        ("CONVERSATION_HISTORY_ROUNDS", "21"),
        ("CONVERSATION_TIMEOUT_HOURS", "0"),
        ("CONVERSATION_TIMEOUT_HOURS", "169"),
        ("MAX_LLM_CALLS_PER_REQUEST", "0"),
        ("MAX_LLM_CALLS_PER_REQUEST", "21"),
        ("MAX_RETRIEVAL_REWRITES", "-1"),
        ("MAX_RETRIEVAL_REWRITES", "4"),
    ],
)
def test_out_of_range_bounds_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env_name: str, value: str
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv(env_name, value)

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_ticket_service_timeout_out_of_range_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TICKET_SERVICE_TIMEOUT_SECONDS", "0.5")

    with pytest.raises(ValueError):
        RagSettings.from_env()

    monkeypatch.setenv("TICKET_SERVICE_TIMEOUT_SECONDS", "61")

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_invalid_knowledge_service_mode_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_MODE", "PINECONE")

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_invalid_ticket_service_mode_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TICKET_SERVICE_MODE", "SOAP")

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_ticket_service_mode_http_without_base_url_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TICKET_SERVICE_MODE", "HTTP")

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_ticket_service_mode_http_with_non_http_url_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TICKET_SERVICE_MODE", "HTTP")
    monkeypatch.setenv("TICKET_SERVICE_BASE_URL", "ftp://example.internal")

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_ticket_service_mode_http_with_valid_base_url_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TICKET_SERVICE_MODE", "HTTP")
    monkeypatch.setenv("TICKET_SERVICE_BASE_URL", "https://example.internal")

    settings = RagSettings.from_env()

    assert settings.ticket_service_mode == "HTTP"
    assert settings.ticket_service_base_url == "https://example.internal"


def test_invalid_conversation_repository_mode_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CONVERSATION_REPOSITORY_MODE", "MONGO")

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_feedback_enabled_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FEEDBACK_ENABLED", "false")

    settings = RagSettings.from_env()

    assert settings.feedback_enabled is False


def test_direct_construction_still_works_with_defaults(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
    )

    assert settings.max_issues_per_message == 3
    assert settings.ticket_service_mode == "DISABLED"
    assert settings.conversation_store_path is None
    assert settings.faq_path is None
