"""Typed workbench persistence repository (filesystem stays out of routers)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_ops_backoffice.adapters.workbench_json_store import WorkbenchJsonStore


@dataclass
class WorkbenchRepository:
    """Owns workbench JSON document paths and cache for route handlers."""

    data_dir: Path
    store: WorkbenchJsonStore = field(default_factory=WorkbenchJsonStore)
    _cached_chunks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def faqs_path(self) -> Path:
        return self.data_dir / "ops" / "phase2" / "faqs.json"

    @property
    def portal_state_path(self) -> Path:
        return self.data_dir / "portal_state" / "portal_state.json"

    @property
    def chunks_path(self) -> Path:
        return self.data_dir / "index" / "chunks.json"

    @property
    def tickets_path(self) -> Path:
        return self.data_dir / "ops" / "tickets.json"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "ops" / "workbench_state.json"

    def load_faqs(self) -> dict[str, Any]:
        data = self.store.load(self.faqs_path)
        return data if isinstance(data, dict) else {}

    def save_faqs(self, data: dict[str, Any]) -> None:
        self.store.save(self.faqs_path, data)

    def load_portal_state(self) -> dict[str, Any]:
        data = self.store.load(self.portal_state_path)
        return data if isinstance(data, dict) else {}

    def list_chunks(self) -> list[dict[str, Any]]:
        if not self._cached_chunks:
            data = self.store.load(self.chunks_path)
            if isinstance(data, dict):
                self._cached_chunks = list(data.get("chunks") or [])
        return self._cached_chunks

    def list_tickets(self) -> list[dict[str, Any]]:
        raw = self.store.load(self.tickets_path)
        if isinstance(raw, list):
            return raw
        self.store.save(self.tickets_path, [])
        return []

    def save_tickets(self, tickets: list[dict[str, Any]]) -> None:
        self.store.save(self.tickets_path, tickets)

    def load_state(self) -> dict[str, Any]:
        state = self.store.load(self.state_path)
        if isinstance(state, dict):
            return state
        return {
            "resolved_conversations": [],
            "root_causes": {},
            "associated_tickets": {},
            "broadcast": None,
        }

    def save_state(self, state: dict[str, Any]) -> None:
        self.store.save(self.state_path, state)
