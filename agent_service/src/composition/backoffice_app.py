"""Backoffice FastAPI composition with in-process Knowledge Portal injected."""

from __future__ import annotations

from fastapi import FastAPI

from ai_ops_backoffice.api import create_app as create_backoffice_core_app
from ai_ops_backoffice.runtime_hooks import register_portal_app_factory
from ai_ops_backoffice.settings import BackofficeSettings
from composition.backoffice_agent_adapters import configure_backoffice_agent_adapters
from composition.portal_app import create_portal_app


def create_backoffice_app(
    settings: BackofficeSettings | None = None,
    **kwargs: object,
) -> FastAPI:
    configure_backoffice_agent_adapters()
    register_portal_app_factory(create_portal_app)
    return create_backoffice_core_app(
        settings=settings,
        portal_app_factory=create_portal_app,
        **kwargs,
    )
