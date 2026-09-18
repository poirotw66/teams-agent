"""ASGI entry for the Knowledge Portal service (uvicorn / Cloud Run)."""

from __future__ import annotations

from composition.portal_app import create_portal_app

app = create_portal_app()
