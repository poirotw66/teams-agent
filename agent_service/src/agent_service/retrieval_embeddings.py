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


def _retry_on_transient(func: Any, *args: Any, max_attempts: int = 3, initial_delay: float = 0.5, **kwargs: Any) -> Any:
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            is_transient = any(
                code in msg
                for code in ("503", "unavailable", "429", "resource_exhausted", "timeout", "reset", "deadline")
            )
            if attempt == max_attempts or not is_transient:
                raise
            logger.warning(
                "Transient embedding error on attempt %d/%d: %s. Retrying in %.2fs...",
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
            delay *= 2.0


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
            sig = inspect.signature(client.embed_documents)
            if "task_type" in sig.parameters:
                return _retry_on_transient(client.embed_documents, text_list, task_type="RETRIEVAL_QUERY")
        except (ValueError, TypeError):
            pass

        client_cls_name = type(client).__name__
        if "Google" in client_cls_name or hasattr(client, "task_type"):
            try:
                return _retry_on_transient(client.embed_documents, text_list, task_type="RETRIEVAL_QUERY")
            except TypeError:
                pass

        # For symmetric embedding providers (e.g. OpenAI, HuggingFace, FakeEmbeddings)
        try:
            return _retry_on_transient(client.embed_documents, text_list)
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


__all__ = ["embed_queries_batch", "embed_single_query"]

