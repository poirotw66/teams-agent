"""Durable export authorization registry (survives process restart)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from agent_service.operations.access import ActorContext

from .export_authorization import RoleRevalidatingExportAuthorizationResolver


class FileBackedExportAuthorizationResolver(RoleRevalidatingExportAuthorizationResolver):
    """Persist role/owner-unit bindings so workers can re-resolve after restart."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._file_lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        records = payload.get("records") or {}
        revoked = payload.get("revoked") or []
        loaded: dict[tuple[str, str], tuple[str, str, tuple[str, ...]]] = {}
        for key, value in records.items():
            user_id, _, tenant_id = str(key).partition("::")
            loaded[(user_id, tenant_id)] = (
                str(value["role"]),
                str(value["display_name"]),
                tuple(value.get("owner_unit_ids") or ()),
            )
        self._records = loaded
        self._revoked = set(str(item) for item in revoked)

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "records": {
                f"{user_id}::{tenant_id}": {
                    "role": role,
                    "display_name": display_name,
                    "owner_unit_ids": list(owner_units),
                }
                for (user_id, tenant_id), (role, display_name, owner_units) in self._records.items()
            },
            "revoked": sorted(self._revoked),
        }
        temporary = self._path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._path)

    def register(self, *, actor: ActorContext, tenant_id: str) -> None:
        with self._file_lock:
            super().register(actor=actor, tenant_id=tenant_id)
            self._persist()

    def revoke(self, requester_id: str) -> None:
        with self._file_lock:
            super().revoke(requester_id)
            self._persist()
