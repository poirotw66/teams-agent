"""Shared pytest fixtures for agent_service tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _install_composition_hooks() -> None:
    from ai_ops_backoffice.runtime_hooks import register_portal_app_factory
    from composition.agent_hooks import install_agent_hooks
    from composition.backoffice_agent_adapters import configure_backoffice_agent_adapters
    from composition.portal_agent_adapters import configure_portal_agent_adapters
    from composition.portal_app import create_portal_app

    configure_backoffice_agent_adapters()
    configure_portal_agent_adapters()
    install_agent_hooks()
    register_portal_app_factory(create_portal_app)
