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
        "AGENT_MODEL",
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
        "MAX_CLARIFICATION_ROUNDS",
        "MAX_HISTORY_MESSAGES",
        "CONVERSATION_HISTORY_ROUNDS",
        "CONVERSATION_TIMEOUT_HOURS",
        "CONVERSATION_RETENTION_DAYS",
        "MAX_LLM_CALLS_PER_REQUEST",
        "MAX_RETRIEVAL_REWRITES",
        "KNOWLEDGE_SERVICE_MODE",
        "GEMINI_FILE_SEARCH_STORE",
        "GEMINI_FILE_SEARCH_MODEL",
        "GEMINI_FILE_SEARCH_ENFORCE_ACL",
        "RAG_REQUIRE_FILE_SEARCH_ACL",
        "KNOWLEDGE_BACKEND_ADMIN_ENABLED",
        "KNOWLEDGE_BACKEND_STATE_MODE",
        "KNOWLEDGE_BACKEND_STATE_COLLECTION",
        "TICKET_SERVICE_MODE",
        "TICKET_SERVICE_BASE_URL",
        "TICKET_SERVICE_TOKEN",
        "TICKET_SERVICE_TIMEOUT_SECONDS",
        "CONVERSATION_REPOSITORY_MODE",
        "CONVERSATION_STORE_PATH",
        "CONVERSATION_FIRESTORE_PROJECT",
        "CONVERSATION_FIRESTORE_DATABASE",
        "CONVERSATION_FIRESTORE_COLLECTION",
        "HANDOFF_REPOSITORY_MODE",
        "HANDOFF_STORE_PATH",
        "HANDOFF_FIRESTORE_PROJECT",
        "HANDOFF_FIRESTORE_DATABASE",
        "HANDOFF_FIRESTORE_COLLECTION",
        "HANDOFF_DEMO_TIMEOUT_HOURS",
        "HANDOFF_RETENTION_DAYS",
        "FAQ_PATH",
        "FAQ_RUNTIME_MODE",
        "AI_OPS_FAQ_STORE_MODE",
        "AI_OPS_FAQ_STORE_PATH",
        "AI_OPS_FAQ_FIRESTORE_PROJECT",
        "AI_OPS_FAQ_FIRESTORE_DATABASE",
        "AI_OPS_FAQ_FIRESTORE_COLLECTION_PREFIX",
        "FEEDBACK_ENABLED",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RAG_DATA_DIR", str(tmp_path))


def test_agent_model_loads_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("RAG_MODEL", "google_genai:gemini-3.5-flash-lite")
    monkeypatch.setenv("AGENT_MODEL", "google_genai:gemini-3.7-flash")

    settings = RagSettings.from_env()

    assert settings.model == "google_genai:gemini-3.5-flash-lite"
    assert settings.agent_model == "google_genai:gemini-3.7-flash"


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _minimal_env(monkeypatch, tmp_path)

    settings = RagSettings.from_env()

    assert settings.max_issues_per_message == 3
    assert settings.max_missing_info_per_issue == 2
    assert settings.max_clarification_rounds == 2
    assert settings.max_history_messages == 10
    assert settings.conversation_history_rounds == 5
    assert settings.conversation_timeout_hours == 24
    assert settings.conversation_retention_days == 730
    assert settings.max_llm_calls_per_request == 6
    assert settings.max_retrieval_rewrites == 1
    assert settings.knowledge_service_mode == "HYBRID"
    assert settings.gemini_file_search_store is None
    assert settings.knowledge_backend_state_mode == "MEMORY"
    assert settings.knowledge_backend_state_collection == "runtime_config"
    assert settings.ticket_service_mode == "DISABLED"
    assert settings.ticket_service_base_url is None
    assert settings.ticket_service_timeout_seconds == 10.0
    assert settings.conversation_repository_mode == "MEMORY"
    assert settings.conversation_store_path == (tmp_path / "conversations").resolve()
    # Firestore project/database default to whatever ADC resolves to.
    assert settings.conversation_firestore_project is None
    assert settings.conversation_firestore_database is None
    assert settings.conversation_firestore_collection == "conversations"
    assert settings.handoff_repository_mode == "MEMORY"
    assert settings.handoff_store_path == (tmp_path / "handoffs").resolve()
    assert settings.handoff_firestore_project is None
    assert settings.handoff_firestore_database is None
    assert settings.handoff_firestore_collection == "handoffs"
    assert settings.handoff_demo_timeout_hours == 24
    assert settings.handoff_retention_days == 730
    assert settings.faq_path == (tmp_path / "faq.json").resolve()
    assert settings.faq_runtime_mode == "LEGACY_JSON"
    assert settings.faq_governed_store_mode == "FILE"
    assert settings.faq_governed_store_path == (
        tmp_path / "ops" / "phase2" / "faqs.json"
    ).resolve()
    assert settings.faq_firestore_collection_prefix == "ai_ops_faq"
    assert settings.feedback_enabled is True
    assert settings.model is None
    assert settings.agent_model is None


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
        ("MAX_CLARIFICATION_ROUNDS", "0"),
        ("MAX_CLARIFICATION_ROUNDS", "4"),
        ("MAX_HISTORY_MESSAGES", "-1"),
        ("MAX_HISTORY_MESSAGES", "51"),
        ("CONVERSATION_HISTORY_ROUNDS", "0"),
        ("CONVERSATION_HISTORY_ROUNDS", "21"),
        ("CONVERSATION_TIMEOUT_HOURS", "0"),
        ("CONVERSATION_TIMEOUT_HOURS", "169"),
        ("CONVERSATION_RETENTION_DAYS", "0"),
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


