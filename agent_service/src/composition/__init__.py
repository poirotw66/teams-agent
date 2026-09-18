"""Composition root: wire domain ports without reverse domain imports."""

from __future__ import annotations

from composition.agent_hooks import install_agent_hooks
from composition.portal_app import create_portal_app

__all__ = ["create_portal_app", "install_agent_hooks"]
