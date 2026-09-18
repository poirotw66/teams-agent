"""Composition root: wire domain ports without reverse domain imports."""

from __future__ import annotations

from composition.agent_app import create_agent_app
from composition.agent_hooks import install_agent_hooks
from composition.backoffice_app import create_backoffice_app
from composition.portal_app import create_portal_app

__all__ = [
    "create_agent_app",
    "create_backoffice_app",
    "create_portal_app",
    "install_agent_hooks",
]
