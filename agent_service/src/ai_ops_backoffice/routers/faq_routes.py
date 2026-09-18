"""Compatibility shim — prefer `ai_ops_backoffice.routers.faq`.

Preserves `from ai_ops_backoffice.routers.faq_routes import register_faq_routes`.
"""

from __future__ import annotations

from .faq import register_faq_routes

__all__ = ["register_faq_routes"]
