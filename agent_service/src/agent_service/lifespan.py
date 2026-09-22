"""Application lifespan: build and wire runtime collaborators once at startup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .lifespan_wiring import startup_agent_runtime
from .settings import RagSettings


def build_lifespan(resolved_settings: RagSettings):
    """Return a FastAPI lifespan context manager bound to ``resolved_settings``."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await startup_agent_runtime(app, resolved_settings)
        try:
            yield
        finally:
            syncer = getattr(app.state, "knowledge_release_syncer", None)
            if syncer is not None:
                syncer.stop_background()

    return lifespan
