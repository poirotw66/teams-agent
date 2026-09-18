"""Validation helpers for AgentServiceSettings.validate."""

from __future__ import annotations

from typing import Any, Protocol


class _AgentSettingsView(Protocol):
    top_k: int
    min_score: float
    max_rewrites: int
    chunk_size: int
    chunk_overlap: int
    max_images: int
    max_issues_per_message: int
    max_missing_info_per_issue: int
    max_history_messages: int
    conversation_history_rounds: int
    max_clarification_rounds: int
    conversation_timeout_hours: int
    conversation_retention_days: int
    supervisor_terminal_confidence: float
    max_llm_calls_per_request: int
    max_retrieval_rewrites: int
    faq_runtime_mode: str
    faq_governed_store_mode: str
    faq_firestore_collection_prefix: str
    prompt_runtime_mode: str
    prompt_governance_store_mode: str
    prompt_governance_firestore_collection: str
    knowledge_service_mode: str
    rag_require_file_search_acl: bool
    gemini_file_search_store: Any
    gemini_file_search_enforce_acl: bool
    knowledge_backend_state_mode: str
    knowledge_backend_state_collection: str
    ticket_service_mode: str
    ticket_service_base_url: str | None
    ticket_service_timeout_seconds: float
    ticket_request_dedupe_mode: str
    ticket_request_dedupe_collection: str
    ticket_request_dedupe_retention_days: int
    conversation_repository_mode: str
    conversation_firestore_collection: str
    handoff_repository_mode: str
    handoff_firestore_collection: str
    handoff_demo_timeout_hours: int
    handoff_retention_days: int
    knowledge_release_mode: str
    knowledge_release_store_mode: str
    knowledge_release_gcs_bucket: str | None
    deployment_environment: str
    usd_twd_exchange_rate: float


def validate_rag_and_conversation_limits(settings: _AgentSettingsView) -> None:
    if settings.top_k < 1 or settings.top_k > 20:
        raise ValueError("RAG_TOP_K must be between 1 and 20.")
    if not 0 <= settings.min_score <= 1:
        raise ValueError("RAG_MIN_SCORE must be between 0 and 1.")
    if settings.max_rewrites < 0 or settings.max_rewrites > 3:
        raise ValueError("RAG_MAX_REWRITES must be between 0 and 3.")
    if settings.chunk_size < 200:
        raise ValueError("RAG_CHUNK_SIZE must be at least 200.")
    if settings.chunk_overlap < 0 or settings.chunk_overlap >= settings.chunk_size:
        raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE.")
    if settings.max_images < 0 or settings.max_images > 4:
        raise ValueError("RAG_MAX_IMAGES must be between 0 and 4.")
    if not 1 <= settings.max_issues_per_message <= 5:
        raise ValueError("MAX_ISSUES_PER_MESSAGE must be between 1 and 5.")
    if not 1 <= settings.max_missing_info_per_issue <= 3:
        raise ValueError("MAX_MISSING_INFO_PER_ISSUE must be between 1 and 3.")
    if not 0 <= settings.max_history_messages <= 50:
        raise ValueError("MAX_HISTORY_MESSAGES must be between 0 and 50.")
    if not 1 <= settings.conversation_history_rounds <= 20:
        raise ValueError("CONVERSATION_HISTORY_ROUNDS must be between 1 and 20.")
    if not 1 <= settings.max_clarification_rounds <= 3:
        raise ValueError("MAX_CLARIFICATION_ROUNDS must be between 1 and 3.")
    if not 1 <= settings.conversation_timeout_hours <= 168:
        raise ValueError("CONVERSATION_TIMEOUT_HOURS must be between 1 and 168.")
    if not 1 <= settings.conversation_retention_days <= 365:
        raise ValueError("CONVERSATION_RETENTION_DAYS must be between 1 and 365.")
    if not 0.5 <= settings.supervisor_terminal_confidence <= 1:
        raise ValueError("SUPERVISOR_TERMINAL_CONFIDENCE must be between 0.5 and 1.")
    if not 1 <= settings.max_llm_calls_per_request <= 20:
        raise ValueError("MAX_LLM_CALLS_PER_REQUEST must be between 1 and 20.")
    if not 0 <= settings.max_retrieval_rewrites <= 3:
        raise ValueError("MAX_RETRIEVAL_REWRITES must be between 0 and 3.")


def validate_faq_and_prompt_modes(settings: _AgentSettingsView) -> None:
    if settings.faq_runtime_mode not in {"LEGACY_JSON", "GOVERNED"}:
        raise ValueError("FAQ_RUNTIME_MODE must be one of LEGACY_JSON or GOVERNED.")
    if settings.faq_governed_store_mode not in {"FILE", "FIRESTORE"}:
        raise ValueError("AI_OPS_FAQ_STORE_MODE must be one of FILE or FIRESTORE.")
    if not settings.faq_firestore_collection_prefix.strip():
        raise ValueError("AI_OPS_FAQ_FIRESTORE_COLLECTION_PREFIX must not be blank.")
    if "/" in settings.faq_firestore_collection_prefix:
        raise ValueError("AI_OPS_FAQ_FIRESTORE_COLLECTION_PREFIX must not contain '/'.")
    if settings.prompt_runtime_mode not in {"CODE_BASELINE", "GOVERNED"}:
        raise ValueError("PROMPT_RUNTIME_MODE must be one of CODE_BASELINE or GOVERNED.")
    if settings.prompt_governance_store_mode not in {
        "FILE",
        "FIRESTORE",
        "FIRESTORE_SHARDED",
        "FIRESTORE_SPLIT",
    }:
        raise ValueError(
            "AI_OPS_GOVERNANCE_STORE_MODE must be one of FILE, FIRESTORE, "
            "FIRESTORE_SHARDED, or FIRESTORE_SPLIT."
        )
    if not settings.prompt_governance_firestore_collection.strip():
        raise ValueError("AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION must not be blank.")
    if "/" in settings.prompt_governance_firestore_collection:
        raise ValueError("AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION must not contain '/'.")


