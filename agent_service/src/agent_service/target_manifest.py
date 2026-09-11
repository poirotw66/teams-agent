"""Canonical target-manifest hashing shared by publish gates and evaluation.

Knowledge / FAQ activation and Quality Gate decisions must use the same
``target_manifest_hash`` contract (Spec 7.1). Passing a corpus or content hash
alone is not sufficient.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def calculate_target_manifest_hash(payload: dict[str, Any]) -> str:
    """Computes an immutable SHA-256 hash from canonical manifest fields."""
    canonical = {
        "target_id": payload.get("target_id", ""),
        "target_side": payload.get("target_side", ""),
        "app_revision": payload.get("app_revision", "v1"),
        "prompt_version": payload.get("prompt_version", "default"),
        "model_id": payload.get("model_id", "gemini-2.5-flash"),
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


def knowledge_release_gate_manifest(
    *,
    release_id: str,
    environment: str = "prod",
    app_revision: str = "v1",
    prompt_version: str = "default",
    model_id: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """Canonical candidate target used when gating a knowledge release activation."""
    return {
        "target_id": f"knowledge:{release_id}",
        "target_side": "CANDIDATE",
        "app_revision": app_revision,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "temperature": 0.0,
        "knowledge_release_id": release_id,
        "faq_version_id": None,
        "retriever_config": {},
        "persona_fixture_id": None,
        "acl_policy": "STRICT",
        "environment": environment,
    }


def faq_version_gate_manifest(
    *,
    faq_version_id: str,
    environment: str = "prod",
    app_revision: str = "v1",
    prompt_version: str = "default",
    model_id: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """Canonical candidate target used when gating FAQ activation."""
    return {
        "target_id": f"faq:{faq_version_id}",
        "target_side": "CANDIDATE",
        "app_revision": app_revision,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "temperature": 0.0,
        "knowledge_release_id": None,
        "faq_version_id": faq_version_id,
        "retriever_config": {},
        "persona_fixture_id": None,
        "acl_policy": "STRICT",
        "environment": environment,
    }


def knowledge_release_target_manifest_hash(*, release_id: str, environment: str = "prod") -> str:
    return calculate_target_manifest_hash(
        knowledge_release_gate_manifest(release_id=release_id, environment=environment)
    )


def faq_version_target_manifest_hash(*, faq_version_id: str, environment: str = "prod") -> str:
    return calculate_target_manifest_hash(
        faq_version_gate_manifest(faq_version_id=faq_version_id, environment=environment)
    )


__all__ = [
    "calculate_target_manifest_hash",
    "knowledge_release_gate_manifest",
    "faq_version_gate_manifest",
    "knowledge_release_target_manifest_hash",
    "faq_version_target_manifest_hash",
]
