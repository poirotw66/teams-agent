"""Shared pytest fixtures for agent_service tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _install_composition_hooks() -> None:
    from composition.agent_hooks import install_agent_hooks

    install_agent_hooks()
