"""Controlled BFF bridge from AI Ops Backoffice to Knowledge Portal."""

from __future__ import annotations

from .client import KnowledgePortalClient
from .formal_write_gate import (
    FORMAL_CLOUD_WRITE_CAPABILITIES,
    evaluate_knowledge_workspace_gate,
)
from .routes import build_knowledge_router

__all__ = [
    "FORMAL_CLOUD_WRITE_CAPABILITIES",
    "KnowledgePortalClient",
    "build_knowledge_router",
    "evaluate_knowledge_workspace_gate",
]
