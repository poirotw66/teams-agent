"""Compatibility shim — prefer `ai_ops_backoffice.routers.workbench`.

Preserves `from ai_ops_backoffice.routers.workbench_router import register_workbench_routes`.
"""

from __future__ import annotations

from .workbench import register_workbench_routes

__all__ = ["register_workbench_routes"]
