"""Backoffice ports for Agent-backed collaborators injected at composition time."""

from __future__ import annotations

from .answer_prompt import (
    AnswerPromptProvider,
    configure_default_answer_prompt,
    get_default_answer_prompt,
)
from .chat_model import (
    ChatModelFactory,
    configure_chat_model_factory,
    get_chat_model_factory,
)
from .default_chat_model import (
    DefaultChatModelIdProvider,
    configure_default_chat_model_id,
    get_default_chat_model_id,
)
from .eval_agent import (
    EvalAgentBindings,
    configure_eval_agent_bindings,
    get_eval_agent_bindings,
)
from .governance_policy import (
    GovernancePolicyConfigurer,
    apply_governance_policy_runtime,
    configure_governance_policy_configurer,
)
from .retrieval import (
    HybridIndexFactory,
    HybridIndexPort,
    HybridSearchHit,
    configure_hybrid_index_factory,
    get_hybrid_index_factory,
)

__all__ = [
    "AnswerPromptProvider",
    "ChatModelFactory",
    "DefaultChatModelIdProvider",
    "EvalAgentBindings",
    "GovernancePolicyConfigurer",
    "HybridIndexFactory",
    "HybridIndexPort",
    "HybridSearchHit",
    "apply_governance_policy_runtime",
    "configure_chat_model_factory",
    "configure_default_answer_prompt",
    "configure_default_chat_model_id",
    "configure_eval_agent_bindings",
    "configure_governance_policy_configurer",
    "configure_hybrid_index_factory",
    "get_chat_model_factory",
    "get_default_answer_prompt",
    "get_default_chat_model_id",
    "get_eval_agent_bindings",
    "get_hybrid_index_factory",
]
