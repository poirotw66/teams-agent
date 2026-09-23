"""ASGI entry for the Knowledge Portal service (uvicorn / Cloud Run)."""

from __future__ import annotations

from agent_service.runtime_dotenv import load_runtime_dotenv
from composition.portal_app import create_portal_app

load_runtime_dotenv()
app = create_portal_app()
