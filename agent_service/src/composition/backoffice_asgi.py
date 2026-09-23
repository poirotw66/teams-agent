"""ASGI entry for the AI Ops Backoffice service (uvicorn / Cloud Run)."""

from __future__ import annotations

from agent_service.runtime_dotenv import load_runtime_dotenv
from composition.backoffice_app import create_backoffice_app

load_runtime_dotenv()
app = create_backoffice_app()
