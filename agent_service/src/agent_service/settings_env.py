"""Environment parsing helpers for RagSettings.from_env."""

from __future__ import annotations

from os import environ
from pathlib import Path
from typing import Any


def _bool_env(name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> frozenset[str]:
    return frozenset(
        value.strip() for value in environ.get(name, "").split(",") if value.strip()
    )


def _int_env(name: str, default: int) -> int:
    return int(environ.get(name, str(default)))


def _float_env(name: str, default: float) -> float:
    return float(environ.get(name, str(default)))


def _str_env(name: str) -> str | None:
    return environ.get(name, "").strip() or None


def _resolve_turn_planner_mode() -> str:
    """Prefer TURN_PLANNER_MODE; else map TURN_PLANNER_ENABLED to OFF/ALL."""
    mode = (_str_env("TURN_PLANNER_MODE") or "").upper()
    if mode:
        if mode not in {"OFF", "CONTEXTUAL", "ALL"}:
            raise ValueError(
                "TURN_PLANNER_MODE must be OFF, CONTEXTUAL, or ALL; "
                f"got {mode!r}"
            )
        return mode
    return "ALL" if _bool_env("TURN_PLANNER_ENABLED", False) else "OFF"


def resolve_paths(project_dir: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    raw = environ.get("RAG_DATA_DIR")
    if raw and Path(raw).is_absolute():
        data_dir = Path(raw).resolve()
    elif raw and (project_dir / raw).exists():
        data_dir = (project_dir / raw).resolve()
    elif raw and Path(raw).exists():
        data_dir = Path(raw).resolve()
    else:
        data_dir = (project_dir.parent / "data").resolve()

    def _path(key: str, default: Path) -> Path:
        return Path(environ.get(key, default)).expanduser().resolve()

    return (
        data_dir,
        _path("RAG_INDEX_PATH", data_dir / "index" / "chunks.json"),
        _path("CONVERSATION_STORE_PATH", data_dir / "conversations"),
        _path("HANDOFF_STORE_PATH", data_dir / "handoffs"),
        _path("FAQ_PATH", data_dir / "faq.json"),
        _path("AI_OPS_FAQ_STORE_PATH", data_dir / "ops" / "phase2" / "faqs.json"),
    )


def load_core_rag_env(
    data_dir: Path,
    index_path: Path,
) -> dict[str, Any]:
    return {
        "data_dir": data_dir,
        "index_path": index_path,
        "auto_build_index": _bool_env("RAG_AUTO_BUILD_INDEX", True),
        "model": environ.get("RAG_MODEL", "").strip() or None,
        "agent_model": environ.get("AGENT_MODEL", "").strip() or None,
        "embedding_model": environ.get("RAG_EMBEDDING_MODEL", "").strip() or None,
        "rag_answer_model": environ.get("RAG_ANSWER_MODEL", "").strip() or None,
        "rag_relevance_model": environ.get("RAG_RELEVANCE_MODEL", "").strip() or None,
        "rag_rewrite_model": environ.get("RAG_REWRITE_MODEL", "").strip() or None,
        "rag_hard_answer_model": environ.get("RAG_HARD_ANSWER_MODEL", "").strip() or None,
        "rag_answer_escalation_policy": (
            environ.get("RAG_ANSWER_ESCALATION_POLICY", "OFF").strip().upper() or "OFF"
        ),
        "top_k": _int_env("RAG_TOP_K", 4),
        "min_score": _float_env("RAG_MIN_SCORE", 0.08),
        "max_rewrites": _int_env("RAG_MAX_REWRITES", 1),
        "chunk_size": _int_env("RAG_CHUNK_SIZE", 900),
        "chunk_overlap": _int_env("RAG_CHUNK_OVERLAP", 120),
        "allowed_tenants": _csv_env("RAG_ALLOWED_TENANTS"),
        "source_base_url": _str_env("RAG_SOURCE_BASE_URL"),
        "service_token": next(
            (
                environ[key].strip()
                for key in (
                    "AGENT_SERVICE_TOKEN",
                    "AGENT_RELOAD_TOKEN",
                    "SERVICE_TOKEN",
                )
                if environ.get(key, "").strip()
            ),
            None,
        ),
        "golden_evaluation_token": _str_env("GOLDEN_EVALUATION_TOKEN"),
        "max_images": _int_env("RAG_MAX_IMAGES", 2),
    }


def load_issue_cost_controls_env() -> dict[str, Any]:
    return {
        "max_issues_per_message": _int_env("MAX_ISSUES_PER_MESSAGE", 3),
        "max_missing_info_per_issue": _int_env("MAX_MISSING_INFO_PER_ISSUE", 2),
        "max_clarification_rounds": _int_env("MAX_CLARIFICATION_ROUNDS", 2),
        "max_history_messages": _int_env("MAX_HISTORY_MESSAGES", 10),
        "conversation_history_rounds": _int_env("CONVERSATION_HISTORY_ROUNDS", 5),
        "conversation_timeout_hours": _int_env("CONVERSATION_TIMEOUT_HOURS", 24),
        "conversation_retention_days": _int_env("CONVERSATION_RETENTION_DAYS", 365),
        "supervisor_terminal_confidence": _float_env(
            "SUPERVISOR_TERMINAL_CONFIDENCE", 0.9
        ),
        "turn_planner_enabled": _bool_env("TURN_PLANNER_ENABLED", False),
        "turn_planner_mode": _resolve_turn_planner_mode(),
        "max_llm_calls_per_request": _int_env("MAX_LLM_CALLS_PER_REQUEST", 6),
        "max_concurrent_llm_calls_per_request": _int_env(
            "MAX_CONCURRENT_LLM_CALLS_PER_REQUEST", 2
        ),
        "request_deadline_seconds": _float_env("AGENT_REQUEST_DEADLINE_SECONDS", 90.0),
        "max_retrieval_rewrites": _int_env(
            "MAX_RETRIEVAL_REWRITES", int(environ.get("RAG_MAX_REWRITES", "1"))
        ),
        "skip_relevance_llm_on_high_confidence": _bool_env(
            "RAG_SKIP_RELEVANCE_LLM_ON_HIGH_CONFIDENCE", True
        ),
        "enable_adaptive_query_tiers": _bool_env("ENABLE_ADAPTIVE_QUERY_TIERS", True),
        "rag_fusion_mode": (_str_env("RAG_FUSION_MODE") or "RRF").upper(),
        "rag_rrf_k": _int_env("RAG_RRF_K", 5),
        "rag_sparse_candidate_k": _int_env("RAG_SPARSE_CANDIDATE_K", 40),
        "rag_dense_candidate_k": _int_env("RAG_DENSE_CANDIDATE_K", 10),
        "rag_fusion_candidate_k": _int_env("RAG_FUSION_CANDIDATE_K", 20),
        "rag_sparse_weight": _float_env("RAG_SPARSE_WEIGHT", 0.5),
        "rag_dense_weight": _float_env("RAG_DENSE_WEIGHT", 1.5),
        "rag_contextual_index": _bool_env("RAG_CONTEXTUAL_INDEX", True),
        "rag_reranker_enabled": _bool_env("RAG_RERANKER_ENABLED", False),
        "rag_reranker_model": (_str_env("RAG_RERANKER_MODEL") or "lexical"),
        "rag_rerank_candidate_k": _int_env("RAG_RERANK_CANDIDATE_K", 24),
        "rag_rerank_timeout_ms": _int_env("RAG_RERANK_TIMEOUT_MS", 700),
        "rag_reranker_min_tier": (
            _str_env("RAG_RERANKER_MIN_TIER") or "standard"
        ).strip().lower(),
        "rag_canary_percent": _int_env("RAG_CANARY_PERCENT", 0),
        "rag_canary_variant": (
            _str_env("RAG_CANARY_VARIANT") or "CANDIDATE"
        ).strip().upper(),
        "rag_baseline_variant": (
            _str_env("RAG_BASELINE_VARIANT") or "BASELINE"
        ).strip().upper(),
        "rag_evidence_token_budget": _int_env("RAG_EVIDENCE_TOKEN_BUDGET", 1200),
        "rag_evidence_token_budget_trivial": _int_env(
            "RAG_EVIDENCE_TOKEN_BUDGET_TRIVIAL", 500
        ),
        "rag_evidence_token_budget_standard": _int_env(
            "RAG_EVIDENCE_TOKEN_BUDGET_STANDARD", 800
        ),
        "rag_companion_inject_enabled": _bool_env(
            "RAG_COMPANION_INJECT_ENABLED", True
        ),
    }


def load_knowledge_service_env() -> dict[str, Any]:
    return {
        "knowledge_service_mode": environ.get("KNOWLEDGE_SERVICE_MODE", "HYBRID").strip()
        or "HYBRID",
        "gemini_file_search_store": _str_env("GEMINI_FILE_SEARCH_STORE"),
        "gemini_file_search_model": (
            _str_env("GEMINI_FILE_SEARCH_MODEL") or "gemini-3.5-flash-lite"
        ),
        "gemini_file_search_enforce_acl": _bool_env(
            "GEMINI_FILE_SEARCH_ENFORCE_ACL", True
        ),
        "rag_require_file_search_acl": _bool_env("RAG_REQUIRE_FILE_SEARCH_ACL", False),
        "knowledge_backend_state_mode": (
            _str_env("KNOWLEDGE_BACKEND_STATE_MODE") or "MEMORY"
        ),
        "knowledge_backend_state_collection": (
            _str_env("KNOWLEDGE_BACKEND_STATE_COLLECTION") or "runtime_config"
        ),
        "knowledge_backend_admin_enabled": _bool_env(
            "KNOWLEDGE_BACKEND_ADMIN_ENABLED", True
        ),
        "knowledge_evaluation_channels": _csv_env("KNOWLEDGE_EVALUATION_CHANNELS")
        or frozenset({"playground", "msteams-web"}),
        "deployment_environment": (
            _str_env("AGENT_DEPLOYMENT_ENV")
            or _str_env("RAG_DEPLOYMENT_ENV")
            or "dev"
        ),
    }


def load_ticket_service_env() -> dict[str, Any]:
    return {
        "ticket_service_mode": environ.get("TICKET_SERVICE_MODE", "DISABLED").strip()
        or "DISABLED",
        "ticket_service_base_url": _str_env("TICKET_SERVICE_BASE_URL"),
        "ticket_service_token": _str_env("TICKET_SERVICE_TOKEN"),
        "ticket_service_timeout_seconds": _float_env(
            "TICKET_SERVICE_TIMEOUT_SECONDS", 10.0
        ),
        "ticket_request_dedupe_mode": (
            _str_env("TICKET_REQUEST_DEDUPE_MODE") or "MEMORY"
        ),
        "ticket_request_dedupe_collection": (
            _str_env("TICKET_REQUEST_DEDUPE_COLLECTION") or "ticket_request_ledger"
        ),
        "ticket_request_dedupe_retention_days": _int_env(
            "TICKET_REQUEST_DEDUPE_RETENTION_DAYS", 30
        ),
        "ticket_request_dedupe_firestore_project": _str_env(
            "TICKET_REQUEST_DEDUPE_FIRESTORE_PROJECT"
        ),
        "ticket_request_dedupe_firestore_database": _str_env(
            "TICKET_REQUEST_DEDUPE_FIRESTORE_DATABASE"
        ),
    }


def load_conversation_handoff_faq_env(
    conversation_store_path: Path,
    handoff_store_path: Path,
    faq_path: Path,
    faq_governed_store_path: Path,
) -> dict[str, Any]:
    return {
        "conversation_repository_mode": environ.get(
            "CONVERSATION_REPOSITORY_MODE", "MEMORY"
        ).strip()
        or "MEMORY",
        "conversation_store_path": conversation_store_path.expanduser().resolve(),
        "conversation_firestore_project": _str_env("CONVERSATION_FIRESTORE_PROJECT"),
        "conversation_firestore_database": _str_env("CONVERSATION_FIRESTORE_DATABASE"),
        "conversation_firestore_collection": (
            _str_env("CONVERSATION_FIRESTORE_COLLECTION") or "conversations"
        ),
        "handoff_repository_mode": (_str_env("HANDOFF_REPOSITORY_MODE") or "MEMORY"),
        "handoff_store_path": handoff_store_path.expanduser().resolve(),
        "handoff_firestore_project": _str_env("HANDOFF_FIRESTORE_PROJECT"),
        "handoff_firestore_database": _str_env("HANDOFF_FIRESTORE_DATABASE"),
        "handoff_firestore_collection": (
            _str_env("HANDOFF_FIRESTORE_COLLECTION") or "handoffs"
        ),
        "handoff_demo_timeout_hours": _int_env("HANDOFF_DEMO_TIMEOUT_HOURS", 24),
        "handoff_retention_days": _int_env("HANDOFF_RETENTION_DAYS", 365),
        "faq_path": faq_path.expanduser().resolve(),
        "faq_runtime_mode": (_str_env("FAQ_RUNTIME_MODE") or "LEGACY_JSON").upper(),
        "faq_governed_store_mode": (
            _str_env("AI_OPS_FAQ_STORE_MODE") or "FILE"
        ).upper(),
        "faq_governed_store_path": faq_governed_store_path.expanduser().resolve(),
        "faq_firestore_project": (
            _str_env("AI_OPS_FAQ_FIRESTORE_PROJECT") or _str_env("GOOGLE_CLOUD_PROJECT")
        ),
        "faq_firestore_database": _str_env("AI_OPS_FAQ_FIRESTORE_DATABASE"),
        "faq_firestore_collection_prefix": (
            _str_env("AI_OPS_FAQ_FIRESTORE_COLLECTION_PREFIX") or "ai_ops_faq"
        ),
    }


def load_feedback_cost_env() -> dict[str, Any]:
    return {
        "feedback_enabled": _bool_env("FEEDBACK_ENABLED", True),
        "otel_enabled": _bool_env("OTEL_ENABLED", False),
        "otel_service_name": _str_env("OTEL_SERVICE_NAME") or "agent-runtime",
        "otel_exporter_endpoint": _str_env("OTEL_EXPORTER_OTLP_ENDPOINT"),
        "show_turn_cost": _bool_env("SHOW_TURN_COST", True),
        "show_turn_cost_playground": _bool_env("SHOW_TURN_COST_PLAYGROUND", False),
        "usd_twd_exchange_rate": _float_env("USD_TWD_EXCHANGE_RATE", 31.70),
    }


def load_knowledge_release_env(data_dir: Path) -> dict[str, Any]:
    is_prod = environ.get("AGENT_DEPLOYMENT_ENV", "dev").strip().lower() == "prod"
    return {
        "knowledge_release_mode": (_str_env("KNOWLEDGE_RELEASE_MODE") or "AUTO").upper(),
        "knowledge_release_dir": Path(
            environ.get(
                "KNOWLEDGE_RELEASE_DIR",
                data_dir / "releases",
            )
        )
        .expanduser()
        .resolve(),
        "knowledge_active_release_id": _str_env("KNOWLEDGE_ACTIVE_RELEASE_ID"),
        "knowledge_release_require_manifest": _bool_env(
            "KNOWLEDGE_RELEASE_REQUIRE_MANIFEST",
            is_prod,
        ),
        "knowledge_release_require_vectors": _bool_env(
            "KNOWLEDGE_RELEASE_REQUIRE_VECTORS",
            is_prod,
        ),
        "knowledge_release_store_mode": (
            _str_env("KNOWLEDGE_RELEASE_STORE_MODE") or "FILE"
        ).upper(),
        "knowledge_release_gcs_bucket": _str_env("KNOWLEDGE_RELEASE_GCS_BUCKET"),
        "knowledge_release_gcs_prefix": (
            _str_env("KNOWLEDGE_RELEASE_GCS_PREFIX") or "knowledge-releases"
        ).strip("/"),
        "knowledge_release_tenant_id": (
            _str_env("KNOWLEDGE_RELEASE_TENANT_ID") or "default"
        ),
        "knowledge_release_cache_dir": Path(
            environ.get(
                "KNOWLEDGE_RELEASE_CACHE_DIR",
                data_dir / "knowledge_cache",
            )
        )
        .expanduser()
        .resolve(),
        "knowledge_release_sync_interval_seconds": _int_env(
            "KNOWLEDGE_RELEASE_SYNC_INTERVAL_SECONDS",
            300,
        ),
        "knowledge_release_selection_mode": (
            (_str_env("KNOWLEDGE_RELEASE_SELECTION_MODE") or "").upper() or None
        ),
        "knowledge_release_firestore_project": _str_env(
            "KNOWLEDGE_RELEASE_FIRESTORE_PROJECT"
        ),
        "knowledge_release_firestore_database": _str_env(
            "KNOWLEDGE_RELEASE_FIRESTORE_DATABASE"
        ),
        "knowledge_release_firestore_config_collection": (
            _str_env("KNOWLEDGE_RELEASE_FIRESTORE_CONFIG_COLLECTION")
            or "knowledge_portal_config"
        ),
        "knowledge_release_firestore_releases_collection": (
            _str_env("KNOWLEDGE_RELEASE_FIRESTORE_RELEASES_COLLECTION")
            or "knowledge_releases"
        ),
    }


def load_prompt_governance_env(data_dir: Path) -> dict[str, Any]:
    return {
        "prompt_runtime_mode": (_str_env("PROMPT_RUNTIME_MODE") or "GOVERNED").upper(),
        "prompt_governance_store_mode": (
            _str_env("AI_OPS_GOVERNANCE_STORE_MODE") or "FILE"
        ).upper(),
        "prompt_governance_store_path": Path(
            environ.get(
                "AI_OPS_GOVERNANCE_STORE_PATH",
                data_dir / "ops" / "phase3" / "governance.json",
            )
        )
        .expanduser()
        .resolve(),
        "prompt_governance_firestore_project": (
            _str_env("AI_OPS_GOVERNANCE_FIRESTORE_PROJECT")
            or _str_env("GOOGLE_CLOUD_PROJECT")
        ),
        "prompt_governance_firestore_database": _str_env(
            "AI_OPS_GOVERNANCE_FIRESTORE_DATABASE"
        ),
        "prompt_governance_firestore_collection": (
            _str_env("AI_OPS_GOVERNANCE_FIRESTORE_COLLECTION")
            or "ai_ops_governance_state"
        ),
    }


def build_rag_settings_kwargs(project_dir: Path) -> dict[str, Any]:
    """Assemble all RagSettings constructor kwargs from the environment."""
    (
        data_dir,
        index_path,
        conversation_store_path,
        handoff_store_path,
        faq_path,
        faq_governed_store_path,
    ) = resolve_paths(project_dir)
    return {
        **load_core_rag_env(data_dir, index_path),
        **load_issue_cost_controls_env(),
        **load_knowledge_service_env(),
        **load_ticket_service_env(),
        **load_conversation_handoff_faq_env(
            conversation_store_path,
            handoff_store_path,
            faq_path,
            faq_governed_store_path,
        ),
        **load_feedback_cost_env(),
        **load_knowledge_release_env(data_dir),
        **load_prompt_governance_env(data_dir),
    }
