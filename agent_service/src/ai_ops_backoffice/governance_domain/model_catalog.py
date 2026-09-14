"""Which model configs the control plane can switch, and how."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .constants import PROVIDER_MODELS
from .errors import GovernanceValidationError

ModelEffect = Literal["next_request", "reindex", "service_refresh"]
ModelFamily = Literal["chat", "embedding", "file_search"]

CHAT_MODELS: dict[str, frozenset[str]] = {
    "google_genai": frozenset(
        {
            "gemini-3.8-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        }
    ),
    "azure_openai": frozenset(PROVIDER_MODELS["azure_openai"]),
}
EMBEDDING_MODELS: dict[str, frozenset[str]] = {
    "google_genai": frozenset({"gemini-embedding-2"}),
}
FILE_SEARCH_MODELS: dict[str, frozenset[str]] = {
    "google_genai": frozenset(
        {
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
        }
    ),
}


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

_BY_CONFIG_ID = {item.config_id: item for item in MODEL_COMPONENTS}
_BY_COMPONENT = {item.component: item for item in MODEL_COMPONENTS}
_ALIASES = {
    "issue_extractor": "issue-extractor",
    "rag_answer": "rag-answer",
    "file_search": "file-search",
}
_FAMILIES: dict[ModelFamily, dict[str, frozenset[str]]] = {
    "chat": CHAT_MODELS,
    "embedding": EMBEDDING_MODELS,
    "file_search": FILE_SEARCH_MODELS,
}


def model_component(
    config_id: str | None = None, component: str | None = None
) -> ModelComponentSpec:
    if config_id and config_id in _BY_CONFIG_ID:
        return _BY_CONFIG_ID[config_id]
    key = _ALIASES.get(component or "", component or "")
    if key in _BY_COMPONENT:
        return _BY_COMPONENT[key]
    raise GovernanceValidationError("model component is not in the control-plane catalog")


def component_effect(config_id: str) -> ModelEffect:
    return model_component(config_id=config_id).effect


def allowlist_for(spec: ModelComponentSpec, provider: str) -> frozenset[str]:
    return _FAMILIES[spec.family].get(provider, frozenset())


def assert_component_models(
    *,
    config_id: str,
    component: str,
    provider: str,
    model_id: str,
    fallback_model_id: str | None,
) -> ModelComponentSpec:
    spec = model_component(config_id=config_id, component=component)
    if spec.component != _ALIASES.get(component, component) and component not in {
        spec.component,
        spec.config_id,
    }:
        raise GovernanceValidationError("component does not match the model config")
    allowed = allowlist_for(spec, provider)
    if model_id not in allowed:
        raise GovernanceValidationError("model is not on the component allowlist")
    if fallback_model_id and (fallback_model_id not in allowed or fallback_model_id == model_id):
        raise GovernanceValidationError(
            "fallback model must be a different model in the same component allowlist"
        )
    return spec


def component_catalog_payload() -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for spec in MODEL_COMPONENTS:
        families = _FAMILIES[spec.family]
        items.append(
            {
                "configId": spec.config_id,
                "component": spec.component,
                "role": spec.role,
                "label": spec.label,
                "effect": spec.effect,
                "providers": {provider: sorted(models) for provider, models in families.items()},
            }
        )
    return items
