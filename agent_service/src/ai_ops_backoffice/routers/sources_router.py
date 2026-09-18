"""Compatibility shim — prefer `ai_ops_backoffice.routers.sources`.

Preserves:
- `from ai_ops_backoffice.routers.sources_router import register_sources_routes`
- `parse_range_header` re-export
"""

from __future__ import annotations

from .sources import parse_range_header, register_sources_routes

__all__ = ["parse_range_header", "register_sources_routes"]
