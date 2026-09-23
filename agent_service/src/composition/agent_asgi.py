"""ASGI entry for the Agent service (uvicorn / Cloud Run)."""

from __future__ import annotations

from agent_service.runtime_dotenv import load_runtime_dotenv
from composition.agent_app import create_agent_app

load_runtime_dotenv()
app = create_agent_app()
