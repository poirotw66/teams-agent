"""ASGI entry for the AI Ops Backoffice service (uvicorn / Cloud Run)."""

from __future__ import annotations

from composition.backoffice_app import create_backoffice_app

app = create_backoffice_app()
