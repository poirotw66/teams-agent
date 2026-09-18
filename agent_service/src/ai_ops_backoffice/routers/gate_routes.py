"""Compatibility shim — prefer `ai_ops_backoffice.routers.gate`.

Preserves `from ai_ops_backoffice.routers.gate_routes import register_gate_routes`.
"""

from __future__ import annotations

from .gate import register_gate_routes

__all__ = ["register_gate_routes"]
