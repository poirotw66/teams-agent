"""Shared route context for workbench handlers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ai_ops_backoffice.adapters.workbench_repository import WorkbenchRepository


@dataclass
class WorkbenchRouteContext:
    """Collaborators for workbench HTTP handlers (no filesystem Paths)."""

    repository: WorkbenchRepository
    query_service: Any
    knowledge_client: Any
    current_actor: Callable[..., Any]
    require_capability: Callable[[Any, str], None]

    @property
    def data_dir(self):
        return self.repository.data_dir

    def get_cached_chunks(self) -> list[dict[str, Any]]:
        return self.repository.list_chunks()

    def get_workbench_state(self) -> dict[str, Any]:
        return self.repository.load_state()

    def save_workbench_state(self, state: dict[str, Any]) -> None:
        self.repository.save_state(state)

    def get_all_tickets(self) -> list[dict[str, Any]]:
        return self.repository.list_tickets()

    def save_all_tickets(self, tickets: list[dict[str, Any]]) -> None:
        self.repository.save_tickets(tickets)

    def load_faqs(self) -> dict[str, Any]:
        return self.repository.load_faqs()

    def save_faqs(self, data: dict[str, Any]) -> None:
        self.repository.save_faqs(data)

    def load_portal_state(self) -> dict[str, Any]:
        return self.repository.load_portal_state()

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
