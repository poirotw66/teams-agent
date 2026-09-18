"""Shared Firestore client factories for Agent and Backoffice.

Keeps google-cloud-firestore construction out of domain packages so Backoffice
repository wiring does not import Agent store implementations.
"""

from __future__ import annotations

from typing import Any


def build_sync_firestore_client(project: str | None, database: str | None) -> Any:
    """Sync client for repositories that call get/set/stream without await."""
    try:
        from google.cloud.firestore import Client
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "OPS_STORE_MODE=FIRESTORE requires google-cloud-firestore."
        ) from exc
    kwargs: dict[str, str] = {}
    if project:
        kwargs["project"] = project
    if database:
        kwargs["database"] = database
    return Client(**kwargs)


def build_firestore_client(project: str | None, database: str | None) -> Any:
    """Async Firestore client for operational event stores."""
    try:
        from google.cloud.firestore import AsyncClient
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "OPS_STORE_MODE=FIRESTORE requires google-cloud-firestore."
        ) from exc
    kwargs: dict[str, str] = {}
    if project:
        kwargs["project"] = project
    if database:
        kwargs["database"] = database
    return AsyncClient(**kwargs)
