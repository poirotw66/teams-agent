"""Adopt scheduled embedding indexes and refresh the File Search client."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from .graph import RagAgent
from .knowledge_backends import KnowledgeBackendRouter
from .knowledge_release import read_active_release_id, release_index_path
from .retrieval import HybridIndex
from .service_scope_evidence import (
    configure_service_scope_from_release,
    reset_service_scope_catalog,
)
from .settings import RagSettings
from .source_refs import hydrate_index_sources
from .workflow import build_knowledge_service


@dataclass(frozen=True)
class AdoptResult:
    adopted: bool
    embedding_model: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ApplyResult:
    applied: bool
    model: str | None = None
    previous_model: str | None = None
    reason: str | None = None


def index_embedding_model(index_path: Path) -> str | None:
    if not index_path.is_file():
        return None
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    model = payload.get("embeddingModel")
    return str(model) if model else None


def scheduled_index_path(app: FastAPI, settings: RagSettings) -> tuple[Path, str | None]:
    release_dir = settings.knowledge_release_dir or (settings.data_dir / "releases")
    active_id = read_active_release_id(release_dir)
    if active_id:
        return release_index_path(release_dir, active_id), active_id
    current = getattr(app.state, "knowledge_index_path", settings.index_path)
    return Path(current), getattr(app.state, "knowledge_release_id", None)


def adopt_embedding_index(
    app: FastAPI,
    settings: RagSettings,
    expected_model_id: str,
) -> AdoptResult:
    """Load an index only when its embedding model matches the scheduled id."""

    if not expected_model_id.strip():
        return AdoptResult(adopted=False, reason="scheduled embedding model is missing")
    index_path, release_id = scheduled_index_path(app, settings)
    recorded = index_embedding_model(index_path)
    if recorded != expected_model_id:
        return AdoptResult(
            adopted=False,
            embedding_model=recorded,
            reason="index embedding model does not match the scheduled model",
        )
    previous = getattr(app.state, "index", None)
    try:
        new_index = HybridIndex.load(index_path, expected_model_id)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return AdoptResult(adopted=False, reason=type(exc).__name__)
    if new_index.embedding_model_name != expected_model_id:
        return AdoptResult(
            adopted=False,
            embedding_model=new_index.embedding_model_name,
            reason="loaded index embedding model does not match the scheduled model",
        )
    try:
        _install_index(app, settings, new_index, index_path, release_id)
    except Exception as exc:  # noqa: BLE001
        if previous is not None:
            app.state.index = previous
        return AdoptResult(adopted=False, reason=type(exc).__name__)
    return AdoptResult(adopted=True, embedding_model=new_index.embedding_model_name)


def apply_file_search_model(app: FastAPI, model_id: str) -> ApplyResult:
    """Refresh the running File Search client. Leave it unchanged on failure."""

    if not model_id.strip():
        return ApplyResult(applied=False, reason="scheduled file search model is missing")
    router = getattr(app.state, "knowledge_router", None)
    getter = getattr(router, "get_service", None)
    service = getter("GEMINI_FILE_SEARCH") if callable(getter) else None
    if service is None or not hasattr(service, "model"):
        return ApplyResult(applied=False, reason="file search client is not running")
    previous = str(service.model)
    service.model = model_id
    return ApplyResult(applied=True, model=model_id, previous_model=previous)


def restore_file_search_model(app: FastAPI, model_id: str) -> None:
    router = getattr(app.state, "knowledge_router", None)
    getter = getattr(router, "get_service", None)
    service = getter("GEMINI_FILE_SEARCH") if callable(getter) else None
    if service is not None and hasattr(service, "model"):
        service.model = model_id


def embedding_model_for_load(app: FastAPI, settings: RagSettings) -> str | None:
    runtime = getattr(app.state, "governance_runtime", None)
    resolve = getattr(runtime, "resolve_model", None)
    if resolve is None:
        return settings.embedding_model
    try:
        resolved = resolve(config_id="embedding-model")
    except Exception:  # noqa: BLE001
        return settings.embedding_model
    if getattr(resolved, "source", None) == "governance" and getattr(resolved, "model_id", None):
        return str(resolved.model_id)
    return settings.embedding_model


def _install_index(
    app: FastAPI,
    settings: RagSettings,
    new_index: HybridIndex,
    index_path: Path,
    release_id: str | None,
) -> None:
    release_dir = settings.knowledge_release_dir or (settings.data_dir / "releases")
    hydrate_index_sources(new_index.chunks, release_dir=release_dir, release_id=release_id)
    new_agent = RagAgent(settings, new_index)
    hybrid_settings = getattr(app.state, "hybrid_settings", settings)
    rag_model = getattr(app.state, "rag_model", None)
    new_hybrid = build_knowledge_service(
        hybrid_settings,
        new_index,
        rag_model,
        release_id=release_id,
    )
    router: KnowledgeBackendRouter | None = getattr(app.state, "knowledge_router", None)
    if router is not None:
        router.update_service("HYBRID", new_hybrid)
    app.state.index = new_index
    app.state.knowledge_index_path = index_path
    app.state.knowledge_release_id = release_id
    app.state.knowledge_index_source = "portal_release" if release_id else "bundled_index"
    app.state.agent = new_agent
    if release_id:
        configure_service_scope_from_release(release_dir, release_id)
    else:
        reset_service_scope_catalog()
