"""Catalog draft persistence backends (spec §2.3 multi-instance slice).

``FIRESTORE`` repository mode uses a shared collection so multiple Backoffice
instances see the same draft/review state. Non-Firestore modes keep the local
FILE store for single-node / local-dev fallback.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Protocol, TypeVar

from knowledge_portal.service_catalog_artifact import SERVICE_CATALOG_DRAFT_RELATIVE_PATH
from knowledge_portal.settings import PortalSettings

_T = TypeVar("_T")


class CatalogDraftStore(Protocol):
    """Load/save tenant catalog drafts for governance state machine."""

    @property
    def backend_name(self) -> str:
        """Machine-readable backend id exposed on GET /api/catalog."""

    def load(self, tenant_id: str) -> dict[str, Any] | None:
        """Return the draft payload or None when absent."""

    def save(self, tenant_id: str, payload: dict[str, Any]) -> None:
        """Persist the full draft payload for ``tenant_id``."""


def _safe_tenant(tenant_id: str) -> str:
    return tenant_id.strip().replace("/", "_") or "default"


def _run_coroutine_sync(coroutine: Coroutine[Any, Any, _T]) -> _T:
    """Run async Firestore I/O from sync governance helpers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


class FileCatalogDraftStore:
    """Local filesystem draft store (single-node / local-dev fallback)."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    @property
    def backend_name(self) -> str:
        return "FILE"

    def _path(self, tenant_id: str) -> Path:
        return (
            self._data_dir
            / "tenants"
            / _safe_tenant(tenant_id)
            / SERVICE_CATALOG_DRAFT_RELATIVE_PATH
        )

    def load(self, tenant_id: str) -> dict[str, Any] | None:
        path = self._path(tenant_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("Catalog draft file must contain a JSON object.")
        return payload

    def save(self, tenant_id: str, payload: dict[str, Any]) -> None:
        path = self._path(tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class MemoryCatalogDraftStore:
    """Process-shared dict store for multi-instance simulations in tests."""

    def __init__(self, shared: dict[str, dict[str, Any]] | None = None) -> None:
        self._shared = shared if shared is not None else {}

    @property
    def backend_name(self) -> str:
        return "MEMORY"

    def load(self, tenant_id: str) -> dict[str, Any] | None:
        payload = self._shared.get(_safe_tenant(tenant_id))
        return copy.deepcopy(payload) if payload is not None else None

    def save(self, tenant_id: str, payload: dict[str, Any]) -> None:
        self._shared[_safe_tenant(tenant_id)] = copy.deepcopy(payload)


class FirestoreCatalogDraftStore:
    """Shared Firestore collection for multi-instance catalog drafts."""

    def __init__(
        self,
        settings: PortalSettings,
        *,
        client: Any | None = None,
    ) -> None:
        self._collection_name = settings.catalog_drafts_collection
        if client is not None:
            self._client = client
        else:
            from google.cloud import firestore

            self._client = firestore.AsyncClient(
                project=settings.firestore_project_id,
                database=settings.firestore_database_id,
            )

    @property
    def backend_name(self) -> str:
        return "FIRESTORE"

    def _document(self, tenant_id: str) -> Any:
        return self._client.collection(self._collection_name).document(
            _safe_tenant(tenant_id)
        )

    async def _aload(self, tenant_id: str) -> dict[str, Any] | None:
        snapshot = await self._document(tenant_id).get()
        if not snapshot.exists:
            return None
        payload = snapshot.to_dict()
        if not isinstance(payload, dict):
            raise TypeError("Catalog draft Firestore document must be an object.")
        return payload

    async def _asave(self, tenant_id: str, payload: dict[str, Any]) -> None:
        await self._document(tenant_id).set(copy.deepcopy(payload))

    def load(self, tenant_id: str) -> dict[str, Any] | None:
        return _run_coroutine_sync(self._aload(tenant_id))

    def save(self, tenant_id: str, payload: dict[str, Any]) -> None:
        _run_coroutine_sync(self._asave(tenant_id, payload))


def build_catalog_draft_store(
    settings: PortalSettings,
    *,
    firestore_client: Any | None = None,
) -> CatalogDraftStore:
    """Select FILE fallback or FIRESTORE shared store from repository mode."""
    mode = str(settings.repository_mode or "").strip().upper()
    if mode == "FIRESTORE":
        return FirestoreCatalogDraftStore(settings, client=firestore_client)
    return FileCatalogDraftStore(settings.data_dir)


__all__ = [
    "CatalogDraftStore",
    "FileCatalogDraftStore",
    "FirestoreCatalogDraftStore",
    "MemoryCatalogDraftStore",
    "build_catalog_draft_store",
]
