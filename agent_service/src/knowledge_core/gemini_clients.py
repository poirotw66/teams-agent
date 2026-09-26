"""Shared Gemini chat/embedding construction for the selected backend."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .gemini_backend import (
    GeminiApiBackend,
    GeminiBackendConfig,
    GeminiConfigurationError,
    assert_vertex_process_has_no_api_keys,
    is_google_genai_model,
    require_developer_api_key,
    resolve_gemini_backend,
    strip_model_provider,
)
from .gemini_errors import raise_classified_gemini_error

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

# Gemini 3.8 Flash rejects temperature / top_p / top_k on Vertex.
MODELS_WITHOUT_SAMPLING_PARAMS: frozenset[str] = frozenset(
    {
        "gemini-3.8-flash",
        "models/gemini-3.8-flash",
    }
)


@dataclass(frozen=True)
class EmbeddingProvenance:
    backend: str | None
    model: str | None
    vertex_location: str | None
    dimensions: int | None

    def has_complete_fields(self) -> bool:
        if not self.backend or not self.model or self.dimensions is None:
            return False
        if self.backend == GeminiApiBackend.VERTEX_AI.value:
            return bool(self.vertex_location)
        return True

    def to_index_fields(self) -> dict[str, object]:
        return {
            "embeddingBackend": self.backend,
            "embeddingVertexLocation": self.vertex_location,
            "embeddingDimensions": self.dimensions,
        }


def filter_chat_model_kwargs(
    model_name: str,
    kwargs: dict[str, Any],
    *,
    backend: GeminiApiBackend,
) -> dict[str, Any]:
    """Drop sampling params Vertex rejects; keep Developer API regression behavior."""
    if backend is not GeminiApiBackend.VERTEX_AI:
        return kwargs
    bare = strip_model_provider(model_name).lower()
    if bare not in MODELS_WITHOUT_SAMPLING_PARAMS:
        return kwargs
    filtered = dict(kwargs)
    for name in ("temperature", "top_p", "top_k"):
        filtered.pop(name, None)
    return filtered


def chat_model_init_kwargs(
    model_name: str,
    *,
    temperature: float | None = 0.0,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    reasoning_effort: str | None = None,
    config: GeminiBackendConfig | None = None,
    eval_mode: bool = False,
) -> dict[str, Any]:
    """Build ``init_chat_model`` kwargs. Non-Gemini providers stay unchanged."""
    kwargs: dict[str, Any] = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort
    if not is_google_genai_model(model_name):
        return kwargs
    resolved = config or resolve_gemini_backend()
    if resolved.is_developer_api:
        require_developer_api_key()
        return kwargs
    assert_vertex_process_has_no_api_keys()
    kwargs["vertexai"] = True
    kwargs["project"] = resolved.project_for_requests(eval_mode=eval_mode)
    kwargs["location"] = resolved.location_for_chat(eval_mode=eval_mode)
    return filter_chat_model_kwargs(model_name, kwargs, backend=resolved.backend)


def build_embeddings(
    model_name: str | None,
    *,
    config: GeminiBackendConfig | None = None,
    eval_mode: bool = False,
) -> Any | None:
    """Construct embeddings for the selected backend.

    Gemini clients are built with explicit Vertex or Developer API options.
    ``init_embeddings`` is used only for non-Gemini providers.
    """
    if not model_name:
        return None
    try:
        if is_google_genai_model(model_name):
            return _build_google_genai_embeddings(
                model_name,
                config=config,
                eval_mode=eval_mode,
            )
        from langchain.embeddings import init_embeddings

        return init_embeddings(model_name)
    except Exception as error:  # noqa: BLE001 - process boundary classification
        raise_classified_gemini_error(error, context="build_embeddings")
        raise


def build_genai_sdk_client_kwargs(
    *,
    config: GeminiBackendConfig | None = None,
    require_pdf_location: bool = False,
    eval_mode: bool = False,
) -> dict[str, Any]:
    """Kwargs for ``google.genai.Client`` (PDF Vision / File Search)."""
    resolved = config or resolve_gemini_backend(require_pdf_location=require_pdf_location)
    if resolved.is_developer_api:
        return {"api_key": require_developer_api_key()}
    assert_vertex_process_has_no_api_keys()
    location = (
        resolved.pdf_location
        if require_pdf_location
        else resolved.location_for_chat(eval_mode=eval_mode)
    )
    if require_pdf_location and not location:
        raise GeminiConfigurationError(
            "VERTEX_AI PDF Vision requires VERTEX_AI_PDF_LOCATION."
        )
    return {
        "vertexai": True,
        "project": resolved.project_for_requests(eval_mode=eval_mode),
        "location": location,
    }


def current_embedding_provenance(
    model_name: str | None,
    *,
    dimensions: int | None = None,
    chunks: Sequence[Any] | None = None,
    config: GeminiBackendConfig | None = None,
) -> EmbeddingProvenance:
    resolved = config or resolve_gemini_backend()
    inferred = dimensions
    if inferred is None and chunks is not None:
        inferred = _first_vector_dimensions(chunks)
    backend = resolved.backend.value if is_google_genai_model(model_name) else None
    location = None
    if backend == GeminiApiBackend.VERTEX_AI.value:
        location = resolved.location_for_embedding()
    elif backend == GeminiApiBackend.DEVELOPER_API.value:
        location = None
    return EmbeddingProvenance(
        backend=backend,
        model=model_name,
        vertex_location=location,
        dimensions=inferred,
    )


def provenance_from_index_payload(payload: dict[str, Any]) -> EmbeddingProvenance:
    dimensions = payload.get("embeddingDimensions")
    if dimensions is None:
        dimensions = _first_vector_dimensions_from_payload(payload)
    return EmbeddingProvenance(
        backend=_optional_str(payload.get("embeddingBackend")),
        model=_optional_str(payload.get("embeddingModel")),
        vertex_location=_optional_str(payload.get("embeddingVertexLocation")),
        dimensions=int(dimensions) if dimensions is not None else None,
    )


def embedding_release_compatible(
    index: EmbeddingProvenance,
    runtime: EmbeddingProvenance,
    *,
    indexed_model: str | None,
    runtime_model: str | None,
) -> bool:
    """Full provenance match. Missing fields are not compatible by model ID."""
    if not index.has_complete_fields() or not runtime.has_complete_fields():
        return False
    return (
        index.backend == runtime.backend
        and _model_ids_match(index.model or indexed_model, runtime.model or runtime_model)
        and index.vertex_location == runtime.vertex_location
        and index.dimensions == runtime.dimensions
    )


def embedding_payloads_compatible(
    payload: dict[str, Any],
    runtime_model: str | None,
    *,
    allow_developer_api_grandfather: bool = False,
) -> bool:
    index = provenance_from_index_payload(payload)
    runtime = current_embedding_provenance(
        runtime_model,
        dimensions=index.dimensions,
    )
    if embedding_release_compatible(
        index,
        runtime,
        indexed_model=index.model,
        runtime_model=runtime_model,
    ):
        return True
    return allow_developer_api_grandfather and _developer_api_grandfather_ok(
        index, runtime, runtime_model
    )


def _developer_api_grandfather_ok(
    index: EmbeddingProvenance,
    runtime: EmbeddingProvenance,
    runtime_model: str | None,
) -> bool:
    """Load old Developer API indexes. This is not a compatibility proof."""
    if runtime.backend != GeminiApiBackend.DEVELOPER_API.value:
        return False
    if index.backend not in {None, GeminiApiBackend.DEVELOPER_API.value}:
        return False
    return _model_ids_match(index.model, runtime_model)


def _build_google_genai_embeddings(
    model_name: str,
    *,
    config: GeminiBackendConfig | None,
    eval_mode: bool,
) -> Any:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    resolved = config or resolve_gemini_backend()
    kwargs: dict[str, Any] = {"model": strip_model_provider(model_name)}
    if resolved.is_developer_api:
        require_developer_api_key()
        return GoogleGenerativeAIEmbeddings(**kwargs)
    assert_vertex_process_has_no_api_keys()
    kwargs["vertexai"] = True
    kwargs["project"] = resolved.project_for_requests(eval_mode=eval_mode)
    kwargs["location"] = resolved.location_for_embedding(eval_mode=eval_mode)
    return GoogleGenerativeAIEmbeddings(**kwargs)


def _model_ids_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    return strip_model_provider(left) == strip_model_provider(right)


def _first_vector_dimensions(chunks: Sequence[Any]) -> int | None:
    for chunk in chunks:
        vector = getattr(chunk, "vector", None)
        if isinstance(vector, list) and vector:
            return len(vector)
    return None


def _first_vector_dimensions_from_payload(payload: dict[str, Any]) -> int | None:
    for raw in payload.get("chunks") or []:
        if not isinstance(raw, dict):
            continue
        vector = raw.get("vector")
        if isinstance(vector, list) and vector:
            return len(vector)
    return None


def _optional_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
