"""Shared route context for workbench handlers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_ops_backoffice.adapters.workbench_json_store import WorkbenchJsonStore


@dataclass
class WorkbenchRouteContext:
    """Holds paths, collaborators, and state helpers for workbench routes."""

    data_dir: Path
    faqs_file: Path
    portal_state_file: Path
    chunks_file: Path
    tickets_file: Path
    state_file: Path
    query_service: Any
    knowledge_client: Any
    current_actor: Callable[..., Any]
    require_capability: Callable[[Any, str], None]
    store: WorkbenchJsonStore = field(default_factory=WorkbenchJsonStore)
    cached_chunks: list[dict[str, Any]] = field(default_factory=list)

    def get_cached_chunks(self) -> list[dict[str, Any]]:
        if not self.cached_chunks and self.chunks_file.exists():
            data = self.store.load(self.chunks_file)
            if data and isinstance(data, dict):
                self.cached_chunks = data.get("chunks", [])
        return self.cached_chunks

    def get_workbench_state(self) -> dict[str, Any]:
        state = self.store.load(self.state_file)
        if not isinstance(state, dict):
            state = {
                "resolved_conversations": [],
                "root_causes": {},
                "associated_tickets": {},
                "broadcast": None,
            }
        return state

    def save_workbench_state(self, state: dict[str, Any]) -> None:
        self.store.save(self.state_file, state)

    def get_all_tickets(self) -> list[dict[str, Any]]:
        raw = self.store.load(self.tickets_file)
        if isinstance(raw, list):
            return raw
        self.store.save(self.tickets_file, [])
        return []

    @staticmethod
    def normalize_workbench_ai_text(text: str) -> str:
        """Normalize headers and unpack inline numbered steps for clean rendering."""
        if not text or not text.strip():
            return text
        res = re.sub(r"(?m)^(?<!\*\*)問題：\s*([^\n]+)", r"**問題：** \1", text)
        res = re.sub(
            r"(?:\n\s*|\A)(?:\*\*)?處理方式：(?:\*\*)?\s*",
            r"\n\n**處理方式：**\n\n",
            res,
        )
        res = re.sub(
            r"(?<!\n)(?:([：:。；;!?！？])\s*|(\s+))(\d+)\.\s+",
            r"\1\n\3. ",
            res,
        )
        return res.strip()
