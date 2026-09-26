"""Shared pytest fixtures for agent_service tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_gemini_backend_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolution is process-fixed; tests must not inherit a sibling case's mode."""
    from agent_service.gemini_backend import reset_gemini_backend_for_tests
    from agent_service.runtime_dotenv import reset_runtime_dotenv_for_tests

    reset_gemini_backend_for_tests()
    reset_runtime_dotenv_for_tests()
    monkeypatch.setenv("GEMINI_API_BACKEND", "DEVELOPER_API")
    yield
    reset_gemini_backend_for_tests()
    reset_runtime_dotenv_for_tests()


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
