"""Provider-safe query embedding batching for hybrid retrieval.

Ensures asymmetric embedding models (e.g. Google GenAI / Vertex AI embeddings)
use RETRIEVAL_QUERY task semantics when embedding queries in batch, rather than
accidentally falling back to RETRIEVAL_DOCUMENT semantics from embed_documents().
"""

from __future__ import annotations

import inspect
import logging
import time
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)


def is_transient_embedding_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    markers = (
        "503",
        "unavailable",
        "429",
        "resource_exhausted",
        "timeout",
        "timed out",
        "reset",
        "deadline",
        "disconnected",
        "remote protocol",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "internal error",
        "500",
    )
    return any(marker in msg for marker in markers)


def _is_transient_embedding_error(exc: BaseException) -> bool:
    return is_transient_embedding_error(exc)


def _retry_on_transient(
    func: Any,
    *args: Any,
    max_attempts: int = 5,
    initial_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if attempt == max_attempts or not _is_transient_embedding_error(exc):
                raise
            logger.warning(
                "Transient embedding error on attempt %d/%d: %s. Retrying in %.2fs...",
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
            delay = min(delay * 2.0, 30.0)


def _vertex_embedding_batch_size() -> int | None:
    """Vertex Embedding 2 accepts one content per embedContent request."""
    from .gemini_backend import GeminiApiBackend, peek_gemini_api_backend

    if peek_gemini_api_backend() is GeminiApiBackend.VERTEX_AI:
        return 1
    return None


def _is_single_content_embed_limit(exc: BaseException) -> bool:
    return "only supports one content at a time" in str(exc).lower()


def _embed_documents_call(
    client: Any,
    texts: list[str],
    *,
    task_type: str | None = None,
) -> list[list[float]]:
    kwargs: dict[str, Any] = {}
    try:
        parameters = inspect.signature(client.embed_documents).parameters
    except (TypeError, ValueError):
        parameters = {}
    if task_type is not None and "task_type" in parameters:
        kwargs["task_type"] = task_type
    batch_size = _vertex_embedding_batch_size()
    if batch_size is not None and "batch_size" in parameters:
        kwargs["batch_size"] = batch_size
    try:
        return _retry_on_transient(client.embed_documents, texts, **kwargs)
    except TypeError:
        kwargs.pop("batch_size", None)
        kwargs.pop("task_type", None)
        if task_type is not None:
            try:
                return _retry_on_transient(
                    client.embed_documents,
                    texts,
                    task_type=task_type,
                )
            except TypeError:
                pass
        return _retry_on_transient(client.embed_documents, texts)
    except Exception as exc:
        if len(texts) > 1 and _is_single_content_embed_limit(exc):
            return [
                _embed_documents_call(client, [text], task_type=task_type)[0]
                for text in texts
            ]
        raise


def embed_documents_batch(client: Any, texts: Sequence[str]) -> list[list[float]]:
    """Embed documents. Vertex Embedding 2 is called one content at a time."""
    if not texts or client is None:
        return []
    if not hasattr(client, "embed_documents") or not callable(client.embed_documents):
        raise TypeError("Embedding client does not provide embed_documents.")
    return _embed_documents_call(client, list(texts))


def embed_queries_batch(client: Any, texts: Sequence[str]) -> list[list[float]]:
    """Embed multiple query strings ensuring RETRIEVAL_QUERY task semantics.

    For providers distinguishing query from document embeddings (such as Google GenAI),
    explicitly enforces RETRIEVAL_QUERY so facet / rewrite queries are not embedded
    into the document task space.
    """
    if not texts or client is None:
        return []

    text_list = list(texts)

    # 1. If client provides a native embed_queries method
    if hasattr(client, "embed_queries") and callable(client.embed_queries):
        try:
            return _retry_on_transient(client.embed_queries, text_list)
        except Exception as exc:
            logger.debug("embed_queries native call failed, falling back: %s", exc)

    # 2. Check embed_documents with task_type parameter (e.g. GoogleGenerativeAIEmbeddings)
    if hasattr(client, "embed_documents") and callable(client.embed_documents):
        try:
            return _embed_documents_call(
                client,
                text_list,
                task_type="RETRIEVAL_QUERY",
            )
        except TypeError:
            pass

        # For symmetric embedding providers (e.g. OpenAI, HuggingFace, FakeEmbeddings)
        try:
            return _embed_documents_call(client, text_list)
        except Exception as exc:
            logger.debug("embed_documents batch call failed, falling back to per-query: %s", exc)

    # 3. Fallback to individual embed_query calls
    if hasattr(client, "embed_query") and callable(client.embed_query):
        return [_retry_on_transient(client.embed_query, t) for t in text_list]

    return [[] for _ in text_list]


def embed_single_query(client: Any, text: str) -> list[float]:
    """Embed a single query string using RETRIEVAL_QUERY task semantics."""
    if not text or client is None:
        return []
    if hasattr(client, "embed_query") and callable(client.embed_query):
        return _retry_on_transient(client.embed_query, text)
    batch = embed_queries_batch(client, [text])
    return batch[0] if batch else []


def _normalize_embedding_model_id(model_id: str) -> str:
    """Compare embedding ids with or without provider prefix."""

    normalized = model_id.strip()
    if ":" in normalized:
        return normalized.split(":", 1)[1].strip()
    return normalized


def _embedding_models_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    return _normalize_embedding_model_id(left) == _normalize_embedding_model_id(right)


def _payload_has_vectors(payload: dict[str, object]) -> bool:
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        return False
    return any(
        isinstance(chunk, dict)
        and isinstance(chunk.get("vector"), list)
        and bool(chunk.get("vector"))
        for chunk in chunks
    )


def _format_provenance_side(label: str, provenance: object) -> str:
    rendered_dimensions = (
        "none" if getattr(provenance, "dimensions", None) is None else str(provenance.dimensions)
    )
    return (
        f"{label} backend={getattr(provenance, 'backend', None) or 'none'} "
        f"model={getattr(provenance, 'model', None) or 'none'} "
        f"location={getattr(provenance, 'vertex_location', None) or 'none'} "
        f"dimensions={rendered_dimensions}"
    )


def embedding_index_mismatch_error(
    payload: dict[str, object],
    runtime_model: str | None,
) -> ValueError:
    from .gemini_clients import current_embedding_provenance, provenance_from_index_payload

    index = provenance_from_index_payload(payload)
    runtime = current_embedding_provenance(
        runtime_model,
        dimensions=index.dimensions,
    )
    return ValueError(
        "Configured embedding backend/model/location/dimensions do not "
        "match the built index. "
        f"{_format_provenance_side('Process', runtime)}; "
        f"{_format_provenance_side('index', index)}. "
        "Rebuild the release instead of treating a matching model ID as "
        "compatibility or masking the mismatch with sparse-only search."
    )


def index_embedding_compatible(
    payload: dict[str, object],
    runtime_model: str | None,
) -> bool:
    """Require provenance match. Model-id equality alone is not enough."""
    from .gemini_backend import GeminiApiBackend, resolve_gemini_backend
    from .gemini_clients import embedding_payloads_compatible

    config = resolve_gemini_backend()
    has_vectors = _payload_has_vectors(payload)
    indexed_model = payload.get("embeddingModel")
    if config.backend is GeminiApiBackend.VERTEX_AI:
        if has_vectors or indexed_model:
            if not runtime_model:
                return False
            return embedding_payloads_compatible(
                payload,
                runtime_model,
                allow_developer_api_grandfather=False,
            )
        return True
    if not runtime_model or not indexed_model:
        return True
    return embedding_payloads_compatible(
        payload,
        runtime_model,
        allow_developer_api_grandfather=True,
    )


__all__ = [
    "embed_documents_batch",
    "embed_queries_batch",
    "embed_single_query",
    "embedding_index_mismatch_error",
    "index_embedding_compatible",
    "is_transient_embedding_error",
]

