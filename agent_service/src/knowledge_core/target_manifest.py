"""Canonical target-manifest hashing shared by publish gates and evaluation.

Knowledge / FAQ activation and Quality Gate decisions must use the same
``target_manifest_hash`` contract (Spec 7.1). Passing a corpus or content hash
alone is not sufficient.

This module uses environment variables and hardcoded fallbacks only. Agent
runtime enrichment via ``RagSettings`` stays in ``agent_service.target_manifest``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any


def calculate_target_manifest_hash(payload: dict[str, Any]) -> str:
    """Computes an immutable SHA-256 hash from canonical manifest fields."""
    canonical = {
        "target_id": payload.get("target_id", ""),
        "target_side": payload.get("target_side", ""),
        "app_revision": payload.get("app_revision", "v1"),
        "prompt_version": payload.get("prompt_version", "default"),
        "model_id": payload.get("model_id", "google_genai:gemini-3.8-flash"),
        "temperature": payload.get("temperature", 0.0),
        "knowledge_release_id": payload.get("knowledge_release_id"),
        "faq_version_id": payload.get("faq_version_id"),
        "retriever_config": payload.get("retriever_config", {}),
        "persona_fixture_id": payload.get("persona_fixture_id"),
        "acl_policy": payload.get("acl_policy", "STRICT"),
        "environment": payload.get("environment", "test"),
    }
    dumped = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


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


def _resolve_env_manifest_defaults() -> dict[str, Any]:
    """Resolve publish-gate defaults from env/snapshot only (no RagSettings)."""
    snapshot = _load_candidate_manifest_snapshot()

    model_id = (
        os.environ.get("GATE_CANDIDATE_MODEL_ID", "").strip()
        or str(snapshot.get("model_id") or "").strip()
        or os.environ.get("AGENT_MODEL", "").strip()
        or os.environ.get("RAG_MODEL", "").strip()
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
    if min_score:
        try:
            retriever_config["min_score"] = float(min_score)
        except ValueError:
            pass
    embedding_model = os.environ.get("RAG_EMBEDDING_MODEL", "").strip()
    if embedding_model:
        retriever_config["embedding_model"] = embedding_model
    return {
        "app_revision": app_revision,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "retriever_config": retriever_config,
    }


def knowledge_release_gate_manifest(
    *,
    release_id: str,
    environment: str = "prod",
    app_revision: str | None = None,
    prompt_version: str | None = None,
    model_id: str | None = None,
    retriever_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical candidate target used when gating a knowledge release activation."""
    defaults = _resolve_env_manifest_defaults()
    return {
        "target_id": f"knowledge:{release_id}",
        "target_side": "CANDIDATE",
        "app_revision": app_revision or defaults["app_revision"],
        "prompt_version": prompt_version or defaults["prompt_version"],
        "model_id": model_id or defaults["model_id"],
        "temperature": 0.0,
        "knowledge_release_id": release_id,
        "faq_version_id": None,
        "retriever_config": (
            retriever_config
            if retriever_config is not None
            else defaults["retriever_config"]
        ),
        "persona_fixture_id": None,
        "acl_policy": "STRICT",
        "environment": environment,
    }


def faq_version_gate_manifest(
    *,
    faq_version_id: str,
    environment: str = "prod",
    app_revision: str | None = None,
    prompt_version: str | None = None,
    model_id: str | None = None,
    retriever_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical candidate target used when gating FAQ activation."""
    defaults = _resolve_env_manifest_defaults()
    return {
        "target_id": f"faq:{faq_version_id}",
        "target_side": "CANDIDATE",
        "app_revision": app_revision or defaults["app_revision"],
        "prompt_version": prompt_version or defaults["prompt_version"],
        "model_id": model_id or defaults["model_id"],
        "temperature": 0.0,
        "knowledge_release_id": None,
        "faq_version_id": faq_version_id,
        "retriever_config": (
            retriever_config
            if retriever_config is not None
            else defaults["retriever_config"]
        ),
        "persona_fixture_id": None,
        "acl_policy": "STRICT",
        "environment": environment,
    }


def knowledge_release_target_manifest_hash(
    *,
    release_id: str,
    environment: str = "prod",
    app_revision: str | None = None,
    prompt_version: str | None = None,
    model_id: str | None = None,
    retriever_config: dict[str, Any] | None = None,
) -> str:
    return calculate_target_manifest_hash(
        knowledge_release_gate_manifest(
            release_id=release_id,
            environment=environment,
            app_revision=app_revision,
            prompt_version=prompt_version,
            model_id=model_id,
            retriever_config=retriever_config,
        )
    )


def faq_version_target_manifest_hash(
    *,
    faq_version_id: str,
    environment: str = "prod",
    app_revision: str | None = None,
    prompt_version: str | None = None,
    model_id: str | None = None,
    retriever_config: dict[str, Any] | None = None,
) -> str:
    return calculate_target_manifest_hash(
        faq_version_gate_manifest(
            faq_version_id=faq_version_id,
            environment=environment,
            app_revision=app_revision,
            prompt_version=prompt_version,
            model_id=model_id,
            retriever_config=retriever_config,
        )
    )


__all__ = [
    "calculate_target_manifest_hash",
    "faq_version_gate_manifest",
    "faq_version_target_manifest_hash",
    "knowledge_release_gate_manifest",
    "knowledge_release_target_manifest_hash",
]
