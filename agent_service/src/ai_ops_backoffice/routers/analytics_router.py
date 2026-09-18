"""Compatibility shim — prefer `ai_ops_backoffice.routers.analytics`.

Preserves:
- `from ai_ops_backoffice.routers.analytics_router import register_analytics_routes`
- `ALLOWED_EXPORT_FORMATS` / `EXPORT_CAPABILITIES` re-exports
"""

from __future__ import annotations

from .analytics import (
    ALLOWED_EXPORT_FORMATS,
    EXPORT_CAPABILITIES,
    register_analytics_routes,
)

__all__ = [
    "ALLOWED_EXPORT_FORMATS",
    "EXPORT_CAPABILITIES",
    "register_analytics_routes",
]
