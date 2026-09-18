"""Canonical target-manifest hashing shared by publish gates and evaluation.

Knowledge / FAQ activation and Quality Gate decisions must use the same
``target_manifest_hash`` contract (Spec 7.1). Passing a corpus or content hash
alone is not sufficient.

Pure hashing and env-based gate helpers live in ``knowledge_core.target_manifest``.
This module keeps Agent-enriched ``resolve_publish_manifest_defaults`` (RagSettings)
and re-exports the shared helpers for compatibility.
"""

from __future__ import annotations

import json
import os
from typing import Any

from knowledge_core.target_manifest import (
    calculate_target_manifest_hash,
    faq_version_gate_manifest,
    faq_version_target_manifest_hash,
    knowledge_release_gate_manifest,
    knowledge_release_target_manifest_hash,
)


def resolve_publish_manifest_defaults() -> dict[str, Any]:
    """Load live app/prompt/model/retriever settings for publish gate manifests.

    Prefer explicit candidate env overrides, then a JSON candidate snapshot, then
    live ``RagSettings`` so publish hashes reflect the system under evaluation
    rather than hard-coded placeholders.
    """

    snapshot = _load_candidate_manifest_snapshot()
    rag = _load_rag_settings()

    model_id = (
        os.environ.get("GATE_CANDIDATE_MODEL_ID", "").strip()
        or str(snapshot.get("model_id") or "").strip()
        or os.environ.get("AGENT_MODEL", "").strip()
        or os.environ.get("RAG_MODEL", "").strip()
        or str(getattr(rag, "agent_model", None) or getattr(rag, "model", None) or "").strip()
        or "google_genai:gemini-3.8-flash"
    )
    prompt_version = (
        os.environ.get("GATE_CANDIDATE_PROMPT_VERSION", "").strip()
        or str(snapshot.get("prompt_version") or "").strip()
        or "default"
    )
    app_revision = (
        os.environ.get("GATE_CANDIDATE_APP_REVISION", "").strip()
        or os.environ.get("APP_REVISION", "").strip()
        or str(snapshot.get("app_revision") or "").strip()
        or "v1"
    )
    retriever_config: dict[str, Any] = {}
    snapshot_retriever = snapshot.get("retriever_config")
    if isinstance(snapshot_retriever, dict):
        retriever_config.update(snapshot_retriever)

    top_k = os.environ.get("RAG_TOP_K", "").strip()
    min_score = os.environ.get("RAG_MIN_SCORE", "").strip()
    if top_k:
        try:
            retriever_config["top_k"] = int(top_k)
        except ValueError:
            pass
    elif "top_k" not in retriever_config and rag is not None:
        retriever_config["top_k"] = int(getattr(rag, "top_k", 4))
    if min_score:
        try:
            retriever_config["min_score"] = float(min_score)
        except ValueError:
            pass
    elif "min_score" not in retriever_config and rag is not None:
        retriever_config["min_score"] = float(getattr(rag, "min_score", 0.08))
    embedding_model = os.environ.get("RAG_EMBEDDING_MODEL", "").strip()
    if embedding_model:
        retriever_config["embedding_model"] = embedding_model
    elif "embedding_model" not in retriever_config and rag is not None:
        emb = getattr(rag, "embedding_model", None)
        if emb:
            retriever_config["embedding_model"] = str(emb)
    return {
        "app_revision": app_revision,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "retriever_config": retriever_config,
    }


def _load_candidate_manifest_snapshot() -> dict[str, Any]:
    path = os.environ.get("GATE_CANDIDATE_MANIFEST_PATH", "").strip()
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_rag_settings() -> Any | None:
    try:
        from agent_service.settings import RagSettings

        return RagSettings.from_env()
    except Exception:
        return None


__all__ = [
    "calculate_target_manifest_hash",
    "faq_version_gate_manifest",
    "faq_version_target_manifest_hash",
    "knowledge_release_gate_manifest",
    "knowledge_release_target_manifest_hash",
    "resolve_publish_manifest_defaults",
]
