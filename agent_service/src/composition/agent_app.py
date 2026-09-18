"""Agent FastAPI composition with Backoffice governance and hooks installed."""

from __future__ import annotations

from fastapi import FastAPI

from agent_service.api import create_app as create_agent_core_app
from agent_service.settings import RagSettings
from composition.agent_hooks import install_agent_hooks


def create_agent_app(settings: RagSettings | None = None) -> FastAPI:
    install_agent_hooks()
    return create_agent_core_app(settings)


# ASGI entry used by uvicorn / Cloud Run.
app = create_agent_app()
