"""Compatibility shim. Implementation lives in ``knowledge_core.gemini_clients``."""

from knowledge_core.gemini_clients import (
    MODELS_WITHOUT_SAMPLING_PARAMS,
    EmbeddingProvenance,
    build_embeddings,
    build_genai_sdk_client_kwargs,
    chat_model_init_kwargs,
    current_embedding_provenance,
    embedding_payloads_compatible,
    embedding_release_compatible,
    filter_chat_model_kwargs,
    provenance_from_index_payload,
)

__all__ = [
    "MODELS_WITHOUT_SAMPLING_PARAMS",
    "EmbeddingProvenance",
    "build_embeddings",
    "build_genai_sdk_client_kwargs",
    "chat_model_init_kwargs",
    "current_embedding_provenance",
    "embedding_payloads_compatible",
    "embedding_release_compatible",
    "filter_chat_model_kwargs",
    "provenance_from_index_payload",
]
