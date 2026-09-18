"""ASGI entry for the Agent service (uvicorn / Cloud Run)."""

from __future__ import annotations

from composition.agent_app import create_agent_app

app = create_agent_app()
