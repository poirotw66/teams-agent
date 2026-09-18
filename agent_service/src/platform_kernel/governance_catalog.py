"""Stable governance catalog contracts consumed by Agent and Backoffice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ISSUE_EXTRACTOR_PROMPT_ID = "issue-extractor"

DEFAULT_AGENT_MODEL_ID = "gemini-3.8-flash"
DEFAULT_RAG_MODEL_ID = "gemini-3.1-flash-lite"
DEFAULT_FILE_SEARCH_MODEL_ID = "gemini-3.5-flash-lite"

ModelEffect = Literal["next_request", "reindex", "service_refresh"]
ModelFamily = Literal["chat", "embedding", "file_search"]


@dataclass(frozen=True)
class ModelComponentSpec:
    config_id: str
    component: str
    role: str
    label: str
    effect: ModelEffect
    family: ModelFamily


MODEL_COMPONENTS: tuple[ModelComponentSpec, ...] = (
    ModelComponentSpec(
        config_id="issue-extractor-model",
        component="issue-extractor",
        role="agent",
        label="主代理／議題拆解",
        effect="next_request",
        family="chat",
    ),
    ModelComponentSpec(
        config_id="rag-answer-model",
        component="rag-answer",
        role="answer",
        label="回答生成",
        effect="next_request",
        family="chat",
    ),
    ModelComponentSpec(
        config_id="embedding-model",
        component="embedding",
        role="embedding",
        label="向量檢索 Embedding",
        effect="reindex",
        family="embedding",
    ),
    ModelComponentSpec(
        config_id="file-search-model",
        component="file-search",
        role="file_search",
        label="Gemini File Search",
        effect="service_refresh",
        family="file_search",
    ),
)

FLAG_CATALOG: dict[str, dict[str, Any]] = {
    "ticket_mode": {
        "description": "Governed ticket-mode switch",
        "owner": "AI_ADMIN",
        "flag_type": "enum",
        "values": ("DISABLED", "ENABLED"),
        "default": "ENABLED",
        "safety_locked": False,
    },
    "handoff_mode": {
        "description": "Governed handoff-mode switch",
        "owner": "AI_ADMIN",
        "flag_type": "enum",
        "values": ("DISABLED", "ENABLED"),
        "default": "ENABLED",
        "safety_locked": False,
    },
    "feedback": {
        "description": "Feedback capture",
        "owner": "SERVICE_OWNER",
        "flag_type": "boolean",
        "default": "true",
        "safety_locked": False,
    },
    "cost_display": {
        "description": "Cost display in backoffice",
        "owner": "SERVICE_OWNER",
        "flag_type": "boolean",
        "default": "true",
        "safety_locked": False,
    },
    "knowledge_backend_evaluation": {
        "description": "Knowledge backend evaluation switch",
        "owner": "AI_ADMIN",
        "flag_type": "boolean",
        "default": "false",
        "safety_locked": False,
    },
    "masking_enforced": {
        "description": "Sensitive-data masking enforcement",
        "owner": "SYSTEM_ADMIN",
        "flag_type": "boolean",
        "default": "true",
        "safety_locked": True,
    },
    "audit_enforced": {
        "description": "Audit write fail-closed enforcement",
        "owner": "SYSTEM_ADMIN",
        "flag_type": "boolean",
        "default": "true",
        "safety_locked": True,
    },
    "bu_ui_shell_v1": {
        "description": "BU task-oriented backoffice shell (U1 IA + Teams tokens)",
        "owner": "AI_ADMIN",
        "flag_type": "boolean",
        "default": "false",
        "safety_locked": False,
    },
}
