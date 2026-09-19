from dataclasses import dataclass
from os import environ
from pathlib import Path

from dotenv import load_dotenv

from .settings_env import build_rag_settings_kwargs

load_dotenv()

# Normalize dotenv values that may retain trailing CR on Windows-edited files.
for _key, _value in list(environ.items()):
    if "\r" in _value:
        environ[_key] = _value.replace("\r", "")


@dataclass(frozen=True)
class RagSettings:
    data_dir: Path
    index_path: Path
    auto_build_index: bool = True
    model: str | None = None
    agent_model: str | None = None
    embedding_model: str | None = None
    top_k: int = 4
    min_score: float = 0.08
    max_rewrites: int = 1
    chunk_size: int = 900
    chunk_overlap: int = 120
    allowed_tenants: frozenset[str] = frozenset()
    source_base_url: str | None = None
    service_token: str | None = None
    golden_evaluation_token: str | None = None
    max_images: int = 2

    # --- Issue / cost controls (spec §4.2, §6.3, §16) ---
    max_issues_per_message: int = 3
    max_missing_info_per_issue: int = 2
    max_clarification_rounds: int = 2
    max_history_messages: int = 10
    conversation_history_rounds: int = 5
    conversation_timeout_hours: int = 24
    conversation_retention_days: int = 365
    supervisor_terminal_confidence: float = 0.9
    # PoC: one structured call for route + issues (docs/0919-arch.md).
    # Keep off until Golden Eval Accuracy / P95 / Cost comparison is reviewed.
    turn_planner_enabled: bool = False
    max_llm_calls_per_request: int = 6
    max_retrieval_rewrites: int = 1
    skip_relevance_llm_on_high_confidence: bool = True
    enable_adaptive_query_tiers: bool = True

    # --- Knowledge Service (spec §8) ---
    knowledge_service_mode: str = "HYBRID"
    gemini_file_search_store: str | None = None
    gemini_file_search_model: str = "gemini-3.5-flash-lite"
    gemini_file_search_enforce_acl: bool = True
    rag_require_file_search_acl: bool = False
    knowledge_backend_state_mode: str = "MEMORY"
    knowledge_backend_state_collection: str = "runtime_config"
    knowledge_backend_admin_enabled: bool = True
    knowledge_evaluation_channels: frozenset[str] = frozenset({"playground", "msteams-web"})
    deployment_environment: str = "dev"

    # --- Ticket Service (spec §11) ---
    ticket_service_mode: str = "DISABLED"
    ticket_service_base_url: str | None = None
    ticket_service_token: str | None = None
    ticket_service_timeout_seconds: float = 10.0
    ticket_request_dedupe_mode: str = "MEMORY"
    ticket_request_dedupe_collection: str = "ticket_request_ledger"
    ticket_request_dedupe_retention_days: int = 30
    ticket_request_dedupe_firestore_project: str | None = None
    ticket_request_dedupe_firestore_database: str | None = None

    # --- Conversation Repository (spec §10) ---
    conversation_repository_mode: str = "MEMORY"
    conversation_store_path: Path | None = None
    # FIRESTORE mode only. project/database default to whatever Application
    # Default Credentials resolve to on Cloud Run, so neither is required.
    conversation_firestore_project: str | None = None
    conversation_firestore_database: str | None = None
    conversation_firestore_collection: str = "conversations"
    faq_path: Path | None = None
    faq_runtime_mode: str = "LEGACY_JSON"
    faq_governed_store_mode: str = "FILE"
    faq_governed_store_path: Path | None = None
    faq_firestore_project: str | None = None
    faq_firestore_database: str | None = None
    faq_firestore_collection_prefix: str = "ai_ops_faq"

    # --- Human handoff (phase 2) ---
    handoff_repository_mode: str = "MEMORY"
    handoff_store_path: Path | None = None
    # FIRESTORE mode follows the same ADC conventions as conversations.
    handoff_firestore_project: str | None = None
    handoff_firestore_database: str | None = None
    handoff_firestore_collection: str = "handoffs"
    handoff_demo_timeout_hours: int = 24
    handoff_retention_days: int = 365

    # --- Feedback (spec §14) ---
    feedback_enabled: bool = True

    # --- Observability (docs/0919-arch.md P2) ---
    otel_enabled: bool = False
    otel_service_name: str = "agent-runtime"
    otel_exporter_endpoint: str | None = None

    # --- Cost visibility (Phase 1 observability) ---
    show_turn_cost: bool = True
    # Playground channel hides per-turn cost in the user-facing response by default;
    # request_cost logs and usage.recorded ops events still capture cost metadata.
    show_turn_cost_playground: bool = False
    usd_twd_exchange_rate: float = 31.70

    # --- Knowledge release (portal-published immutable index) ---
    knowledge_release_mode: str = "AUTO"
    knowledge_release_dir: Path | None = None
    knowledge_active_release_id: str | None = None
    knowledge_release_require_manifest: bool = False
    knowledge_release_require_vectors: bool = False
    knowledge_release_store_mode: str = "FILE"
    knowledge_release_gcs_bucket: str | None = None
    knowledge_release_gcs_prefix: str = "knowledge-releases"
    knowledge_release_tenant_id: str = "default"
    knowledge_release_cache_dir: Path | None = None
    knowledge_release_firestore_project: str | None = None
    knowledge_release_firestore_database: str | None = None
    knowledge_release_firestore_config_collection: str = "knowledge_portal_config"
    knowledge_release_firestore_releases_collection: str = "knowledge_releases"

    # --- Phase 3 Prompt governance runtime ---
    prompt_runtime_mode: str = "GOVERNED"
    prompt_governance_store_mode: str = "FILE"
    prompt_governance_store_path: Path | None = None
    prompt_governance_firestore_project: str | None = None
    prompt_governance_firestore_database: str | None = None
    prompt_governance_firestore_collection: str = "ai_ops_governance_state"

    @classmethod
    def from_env(cls) -> "RagSettings":
        project_dir = Path(__file__).resolve().parents[2]
        settings = cls(**build_rag_settings_kwargs(project_dir))
        settings.validate()
        return settings

    def should_show_turn_cost(self, channel: str) -> bool:
        if channel == "playground":
            return self.show_turn_cost_playground
        return self.show_turn_cost

    def validate(self) -> None:
        from .settings_validate import (
            validate_faq_and_prompt_modes,
            validate_knowledge_and_ticket_modes,
            validate_persistence_and_release_modes,
            validate_rag_and_conversation_limits,
        )

        validate_rag_and_conversation_limits(self)
        validate_faq_and_prompt_modes(self)
        validate_knowledge_and_ticket_modes(self)
        validate_persistence_and_release_modes(self)
