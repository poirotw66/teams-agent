"""Compatibility shim — prefer `ai_ops_backoffice.routers.quality`.

Preserves `from ai_ops_backoffice.routers.quality_routes import register_quality_routes`.
"""

from __future__ import annotations

from .quality import register_quality_routes

__all__ = ["register_quality_routes"]