@pytest.mark.parametrize(
    "env_name,value",
    [
        ("FAQ_RUNTIME_MODE", "AUTO"),
        ("AI_OPS_FAQ_STORE_MODE", "MEMORY"),
        ("AI_OPS_FAQ_FIRESTORE_COLLECTION_PREFIX", "faq/nested"),
    ],
)
def test_invalid_governed_faq_settings_raise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_name: str,
    value: str,
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv(env_name, value)

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_rag_require_file_search_acl_requires_enforcement_when_store_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("GEMINI_FILE_SEARCH_STORE", "fileSearchStores/example")
    monkeypatch.setenv("RAG_REQUIRE_FILE_SEARCH_ACL", "true")
    monkeypatch.setenv("GEMINI_FILE_SEARCH_ENFORCE_ACL", "false")

    with pytest.raises(ValueError, match="RAG_REQUIRE_FILE_SEARCH_ACL"):
        RagSettings.from_env()


def test_invalid_knowledge_backend_state_settings_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("KNOWLEDGE_BACKEND_STATE_MODE", "REDIS")
    with pytest.raises(ValueError):
        RagSettings.from_env()

    monkeypatch.setenv("KNOWLEDGE_BACKEND_STATE_MODE", "FIRESTORE")
    monkeypatch.setenv("KNOWLEDGE_BACKEND_STATE_COLLECTION", "config/nested")
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


def test_firestore_conversation_repository_mode_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """FIRESTORE needs no extra config: ADC supplies project and database."""
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CONVERSATION_REPOSITORY_MODE", "FIRESTORE")

    settings = RagSettings.from_env()

    assert settings.conversation_repository_mode == "FIRESTORE"
    assert settings.conversation_firestore_collection == "conversations"


def test_firestore_project_database_and_collection_are_configurable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CONVERSATION_REPOSITORY_MODE", "FIRESTORE")
    monkeypatch.setenv("CONVERSATION_FIRESTORE_PROJECT", "itr-aimasteryhub-lab")
    monkeypatch.setenv("CONVERSATION_FIRESTORE_DATABASE", "teams-agent")
    monkeypatch.setenv("CONVERSATION_FIRESTORE_COLLECTION", "poc_conversations")

    settings = RagSettings.from_env()

    assert settings.conversation_firestore_project == "itr-aimasteryhub-lab"
    assert settings.conversation_firestore_database == "teams-agent"
    assert settings.conversation_firestore_collection == "poc_conversations"


def test_nested_firestore_collection_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bad collection id must fail at startup, not on the first write."""
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CONVERSATION_REPOSITORY_MODE", "FIRESTORE")
    monkeypatch.setenv("CONVERSATION_FIRESTORE_COLLECTION", "conversations/nested")

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_blank_firestore_collection_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Blank means unset here, as it does for every other env var."""
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CONVERSATION_REPOSITORY_MODE", "FIRESTORE")
    monkeypatch.setenv("CONVERSATION_FIRESTORE_COLLECTION", "   ")

    settings = RagSettings.from_env()

    assert settings.conversation_firestore_collection == "conversations"


def test_blank_firestore_collection_rejected_when_constructed_directly(
    tmp_path: Path,
) -> None:
    """The env layer normalizes blanks away; validate() is the backstop."""
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
        conversation_repository_mode="FIRESTORE",
        conversation_firestore_collection="   ",
    )

    with pytest.raises(ValueError):
        settings.validate()


def test_feedback_enabled_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FEEDBACK_ENABLED", "false")

    settings = RagSettings.from_env()

    assert settings.feedback_enabled is False


def test_handoff_firestore_settings_are_configurable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("HANDOFF_REPOSITORY_MODE", "FIRESTORE")
    monkeypatch.setenv("HANDOFF_FIRESTORE_PROJECT", "itr-aimasteryhub-lab")
    monkeypatch.setenv("HANDOFF_FIRESTORE_DATABASE", "teams-agent")
    monkeypatch.setenv("HANDOFF_FIRESTORE_COLLECTION", "support_handoffs")
    monkeypatch.setenv("HANDOFF_DEMO_TIMEOUT_HOURS", "48")
    monkeypatch.setenv("HANDOFF_RETENTION_DAYS", "365")

    settings = RagSettings.from_env()

    assert settings.handoff_repository_mode == "FIRESTORE"
    assert settings.handoff_firestore_project == "itr-aimasteryhub-lab"
    assert settings.handoff_firestore_database == "teams-agent"
    assert settings.handoff_firestore_collection == "support_handoffs"
    assert settings.handoff_demo_timeout_hours == 48
    assert settings.handoff_retention_days == 365


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("HANDOFF_REPOSITORY_MODE", "REDIS"),
        ("HANDOFF_FIRESTORE_COLLECTION", "handoffs/nested"),
        ("HANDOFF_DEMO_TIMEOUT_HOURS", "0"),
        ("HANDOFF_RETENTION_DAYS", "0"),
    ],
)
def test_invalid_handoff_settings_raise(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_name: str,
    value: str,
) -> None:
    _minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv(env_name, value)

    with pytest.raises(ValueError):
        RagSettings.from_env()


def test_blank_handoff_collection_rejected_when_constructed_directly(
    tmp_path: Path,
) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index.json",
        handoff_repository_mode="FIRESTORE",
        handoff_firestore_collection="   ",
    )

    with pytest.raises(ValueError):
        settings.validate()


def test_direct_construction_still_works_with_defaults(tmp_path: Path) -> None:
    settings = RagSettings(
        data_dir=tmp_path,
        index_path=tmp_path / "index" / "chunks.json",
    )

    assert settings.max_issues_per_message == 3
    assert settings.ticket_service_mode == "DISABLED"
    assert settings.conversation_store_path is None
    assert settings.handoff_store_path is None
    assert settings.faq_path is None
