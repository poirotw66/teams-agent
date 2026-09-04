"""Shared governance repository factory for Backoffice and Agent runtimes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from .repository import (
    FileGovernanceRepository,
    FirestoreGovernanceRepository,
    GovernanceRepository,
)

logger = logging.getLogger(__name__)

GovernanceStoreMode = Literal["FILE", "FIRESTORE", "FIRESTORE_SHARDED", "FIRESTORE_SPLIT"]
SUPPORTED_GOVERNANCE_STORE_MODES = frozenset(
    {"FILE", "FIRESTORE", "FIRESTORE_SHARDED", "FIRESTORE_SPLIT"}
)


def normalize_governance_store_mode(mode: str) -> str:
    normalized = (mode or "FILE").strip().upper()
    if normalized not in SUPPORTED_GOVERNANCE_STORE_MODES:
        raise ValueError(
            "AI_OPS_GOVERNANCE_STORE_MODE must be one of "
            "FILE, FIRESTORE, FIRESTORE_SHARDED, or FIRESTORE_SPLIT."
        )
    return normalized


def build_governance_repository(
    *,
    store_mode: str,
    file_path: Path | None = None,
    firestore_project: str | None = None,
    firestore_database: str | None = None,
    firestore_collection: str = "ai_ops_governance_state",
    firestore_client: Any | None = None,
) -> GovernanceRepository:
    mode = normalize_governance_store_mode(store_mode)
    if mode == "FILE":
        if file_path is None:
            raise ValueError("FILE governance store requires a path.")
        return FileGovernanceRepository(file_path)
    from google.cloud import firestore

    client = firestore_client
    if client is None:
        client_kwargs: dict[str, Any] = {}
        if firestore_project:
            client_kwargs["project"] = firestore_project
        if firestore_database:
            client_kwargs["database"] = firestore_database
        client = firestore.Client(**client_kwargs)
    if mode == "FIRESTORE":
        return FirestoreGovernanceRepository(client, collection=firestore_collection)
    from .sharded_repository import ShardedFirestoreGovernanceRepository

    return ShardedFirestoreGovernanceRepository(client, collection=firestore_collection)
