"""Controlled BFF bridge from AI Ops Backoffice to Knowledge Portal."""

from __future__ import annotations

from .client import KnowledgePortalClient
from .routes import build_knowledge_router

__all__ = ["KnowledgePortalClient", "build_knowledge_router"]
