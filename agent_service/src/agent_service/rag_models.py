"""Startup-built RAG model roles for HybridKnowledgeService.

Models are constructed once at process startup. Request paths must not call
``build_chat_model()``. When new role settings are unset, behavior matches the
legacy single ``RAG_MODEL`` / ``settings.model`` path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel

from .settings import RagSettings

RAG_ANSWER_ESCALATION_POLICIES = frozenset(
    {
        "OFF",
        "HARD_DIRECT",
        "ON_GROUNDING_FAILURE",
        "HARD_OR_GROUNDING_FAILURE",
    }
)

ChatModelFactory = Callable[..., BaseChatModel | None]


@dataclass(frozen=True)
class RagModelIds:
    """Resolved model identifiers before chat-model construction."""

    answer: str | None
    relevance: str | None
    rewrite: str | None
    hard_answer: str | None
    answer_source: str
    relevance_source: str
    rewrite_source: str
    hard_answer_source: str
    escalation_policy: str


@dataclass(frozen=True)
class RagModelBundle:
    answer: BaseChatModel | None
    relevance: BaseChatModel | None
    rewrite: BaseChatModel | None
    hard_answer: BaseChatModel | None
    ids: RagModelIds | None = None

    @classmethod
    def from_single_model(cls, model: BaseChatModel | None) -> RagModelBundle:
        return cls(
            answer=model,
            relevance=model,
            rewrite=model,
            hard_answer=None,
            ids=None,
        )


def resolve_rag_model_ids(settings: RagSettings) -> RagModelIds:
    """Apply the role resolution order from the production-optimization spec."""
    policy = str(
        getattr(settings, "rag_answer_escalation_policy", "OFF") or "OFF"
    ).strip().upper()
    if policy not in RAG_ANSWER_ESCALATION_POLICIES:
        raise ValueError(
            "RAG_ANSWER_ESCALATION_POLICY must be one of "
            f"{sorted(RAG_ANSWER_ESCALATION_POLICIES)}; got {policy!r}"
        )

    if getattr(settings, "rag_answer_model", None):
        answer = settings.rag_answer_model
        answer_source = "environment"
    else:
        answer = settings.model
        answer_source = "fallback"

    if getattr(settings, "rag_relevance_model", None):
        relevance = settings.rag_relevance_model
        relevance_source = "environment"
    else:
        relevance = answer
        relevance_source = "fallback"

    if getattr(settings, "rag_rewrite_model", None):
        rewrite = settings.rag_rewrite_model
        rewrite_source = "environment"
    else:
        rewrite = relevance
        rewrite_source = "fallback"

    hard = getattr(settings, "rag_hard_answer_model", None)
    hard_source = "environment" if hard else "fallback"

    return RagModelIds(
        answer=answer,
        relevance=relevance,
        rewrite=rewrite,
        hard_answer=hard,
        answer_source=answer_source,
        relevance_source=relevance_source,
        rewrite_source=rewrite_source,
        hard_answer_source=hard_source,
        escalation_policy=policy,
    )


def build_rag_model_bundle(
    settings: RagSettings,
    *,
    build_chat_model: ChatModelFactory,
    temperature: float = 0.0,
    governance_overrides: dict[str, str] | None = None,
) -> RagModelBundle:
    """Construct role-specific chat models once at startup.

    ``governance_overrides`` maps role names (answer/relevance/rewrite/hard_answer)
    to model ids; governance wins for those roles only.
    """
    ids = resolve_rag_model_ids(settings)
    for role, model_id in (governance_overrides or {}).items():
        if model_id:
            ids = apply_governance_model_override(ids, role=role, model_id=model_id)
    cache: dict[str, BaseChatModel | None] = {}

    def _build(model_id: str | None) -> BaseChatModel | None:
        if not model_id:
            return None
        if model_id not in cache:
            cache[model_id] = build_chat_model(model_id, temperature=temperature)
        return cache[model_id]

    return RagModelBundle(
        answer=_build(ids.answer),
        relevance=_build(ids.relevance),
        rewrite=_build(ids.rewrite),
        hard_answer=_build(ids.hard_answer),
        ids=ids,
    )


def governance_overrides_from_runtime(runtime: Any) -> dict[str, str]:
    """Peek governed RAG role models when runtime mode is GOVERNED."""
    import logging

    logger = logging.getLogger(__name__)
    overrides: dict[str, str] = {}
    if runtime is None:
        return overrides
    role_to_config = {
        "answer": "rag-answer-model",
        "relevance": "rag-relevance-model",
        "rewrite": "rag-rewrite-model",
        "hard_answer": "rag-hard-answer-model",
    }
    for role, config_id in role_to_config.items():
        try:
            resolved = runtime.resolve_model(config_id=config_id)
        except Exception as error:  # noqa: BLE001 - startup must not fail closed on peek errors
            logger.warning(
                "governance peek failed for %s (%s); keeping env baseline",
                config_id,
                type(error).__name__,
            )
            continue
        if getattr(resolved, "source", None) != "governance":
            continue
        model_name = getattr(resolved, "model_name", None) or getattr(
            resolved, "model_id", None
        )
        if model_name:
            overrides[role] = str(model_name)
    return overrides


def apply_governance_model_override(
    ids: RagModelIds,
    *,
    role: str,
    model_id: str,
    source: str = "governance",
) -> RagModelIds:
    """Return a copy with one role overridden (governance wins for that role)."""
    values = {
        "answer": ids.answer,
        "relevance": ids.relevance,
        "rewrite": ids.rewrite,
        "hard_answer": ids.hard_answer,
        "answer_source": ids.answer_source,
        "relevance_source": ids.relevance_source,
        "rewrite_source": ids.rewrite_source,
        "hard_answer_source": ids.hard_answer_source,
        "escalation_policy": ids.escalation_policy,
    }
    key = role.strip().lower().replace("-", "_")
    if key in {"answer", "rag_answer"}:
        values["answer"] = model_id
        values["answer_source"] = source
    elif key in {"relevance", "rag_relevance"}:
        values["relevance"] = model_id
        values["relevance_source"] = source
    elif key in {"rewrite", "rag_rewrite"}:
        values["rewrite"] = model_id
        values["rewrite_source"] = source
    elif key in {"hard_answer", "rag_hard_answer", "hard"}:
        values["hard_answer"] = model_id
        values["hard_answer_source"] = source
    else:
        raise ValueError(f"Unknown RAG model role: {role!r}")
    return RagModelIds(**values)  # type: ignore[arg-type]


def selection_audit_event(
    ids: RagModelIds,
    *,
    role: str,
) -> dict[str, Any]:
    """Low-cardinality audit payload for model governance events."""
    normalized = role.strip().lower().replace("-", "_")
    mapping = {
        "answer": (ids.answer, ids.answer_source),
        "relevance": (ids.relevance, ids.relevance_source),
        "rewrite": (ids.rewrite, ids.rewrite_source),
        "hard_answer": (ids.hard_answer, ids.hard_answer_source),
    }
    if normalized not in mapping:
        raise ValueError(f"Unknown RAG model role: {role!r}")
    model_id, source = mapping[normalized]
    return {
        "role": normalized,
        "selectedModel": model_id,
        "source": source,
        "escalationPolicy": ids.escalation_policy,
        "escalationReason": None,
    }


__all__ = [
    "RAG_ANSWER_ESCALATION_POLICIES",
    "RagModelBundle",
    "RagModelIds",
    "apply_governance_model_override",
    "build_rag_model_bundle",
    "governance_overrides_from_runtime",
    "resolve_rag_model_ids",
    "selection_audit_event",
]
