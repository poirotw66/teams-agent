from dataclasses import dataclass
from os import environ
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


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
    max_images: int = 2

    # --- Issue / cost controls (spec §4.2, §6.3, §16) ---
    max_issues_per_message: int = 3
    max_missing_info_per_issue: int = 2
    max_clarification_rounds: int = 2
    max_history_messages: int = 10
    conversation_history_rounds: int = 5
    conversation_timeout_hours: int = 24
    conversation_retention_days: int = 730
    max_llm_calls_per_request: int = 6
    max_retrieval_rewrites: int = 1

    # --- Knowledge Service (spec §8) ---
    knowledge_service_mode: str = "HYBRID"
    gemini_file_search_store: str | None = None
    gemini_file_search_model: str = "gemini-2.5-flash"
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

    # --- Human handoff (phase 2) ---
    handoff_repository_mode: str = "MEMORY"
    handoff_store_path: Path | None = None
    # FIRESTORE mode follows the same ADC conventions as conversations.
    handoff_firestore_project: str | None = None
    handoff_firestore_database: str | None = None
    handoff_firestore_collection: str = "handoffs"
    handoff_demo_timeout_hours: int = 24
    handoff_retention_days: int = 730

    # --- Feedback (spec §14) ---
    feedback_enabled: bool = True

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

    @classmethod
    def from_env(cls) -> "RagSettings":
        project_dir = Path(__file__).resolve().parents[2]
        data_dir = Path(environ.get("RAG_DATA_DIR", project_dir.parent / "data"))
        index_path = Path(
            environ.get("RAG_INDEX_PATH", data_dir / "index" / "chunks.json")
        )
        conversation_store_path = Path(
            environ.get("CONVERSATION_STORE_PATH", data_dir / "conversations")
        )
        handoff_store_path = Path(
            environ.get("HANDOFF_STORE_PATH", data_dir / "handoffs")
        )
        faq_path = Path(environ.get("FAQ_PATH", data_dir / "faq.json"))

        settings = cls(
            data_dir=data_dir.expanduser().resolve(),
            index_path=index_path.expanduser().resolve(),
            auto_build_index=_bool_env("RAG_AUTO_BUILD_INDEX", True),
            model=environ.get("RAG_MODEL", "").strip() or None,
            agent_model=environ.get("AGENT_MODEL", "").strip() or None,
            embedding_model=environ.get("RAG_EMBEDDING_MODEL", "").strip() or None,
            top_k=int(environ.get("RAG_TOP_K", "4")),
            min_score=float(environ.get("RAG_MIN_SCORE", "0.08")),
            max_rewrites=int(environ.get("RAG_MAX_REWRITES", "1")),
            chunk_size=int(environ.get("RAG_CHUNK_SIZE", "900")),
            chunk_overlap=int(environ.get("RAG_CHUNK_OVERLAP", "120")),
            allowed_tenants=_csv_env("RAG_ALLOWED_TENANTS"),
            source_base_url=environ.get("RAG_SOURCE_BASE_URL", "").strip() or None,
            service_token=environ.get("AGENT_SERVICE_TOKEN", "").strip() or None,
            max_images=int(environ.get("RAG_MAX_IMAGES", "2")),
            max_issues_per_message=_int_env("MAX_ISSUES_PER_MESSAGE", 3),
            max_missing_info_per_issue=_int_env("MAX_MISSING_INFO_PER_ISSUE", 2),
            max_clarification_rounds=_int_env("MAX_CLARIFICATION_ROUNDS", 2),
            max_history_messages=_int_env("MAX_HISTORY_MESSAGES", 10),
            conversation_history_rounds=_int_env("CONVERSATION_HISTORY_ROUNDS", 5),
            conversation_timeout_hours=_int_env("CONVERSATION_TIMEOUT_HOURS", 24),
            conversation_retention_days=_int_env("CONVERSATION_RETENTION_DAYS", 730),
            max_llm_calls_per_request=_int_env("MAX_LLM_CALLS_PER_REQUEST", 6),
            max_retrieval_rewrites=_int_env(
                "MAX_RETRIEVAL_REWRITES", int(environ.get("RAG_MAX_REWRITES", "1"))
            ),
            knowledge_service_mode=environ.get("KNOWLEDGE_SERVICE_MODE", "HYBRID").strip()
            or "HYBRID",
            gemini_file_search_store=_str_env("GEMINI_FILE_SEARCH_STORE"),
            gemini_file_search_model=(
                _str_env("GEMINI_FILE_SEARCH_MODEL") or "gemini-2.5-flash"
            ),
            gemini_file_search_enforce_acl=_bool_env(
                "GEMINI_FILE_SEARCH_ENFORCE_ACL", True
            ),
            rag_require_file_search_acl=_bool_env("RAG_REQUIRE_FILE_SEARCH_ACL", False),
            knowledge_backend_state_mode=(
                _str_env("KNOWLEDGE_BACKEND_STATE_MODE") or "MEMORY"
            ),
            knowledge_backend_state_collection=(
                _str_env("KNOWLEDGE_BACKEND_STATE_COLLECTION") or "runtime_config"
            ),
            knowledge_backend_admin_enabled=_bool_env(
                "KNOWLEDGE_BACKEND_ADMIN_ENABLED", True
            ),
            knowledge_evaluation_channels=_csv_env("KNOWLEDGE_EVALUATION_CHANNELS")
            or frozenset({"playground", "msteams-web"}),
            deployment_environment=(
                _str_env("AGENT_DEPLOYMENT_ENV")
                or _str_env("RAG_DEPLOYMENT_ENV")
                or "dev"
            ),
            ticket_service_mode=environ.get("TICKET_SERVICE_MODE", "DISABLED").strip()
            or "DISABLED",
            ticket_service_base_url=_str_env("TICKET_SERVICE_BASE_URL"),
            ticket_service_token=_str_env("TICKET_SERVICE_TOKEN"),
            ticket_service_timeout_seconds=_float_env("TICKET_SERVICE_TIMEOUT_SECONDS", 10.0),
            ticket_request_dedupe_mode=(
                _str_env("TICKET_REQUEST_DEDUPE_MODE") or "MEMORY"
            ),
            ticket_request_dedupe_collection=(
                _str_env("TICKET_REQUEST_DEDUPE_COLLECTION") or "ticket_request_ledger"
            ),
            ticket_request_dedupe_retention_days=_int_env(
                "TICKET_REQUEST_DEDUPE_RETENTION_DAYS", 30
            ),
            ticket_request_dedupe_firestore_project=_str_env(
                "TICKET_REQUEST_DEDUPE_FIRESTORE_PROJECT"
            ),
            ticket_request_dedupe_firestore_database=_str_env(
                "TICKET_REQUEST_DEDUPE_FIRESTORE_DATABASE"
            ),
            conversation_repository_mode=environ.get(
                "CONVERSATION_REPOSITORY_MODE", "MEMORY"
            ).strip()
            or "MEMORY",
            conversation_store_path=conversation_store_path.expanduser().resolve(),
            conversation_firestore_project=_str_env("CONVERSATION_FIRESTORE_PROJECT"),
            conversation_firestore_database=_str_env("CONVERSATION_FIRESTORE_DATABASE"),
            conversation_firestore_collection=(
                _str_env("CONVERSATION_FIRESTORE_COLLECTION") or "conversations"
            ),
            handoff_repository_mode=(
                _str_env("HANDOFF_REPOSITORY_MODE") or "MEMORY"
            ),
            handoff_store_path=handoff_store_path.expanduser().resolve(),
            handoff_firestore_project=_str_env("HANDOFF_FIRESTORE_PROJECT"),
            handoff_firestore_database=_str_env("HANDOFF_FIRESTORE_DATABASE"),
            handoff_firestore_collection=(
                _str_env("HANDOFF_FIRESTORE_COLLECTION") or "handoffs"
            ),
            handoff_demo_timeout_hours=_int_env("HANDOFF_DEMO_TIMEOUT_HOURS", 24),
            handoff_retention_days=_int_env("HANDOFF_RETENTION_DAYS", 730),
            faq_path=faq_path.expanduser().resolve(),
            feedback_enabled=_bool_env("FEEDBACK_ENABLED", True),
            show_turn_cost=_bool_env("SHOW_TURN_COST", True),
            show_turn_cost_playground=_bool_env("SHOW_TURN_COST_PLAYGROUND", False),
            usd_twd_exchange_rate=_float_env("USD_TWD_EXCHANGE_RATE", 31.70),
            knowledge_release_mode=(
                _str_env("KNOWLEDGE_RELEASE_MODE") or "AUTO"
            ).upper(),
            knowledge_release_dir=Path(
                environ.get(
                    "KNOWLEDGE_RELEASE_DIR",
                    data_dir / "releases",
                )
            ).expanduser().resolve(),
            knowledge_active_release_id=_str_env("KNOWLEDGE_ACTIVE_RELEASE_ID"),
        )
        settings.validate()
        return settings

    def should_show_turn_cost(self, channel: str) -> bool:
        if channel == "playground":
            return self.show_turn_cost_playground
        return self.show_turn_cost

    def validate(self) -> None:
        if self.top_k < 1 or self.top_k > 20:
            raise ValueError("RAG_TOP_K must be between 1 and 20.")
        if not 0 <= self.min_score <= 1:
            raise ValueError("RAG_MIN_SCORE must be between 0 and 1.")
        if self.max_rewrites < 0 or self.max_rewrites > 3:
            raise ValueError("RAG_MAX_REWRITES must be between 0 and 3.")
        if self.chunk_size < 200:
            raise ValueError("RAG_CHUNK_SIZE must be at least 200.")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE.")
        if self.max_images < 0 or self.max_images > 4:
            raise ValueError("RAG_MAX_IMAGES must be between 0 and 4.")

        if not 1 <= self.max_issues_per_message <= 5:
            raise ValueError("MAX_ISSUES_PER_MESSAGE must be between 1 and 5.")
        if not 1 <= self.max_missing_info_per_issue <= 3:
            raise ValueError("MAX_MISSING_INFO_PER_ISSUE must be between 1 and 3.")
        if not 0 <= self.max_history_messages <= 50:
            raise ValueError("MAX_HISTORY_MESSAGES must be between 0 and 50.")
        if not 1 <= self.conversation_history_rounds <= 20:
            raise ValueError("CONVERSATION_HISTORY_ROUNDS must be between 1 and 20.")
        if not 1 <= self.max_clarification_rounds <= 3:
            raise ValueError("MAX_CLARIFICATION_ROUNDS must be between 1 and 3.")
        if not 1 <= self.conversation_timeout_hours <= 168:
            raise ValueError("CONVERSATION_TIMEOUT_HOURS must be between 1 and 168.")
        if self.conversation_retention_days < 1:
            raise ValueError("CONVERSATION_RETENTION_DAYS must be at least 1.")
        if not 1 <= self.max_llm_calls_per_request <= 20:
            raise ValueError("MAX_LLM_CALLS_PER_REQUEST must be between 1 and 20.")
        if not 0 <= self.max_retrieval_rewrites <= 3:
            raise ValueError("MAX_RETRIEVAL_REWRITES must be between 0 and 3.")

        if self.knowledge_service_mode not in {"HYBRID", "GEMINI_FILE_SEARCH"}:
            raise ValueError(
                "KNOWLEDGE_SERVICE_MODE must be one of HYBRID or GEMINI_FILE_SEARCH."
            )
        if (
            self.rag_require_file_search_acl
            and self.gemini_file_search_store
            and not self.gemini_file_search_enforce_acl
        ):
            raise ValueError(
                "RAG_REQUIRE_FILE_SEARCH_ACL=true requires GEMINI_FILE_SEARCH_ENFORCE_ACL=true "
                "when GEMINI_FILE_SEARCH_STORE is configured."
            )
        if self.knowledge_backend_state_mode not in {"MEMORY", "FIRESTORE"}:
            raise ValueError(
                "KNOWLEDGE_BACKEND_STATE_MODE must be one of MEMORY or FIRESTORE."
            )
        if not self.knowledge_backend_state_collection.strip():
            raise ValueError("KNOWLEDGE_BACKEND_STATE_COLLECTION must not be blank.")
        if "/" in self.knowledge_backend_state_collection:
            raise ValueError("KNOWLEDGE_BACKEND_STATE_COLLECTION must not contain '/'.")

        if self.ticket_service_mode not in {"DISABLED", "HTTP"}:
            raise ValueError("TICKET_SERVICE_MODE must be one of DISABLED or HTTP.")
        if self.ticket_service_mode == "HTTP":
            if not self.ticket_service_base_url:
                raise ValueError(
                    "TICKET_SERVICE_BASE_URL is required when TICKET_SERVICE_MODE=HTTP."
                )
            if not self.ticket_service_base_url.startswith(("http://", "https://")):
                raise ValueError("TICKET_SERVICE_BASE_URL must be an http(s) URL.")
        if not 1 <= self.ticket_service_timeout_seconds <= 60:
            raise ValueError("TICKET_SERVICE_TIMEOUT_SECONDS must be between 1 and 60.")
        if self.ticket_request_dedupe_mode not in {"MEMORY", "FIRESTORE"}:
            raise ValueError(
                "TICKET_REQUEST_DEDUPE_MODE must be one of MEMORY or FIRESTORE."
            )
        if not self.ticket_request_dedupe_collection.strip():
            raise ValueError("TICKET_REQUEST_DEDUPE_COLLECTION must not be blank.")
        if "/" in self.ticket_request_dedupe_collection:
            raise ValueError("TICKET_REQUEST_DEDUPE_COLLECTION must not contain '/'.")
        if not 1 <= self.ticket_request_dedupe_retention_days <= 365:
            raise ValueError(
                "TICKET_REQUEST_DEDUPE_RETENTION_DAYS must be between 1 and 365."
            )

        if self.conversation_repository_mode not in {"MEMORY", "FILE", "FIRESTORE"}:
            raise ValueError(
                "CONVERSATION_REPOSITORY_MODE must be one of MEMORY, FILE or FIRESTORE."
            )
        if not self.conversation_firestore_collection.strip():
            raise ValueError("CONVERSATION_FIRESTORE_COLLECTION must not be blank.")
        # Firestore rejects these in a collection id; catching it here turns a
        # runtime write failure into a startup failure.
        if "/" in self.conversation_firestore_collection:
            raise ValueError("CONVERSATION_FIRESTORE_COLLECTION must not contain '/'.")

        if self.handoff_repository_mode not in {"MEMORY", "FILE", "FIRESTORE"}:
            raise ValueError(
                "HANDOFF_REPOSITORY_MODE must be one of MEMORY, FILE or FIRESTORE."
            )
        if not self.handoff_firestore_collection.strip():
            raise ValueError("HANDOFF_FIRESTORE_COLLECTION must not be blank.")
        if "/" in self.handoff_firestore_collection:
            raise ValueError("HANDOFF_FIRESTORE_COLLECTION must not contain '/'.")
        if self.handoff_demo_timeout_hours < 1:
            raise ValueError("HANDOFF_DEMO_TIMEOUT_HOURS must be at least 1.")
        if self.handoff_retention_days < 1:
            raise ValueError("HANDOFF_RETENTION_DAYS must be at least 1.")
        if self.knowledge_release_mode not in {"BUNDLED", "PORTAL", "AUTO"}:
            raise ValueError(
                "KNOWLEDGE_RELEASE_MODE must be one of BUNDLED, PORTAL, or AUTO."
            )
        if self.deployment_environment not in {"dev", "test", "poc", "prod"}:
            raise ValueError(
                "AGENT_DEPLOYMENT_ENV must be one of dev, test, poc, or prod."
            )
        if self.usd_twd_exchange_rate <= 0:
            raise ValueError("USD_TWD_EXCHANGE_RATE must be greater than 0.")
