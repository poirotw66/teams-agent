"""Firestore client factory port for persistent PDF convert jobs."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = [
    "FirestoreClientFactory",
    "configure_firestore_client_factory",
    "get_firestore_client_factory",
]


@runtime_checkable
class FirestoreClientFactory(Protocol):
    def create(self, project_id: str | None, database_id: str | None) -> Any:
        ...


_firestore_client_factory: FirestoreClientFactory | None = None


def configure_firestore_client_factory(
    factory: FirestoreClientFactory | None,
) -> None:
    """Register composition-owned sync Firestore client factory."""

    global _firestore_client_factory
    _firestore_client_factory = factory


def get_firestore_client_factory() -> FirestoreClientFactory | None:
    return _firestore_client_factory
