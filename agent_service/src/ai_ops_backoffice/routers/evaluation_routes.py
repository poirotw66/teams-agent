"""Compatibility shim — prefer `ai_ops_backoffice.routers.evaluation`.

Preserves `from ai_ops_backoffice.routers.evaluation_routes import register_evaluation_routes`.
"""

from __future__ import annotations

from .evaluation import register_evaluation_routes

__all__ = ["register_evaluation_routes"]