def validate_knowledge_and_ticket_modes(settings: _AgentSettingsView) -> None:
    if settings.knowledge_service_mode not in {"HYBRID", "GEMINI_FILE_SEARCH"}:
        raise ValueError("KNOWLEDGE_SERVICE_MODE must be one of HYBRID or GEMINI_FILE_SEARCH.")
    if (
        settings.rag_require_file_search_acl
        and settings.gemini_file_search_store
        and not settings.gemini_file_search_enforce_acl
    ):
        raise ValueError(
            "RAG_REQUIRE_FILE_SEARCH_ACL=true requires GEMINI_FILE_SEARCH_ENFORCE_ACL=true "
            "when GEMINI_FILE_SEARCH_STORE is configured."
        )
    if settings.knowledge_backend_state_mode not in {"MEMORY", "FIRESTORE"}:
        raise ValueError("KNOWLEDGE_BACKEND_STATE_MODE must be one of MEMORY or FIRESTORE.")
    if not settings.knowledge_backend_state_collection.strip():
        raise ValueError("KNOWLEDGE_BACKEND_STATE_COLLECTION must not be blank.")
    if "/" in settings.knowledge_backend_state_collection:
        raise ValueError("KNOWLEDGE_BACKEND_STATE_COLLECTION must not contain '/'.")
    if settings.ticket_service_mode not in {"DISABLED", "HTTP"}:
        raise ValueError("TICKET_SERVICE_MODE must be one of DISABLED or HTTP.")
    if settings.ticket_service_mode == "HTTP":
        if not settings.ticket_service_base_url:
            raise ValueError("TICKET_SERVICE_BASE_URL is required when TICKET_SERVICE_MODE=HTTP.")
        if not settings.ticket_service_base_url.startswith(("http://", "https://")):
            raise ValueError("TICKET_SERVICE_BASE_URL must be an http(s) URL.")
    if not 1 <= settings.ticket_service_timeout_seconds <= 60:
        raise ValueError("TICKET_SERVICE_TIMEOUT_SECONDS must be between 1 and 60.")
    if settings.ticket_request_dedupe_mode not in {"MEMORY", "FIRESTORE"}:
        raise ValueError("TICKET_REQUEST_DEDUPE_MODE must be one of MEMORY or FIRESTORE.")
    if not settings.ticket_request_dedupe_collection.strip():
        raise ValueError("TICKET_REQUEST_DEDUPE_COLLECTION must not be blank.")
    if "/" in settings.ticket_request_dedupe_collection:
        raise ValueError("TICKET_REQUEST_DEDUPE_COLLECTION must not contain '/'.")
    if not 1 <= settings.ticket_request_dedupe_retention_days <= 365:
        raise ValueError("TICKET_REQUEST_DEDUPE_RETENTION_DAYS must be between 1 and 365.")


def validate_persistence_and_release_modes(settings: _AgentSettingsView) -> None:
    if settings.conversation_repository_mode not in {"MEMORY", "FILE", "FIRESTORE"}:
        raise ValueError("CONVERSATION_REPOSITORY_MODE must be one of MEMORY, FILE or FIRESTORE.")
    if not settings.conversation_firestore_collection.strip():
        raise ValueError("CONVERSATION_FIRESTORE_COLLECTION must not be blank.")
    if "/" in settings.conversation_firestore_collection:
        raise ValueError("CONVERSATION_FIRESTORE_COLLECTION must not contain '/'.")
    if settings.handoff_repository_mode not in {"MEMORY", "FILE", "FIRESTORE"}:
        raise ValueError("HANDOFF_REPOSITORY_MODE must be one of MEMORY, FILE or FIRESTORE.")
    if not settings.handoff_firestore_collection.strip():
        raise ValueError("HANDOFF_FIRESTORE_COLLECTION must not be blank.")
    if "/" in settings.handoff_firestore_collection:
        raise ValueError("HANDOFF_FIRESTORE_COLLECTION must not contain '/'.")
    if settings.handoff_demo_timeout_hours < 1:
        raise ValueError("HANDOFF_DEMO_TIMEOUT_HOURS must be at least 1.")
    if not 1 <= settings.handoff_retention_days <= 365:
        raise ValueError("HANDOFF_RETENTION_DAYS must be between 1 and 365.")
    if settings.knowledge_release_mode not in {"BUNDLED", "PORTAL", "AUTO"}:
        raise ValueError("KNOWLEDGE_RELEASE_MODE must be one of BUNDLED, PORTAL, or AUTO.")
    if settings.knowledge_release_store_mode not in {"FILE", "GCS"}:
        raise ValueError("KNOWLEDGE_RELEASE_STORE_MODE must be one of FILE or GCS.")
    if settings.knowledge_release_store_mode == "GCS" and not settings.knowledge_release_gcs_bucket:
        raise ValueError(
            "KNOWLEDGE_RELEASE_GCS_BUCKET is required when KNOWLEDGE_RELEASE_STORE_MODE=GCS."
        )
    if settings.deployment_environment not in {"dev", "test", "poc", "prod"}:
        raise ValueError("AGENT_DEPLOYMENT_ENV must be one of dev, test, poc, or prod.")
    if settings.usd_twd_exchange_rate <= 0:
        raise ValueError("USD_TWD_EXCHANGE_RATE must be greater than 0.")
