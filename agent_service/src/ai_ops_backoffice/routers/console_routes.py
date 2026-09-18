"""Compatibility shim — prefer `ai_ops_backoffice.routers.console`.

Preserves `from ai_ops_backoffice.routers.console_routes import register_console_routes`.
"""

from __future__ import annotations

from .console import register_console_routes

__all__ = ["register_console_routes"]
