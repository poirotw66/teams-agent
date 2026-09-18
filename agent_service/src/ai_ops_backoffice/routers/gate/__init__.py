"""Quality gate API router package for policies, decisions, schedules, and release."""

from __future__ import annotations

from .routes import register_gate_routes

__all__ = ["register_gate_routes"]
